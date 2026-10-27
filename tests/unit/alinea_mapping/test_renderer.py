from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

import pytest
from alinea_contracts import AlineaError, RenderArtifact
from alinea_mapping import renderer as renderer_module
from alinea_mapping.renderer import (
    DEFAULT_TIMEOUT_SECONDS,
    LibreOfficeRenderer,
    RendererAdapter,
    cache_key_for_docx,
    cached_pdf_path,
    find_soffice,
    font_environment_hash,
    render_cache_key,
    sha256_file,
)
from docx import Document
from reportlab.pdfgen import canvas


def make_pdf(path: Path, page_count: int = 1) -> None:
    document = canvas.Canvas(str(path), pagesize=(612, 792))
    for page in range(page_count):
        document.setFont("Helvetica", 11)
        document.drawString(72, 730, f"Rendered page {page + 1}")
        document.showPage()
    document.save()


def write_docx(path: Path, text: str = "Renderer fixture") -> None:
    document = Document()
    document.add_paragraph(text)
    document.save(path)


class FakeSoffice:
    def __init__(self, *, pages: int = 1, timeout: bool = False, no_output: bool = False):
        self.pages = pages
        self.timeout = timeout
        self.no_output = no_output
        self.commands: list[list[str]] = []
        self.kwargs: list[dict] = []
        self.isolation_checks: list[tuple[bool, bool, bool]] = []

    def __call__(self, command, **kwargs):
        command = list(command)
        self.commands.append(command)
        self.kwargs.append(kwargs)
        if command[1] == "--version":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="LibreOffice Test 1.2.3",
                stderr="",
            )
        if self.timeout:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if not self.no_output:
            output_dir = Path(command[command.index("--outdir") + 1])
            input_path = Path(command[-1])
            profile_uri = next(
                value.split("=", 1)[1]
                for value in command
                if value.startswith("-env:UserInstallation=")
            )
            profile_path = Path(url2pathname(urlsplit(profile_uri).path))
            self.isolation_checks.append(
                (
                    profile_path.is_dir() and profile_path != output_dir,
                    output_dir.is_dir() and input_path.parent != output_dir,
                    input_path.read_bytes().startswith(b"PK"),
                )
            )
            make_pdf(output_dir / "input.pdf", self.pages)
        return subprocess.CompletedProcess(command, 0, stdout="converted", stderr="")


def test_find_soffice_prefers_config_then_environment(tmp_path):
    configured = tmp_path / "configured.exe"
    from_environment = tmp_path / "environment.exe"
    configured.write_bytes(b"configured")
    from_environment.write_bytes(b"environment")
    assert find_soffice(
        configured,
        environ={"ALINEA_SOFFICE_PATH": str(from_environment)},
    ) == configured.resolve()
    assert find_soffice(
        environ={"ALINEA_SOFFICE_PATH": str(from_environment)}
    ) == from_environment.resolve()


def test_find_soffice_checks_workspace_tools(monkeypatch, tmp_path):
    executable = tmp_path / ".tools" / "LibreOffice" / "program" / "soffice.com"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"soffice")
    monkeypatch.setattr(renderer_module, "_windows_candidates", lambda environ: [])
    assert find_soffice(
        environ={"PATH": ""},
        workspace_root=tmp_path,
    ) == executable.resolve()


def test_cache_key_uses_content_profile_and_exporter_digest(tmp_path):
    first = tmp_path / "first" / "same.docx"
    second = tmp_path / "second" / "same.docx"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"revision-one")
    second.write_bytes(b"revision-two")
    exporter = "a" * 64
    first_key = cache_key_for_docx(first, "local-lo", exporter)
    assert first_key != cache_key_for_docx(second, "local-lo", exporter)
    assert first_key != render_cache_key(sha256_file(first), "other-profile", exporter)
    assert first_key != render_cache_key(sha256_file(first), "local-lo", "b" * 64)
    second.write_bytes(b"revision-one")
    assert first_key == cache_key_for_docx(second, "local-lo", exporter)
    with pytest.raises(ValueError):
        cached_pdf_path(tmp_path, "../outside")


def test_missing_renderer_raises_retryable_503(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer_module, "find_soffice", lambda *args, **kwargs: None)
    renderer = LibreOfficeRenderer(environ={"PATH": ""}, workspace_root=tmp_path)
    with pytest.raises(AlineaError) as caught:
        renderer.render(tmp_path / "missing.docx", tmp_path / "output")
    assert caught.value.code == "RENDERER_UNAVAILABLE"
    assert caught.value.status_code == 503
    assert caught.value.retryable is True


def test_render_checks_command_isolation_metadata_and_cache(monkeypatch, tmp_path):
    executable = tmp_path / "soffice.com"
    executable.write_bytes(b"fake executable")
    fake = FakeSoffice()
    monkeypatch.setattr(renderer_module.subprocess, "run", fake)
    font_dir = tmp_path / "fonts"
    font_dir.mkdir()
    (font_dir / "test.ttf").write_bytes(b"font environment")
    renderer = LibreOfficeRenderer(
        executable,
        environ={"PATH": ""},
        workspace_root=tmp_path,
        font_dirs=[font_dir],
        locale_id="zh-CN",
    )
    assert DEFAULT_TIMEOUT_SECONDS == 90.0
    assert renderer.timeout_seconds == 90.0
    assert isinstance(renderer, RendererAdapter)

    source = tmp_path / "external-name.docx"
    write_docx(source)
    output = tmp_path / "output"
    artifact = renderer.render(source, output)
    assert isinstance(artifact, RenderArtifact)
    assert artifact.page_count == 1
    assert artifact.render_profile_id == "local-lo"
    assert artifact.pdf_sha256 == sha256_file(artifact.pdf_path)
    assert Path(artifact.pdf_path).read_bytes().startswith(b"%PDF-")
    assert Path(artifact.pdf_path).parent == output.resolve()
    assert "external-name" not in Path(artifact.pdf_path).name
    assert len(fake.commands) == 2
    assert fake.isolation_checks == [(True, True, True)]

    command = fake.commands[1]
    assert command[1:6] == [
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--nodefault",
        "--nofirststartwizard",
    ]
    assert fake.kwargs[1]["timeout"] == 90.0
    assert Path(command[-1]).name == "input.docx"
    profile_uri = next(
        value.split("=", 1)[1]
        for value in command
        if value.startswith("-env:UserInstallation=")
    )
    assert urlsplit(profile_uri).scheme == "file"
    assert "\\" not in profile_uri

    profile = renderer.describe_profile()
    docx_digest = sha256_file(source)
    expected_key = render_cache_key(
        docx_digest,
        "local-lo",
        profile.exporter_config_digest,
    )
    assert Path(artifact.pdf_path) == cached_pdf_path(output, expected_key)
    metadata = json.loads(
        (Path(artifact.pdf_path).with_suffix(".profile.json")).read_text(encoding="utf-8")
    )
    assert metadata["renderer_version"] == "LibreOffice Test 1.2.3"
    assert metadata["font_environment_sha256"] == font_environment_hash([font_dir])
    assert metadata["exporter_config_digest"] == profile.exporter_config_digest
    assert metadata["locale"] == "zh-CN"
    assert metadata["export_config"]["filter"] == "writer_pdf_Export"
    assert metadata["docx_sha256"] == docx_digest

    cached = renderer.render(source, output)
    assert cached.pdf_path == artifact.pdf_path
    assert len(fake.commands) == 2

    first_profile_path = Path(url2pathname(urlsplit(profile_uri).path))
    write_docx(source, "Changed renderer fixture")
    changed = renderer.render(source, output)
    assert changed.pdf_path != artifact.pdf_path
    assert len(fake.commands) == 3
    changed_command = fake.commands[-1]
    changed_uri = next(
        value.split("=", 1)[1]
        for value in changed_command
        if value.startswith("-env:UserInstallation=")
    )
    assert changed_uri != profile_uri
    assert not first_profile_path.exists()


def test_render_timeout_and_missing_output_never_return_fake_pdf(monkeypatch, tmp_path):
    executable = tmp_path / "soffice.com"
    executable.write_bytes(b"fake executable")
    source = tmp_path / "input.docx"
    write_docx(source)
    for fake in (FakeSoffice(timeout=True), FakeSoffice(no_output=True)):
        monkeypatch.setattr(renderer_module.subprocess, "run", fake)
        renderer = LibreOfficeRenderer(
            executable,
            environ={"PATH": ""},
            workspace_root=tmp_path,
            font_dirs=[],
        )
        with pytest.raises(AlineaError) as caught:
            renderer.render(source, tmp_path / f"output-{len(fake.commands)}-{fake.timeout}")
        assert caught.value.code == "PDF_RENDER_FAILED"
        assert not list(tmp_path.glob("output-*/*.pdf"))


def test_render_enforces_configurable_max_pages(monkeypatch, tmp_path):
    executable = tmp_path / "soffice.com"
    executable.write_bytes(b"fake executable")
    monkeypatch.setattr(renderer_module.subprocess, "run", FakeSoffice(pages=2))
    source = tmp_path / "input.docx"
    write_docx(source)
    output = tmp_path / "output"
    renderer = LibreOfficeRenderer(
        executable,
        max_pages=1,
        environ={"PATH": ""},
        workspace_root=tmp_path,
        font_dirs=[],
    )
    with pytest.raises(AlineaError) as caught:
        renderer.render(source, output)
    assert caught.value.code == "PDF_RENDER_FAILED"
    assert caught.value.details["page_count"] == 2
    assert not list(output.glob("*.pdf"))
