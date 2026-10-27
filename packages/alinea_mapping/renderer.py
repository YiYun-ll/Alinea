from __future__ import annotations

import hashlib
import json
import locale as locale_module
import os
import re
import shutil
import subprocess  # noqa: S404
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol, runtime_checkable

import pdfplumber
from alinea_contracts import AlineaError, RenderArtifact
from pydantic import JsonValue

DEFAULT_PROFILE_ID = "local-lo"
DEFAULT_MAX_PAGES = 60
DEFAULT_TIMEOUT_SECONDS = 90.0
_COMMAND_FLAGS = (
    "--headless",
    "--norestore",
    "--nolockcheck",
    "--nodefault",
    "--nofirststartwizard",
)
_CACHE_KEY = re.compile(r"[0-9a-f]{64}")
_FONT_SUFFIXES = {".fon", ".otf", ".ttc", ".ttf"}
_FONT_HASH_CACHE: dict[tuple[tuple[str, int, int], ...], str] = {}
_VERSION_CACHE: dict[tuple[str, int], str] = {}
_CACHE_LOCK = Lock()


@runtime_checkable
class RendererAdapter(Protocol):
    def render(
        self,
        docx_path: str | Path,
        output_dir: str | Path,
        profile_id: str = DEFAULT_PROFILE_ID,
    ) -> RenderArtifact: ...


@dataclass(frozen=True, slots=True)
class RenderProfile:
    profile_id: str
    renderer_version: str
    font_environment_sha256: str
    exporter_config_digest: str
    locale: str
    export_config: dict[str, JsonValue]

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "profile_id": self.profile_id,
            "renderer_version": self.renderer_version,
            "font_environment_sha256": self.font_environment_sha256,
            "exporter_config_digest": self.exporter_config_digest,
            "locale": self.locale,
            "export_config": self.export_config,
        }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render_cache_key(
    docx_sha256: str,
    profile_id: str,
    exporter_config_digest: str,
) -> str:
    if not _CACHE_KEY.fullmatch(docx_sha256):
        raise ValueError("docx_sha256 must be a lowercase SHA-256 digest")
    if not _CACHE_KEY.fullmatch(exporter_config_digest):
        raise ValueError("exporter_config_digest must be a lowercase SHA-256 digest")
    if not profile_id:
        raise ValueError("profile_id must not be empty")
    payload = _canonical_json(
        {
            "docx_sha256": docx_sha256,
            "profile_id": profile_id,
            "exporter_config_digest": exporter_config_digest,
        }
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def cache_key_for_docx(
    docx_path: str | Path,
    profile_id: str,
    exporter_config_digest: str,
) -> str:
    return render_cache_key(sha256_file(docx_path), profile_id, exporter_config_digest)


def cached_pdf_path(cache_dir: str | Path, cache_key: str) -> Path:
    if not _CACHE_KEY.fullmatch(cache_key):
        raise ValueError("invalid render cache key")
    root = Path(cache_dir).resolve()
    path = (root / f"{cache_key}.pdf").resolve()
    if path.parent != root:
        raise ValueError("render cache path escapes its cache directory")
    return path


def _from_directory(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    names = (
        "program/soffice.com",
        "program/soffice.exe",
        "program/soffice",
        "soffice.com",
        "soffice.exe",
        "soffice",
        "libreoffice",
    )
    return [path / name for name in names]


def _windows_candidates(environ: Mapping[str, str]) -> list[Path]:
    roots = [
        environ.get("ProgramFiles"),
        environ.get("ProgramFiles(x86)"),
        environ.get("ProgramW6432"),
    ]
    candidates = [
        Path(root) / "LibreOffice" / "program" / "soffice.com"
        for root in roots
        if root
    ]
    candidates.extend(
        Path(root) / "LibreOffice" / "program" / "soffice.exe"
        for root in roots
        if root
    )
    local_app_data = environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.extend(
            [
                Path(local_app_data)
                / "Programs"
                / "LibreOffice"
                / "program"
                / "soffice.com",
                Path(local_app_data)
                / "Programs"
                / "LibreOffice"
                / "program"
                / "soffice.exe",
            ]
        )
    if os.name == "nt":
        candidates.extend(
            [
                Path("C:/Program Files/LibreOffice/program/soffice.com"),
                Path("C:/Program Files (x86)/LibreOffice/program/soffice.com"),
                Path("C:/Program Files/LibreOffice/program/soffice.exe"),
                Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
            ]
        )
    return candidates


def _workspace_candidates(workspace_root: Path) -> list[Path]:
    tools = workspace_root / ".tools"
    candidates: list[Path] = []
    for relative in (
        "LibreOffice",
        "libreoffice",
        "LibreOfficePortable/App/libreoffice",
        ".",
    ):
        candidates.extend(_from_directory(tools / relative))
    for pattern in ("*/program/soffice.exe", "*/program/soffice"):
        candidates.extend(tools.glob(pattern))
    return candidates


def find_soffice(
    configured_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    workspace_root: str | Path | None = None,
) -> Path | None:
    env = os.environ if environ is None else environ
    root = (
        Path(workspace_root).resolve()
        if workspace_root is not None
        else Path(__file__).resolve().parents[2]
    )
    candidates: list[Path] = []
    for value in (configured_path, env.get("ALINEA_SOFFICE_PATH")):
        if value:
            path = Path(value).expanduser()
            candidates.append(path)
            candidates.extend(_from_directory(path))
    path_value = env.get("PATH")
    for executable in ("soffice", "libreoffice"):
        resolved = shutil.which(executable, path=path_value)
        if resolved:
            candidates.append(Path(resolved))
    candidates.extend(_windows_candidates(env))
    candidates.extend(_workspace_candidates(root))

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate.resolve()
    return None


def _default_font_dirs(environ: Mapping[str, str], workspace_root: Path) -> list[Path]:
    directories = [
        workspace_root / ".tools" / "fonts",
        workspace_root / ".tools" / "LibreOffice" / "share" / "fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".local" / "share" / "fonts",
    ]
    if environ.get("WINDIR"):
        directories.append(Path(environ["WINDIR"]) / "Fonts")
    if environ.get("ALINEA_FONT_PATHS"):
        directories.extend(
            Path(value)
            for value in environ["ALINEA_FONT_PATHS"].split(os.pathsep)
            if value
        )
    return directories


def font_environment_hash(font_dirs: Sequence[str | Path]) -> str:
    files: list[tuple[str, Path]] = []
    signature_parts: list[tuple[str, int, int]] = []
    for configured_root in font_dirs:
        root = Path(configured_root)
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in _FONT_SUFFIXES:
                files.append((path.relative_to(root).as_posix(), path))
                stat = path.stat()
                signature_parts.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns)
                )
    signature = tuple(sorted(signature_parts))
    with _CACHE_LOCK:
        cached = _FONT_HASH_CACHE.get(signature)
        if cached is not None:
            return cached
    digest = hashlib.sha256(b"alinea-font-environment-v1\0")
    for relative_path, path in sorted(files):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    result = digest.hexdigest()
    with _CACHE_LOCK:
        if len(_FONT_HASH_CACHE) >= 16:
            _FONT_HASH_CACHE.clear()
        _FONT_HASH_CACHE[signature] = result
    return result


def _unavailable(message: str, details: dict[str, JsonValue] | None = None) -> AlineaError:
    return AlineaError(
        "RENDERER_UNAVAILABLE",
        message,
        status_code=503,
        retryable=True,
        details=details,
    )


def _render_failed(
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, JsonValue] | None = None,
) -> AlineaError:
    return AlineaError(
        "PDF_RENDER_FAILED",
        message,
        status_code=500,
        retryable=retryable,
        details=details,
    )


class LibreOfficeRenderer:
    def __init__(
        self,
        soffice_path: str | Path | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_pages: int = DEFAULT_MAX_PAGES,
        cache_dir: str | Path | None = None,
        pdf_filter_options: Mapping[str, JsonValue] | None = None,
        font_dirs: Sequence[str | Path] | None = None,
        locale_id: str | None = None,
        environ: Mapping[str, str] | None = None,
        workspace_root: str | Path | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        self.soffice_path = soffice_path
        self.timeout_seconds = float(timeout_seconds)
        self.max_pages = max_pages
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.pdf_filter_options = dict(pdf_filter_options or {})
        self.environ = dict(os.environ if environ is None else environ)
        self.workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.font_dirs = list(
            font_dirs
            if font_dirs is not None
            else _default_font_dirs(self.environ, self.workspace_root)
        )
        self.locale_id = locale_id or (
            self.environ.get("LC_ALL")
            or self.environ.get("LC_CTYPE")
            or self.environ.get("LANG")
            or locale_module.getencoding()
        )
        self._profiles: dict[str, RenderProfile] = {}

    def _executable(self) -> Path:
        executable = find_soffice(
            self.soffice_path,
            environ=self.environ,
            workspace_root=self.workspace_root,
        )
        if executable is None:
            raise _unavailable(
                "LibreOffice soffice executable was not found",
                {"profile_id": self.soffice_path and str(self.soffice_path)},
            )
        return executable

    def _version(self, executable: Path) -> str:
        resolved = executable.resolve()
        cache_key = (str(resolved), resolved.stat().st_mtime_ns)
        with _CACHE_LOCK:
            cached = _VERSION_CACHE.get(cache_key)
            if cached is not None:
                return cached
        try:
            result = subprocess.run(  # noqa: S603
                [str(resolved), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(self.timeout_seconds, 45.0),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _unavailable(
                "LibreOffice could not be started for version detection",
                {"reason": type(exc).__name__},
            ) from exc
        version = result.stdout.strip() or result.stderr.strip()
        if result.returncode != 0 or not version:
            raise _unavailable(
                "LibreOffice version detection failed",
                {"returncode": result.returncode},
            )
        with _CACHE_LOCK:
            _VERSION_CACHE[cache_key] = version
        return version

    def describe_profile(self, profile_id: str = DEFAULT_PROFILE_ID) -> RenderProfile:
        if not profile_id:
            raise ValueError("profile_id must not be empty")
        if profile_id in self._profiles:
            return self._profiles[profile_id]
        executable = self._executable()
        version = self._version(executable)
        font_hash = font_environment_hash(self.font_dirs)
        export_config: dict[str, JsonValue] = {
            "format": "pdf",
            "filter": "writer_pdf_Export",
            "filter_options": self.pdf_filter_options,
        }
        exporter_digest = hashlib.sha256(
            _canonical_json(
                {
                    "renderer": "libreoffice",
                    "renderer_version": version,
                    "font_environment_sha256": font_hash,
                    "locale": self.locale_id,
                    "command_flags": _COMMAND_FLAGS,
                    "export_config": export_config,
                }
            ).encode("utf-8")
        ).hexdigest()
        profile = RenderProfile(
            profile_id=profile_id,
            renderer_version=version,
            font_environment_sha256=font_hash,
            exporter_config_digest=exporter_digest,
            locale=self.locale_id,
            export_config=export_config,
        )
        self._profiles[profile_id] = profile
        return profile

    def _export_spec(self, profile: RenderProfile) -> str:
        spec = "pdf:writer_pdf_Export"
        if self.pdf_filter_options:
            spec = f"{spec}:{_canonical_json(self.pdf_filter_options)}"
        return spec

    def _warnings(self, profile: RenderProfile) -> list[str]:
        environment = _canonical_json(profile.as_dict())
        return [
            "Preview rendered by LibreOffice; Microsoft Word may paginate differently.",
            f"Render environment: {environment}",
        ]

    def _page_count(self, pdf_path: Path, profile_id: str) -> int:
        try:
            with pdf_path.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError("missing PDF header")
            with pdfplumber.open(str(pdf_path)) as pdf:
                return len(pdf.pages)
        except Exception as exc:
            raise _render_failed(
                "LibreOffice output is not a readable PDF",
                details={"profile_id": profile_id, "reason": type(exc).__name__},
            ) from exc

    def _check_page_count(self, page_count: int, profile_id: str) -> None:
        if page_count > self.max_pages:
            raise _render_failed(
                "Rendered PDF exceeds the configured page limit",
                details={
                    "profile_id": profile_id,
                    "page_count": page_count,
                    "max_pages": self.max_pages,
                },
            )

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.stem}-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
            shutil.copyfile(source, temporary_name)
            os.replace(temporary_name, destination)
        finally:
            if temporary_name is not None and os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def _atomic_write(destination: Path, content: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=f".{destination.stem}-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary_name = temporary.name
            os.replace(temporary_name, destination)
        finally:
            if temporary_name is not None and os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _record_profile(
        self,
        pdf_path: Path,
        profile: RenderProfile,
        *,
        docx_sha256: str,
        pdf_sha256: str,
        cache_key: str,
        page_count: int,
    ) -> None:
        metadata = profile.as_dict()
        metadata.update(
            {
                "docx_sha256": docx_sha256,
                "pdf_sha256": pdf_sha256,
                "cache_key": cache_key,
                "page_count": page_count,
            }
        )
        self._atomic_write(
            pdf_path.with_suffix(".profile.json"),
            _canonical_json(metadata),
        )

    def _artifact(
        self,
        pdf_path: Path,
        profile: RenderProfile,
        *,
        docx_sha256: str,
        cache_key: str,
    ) -> RenderArtifact:
        page_count = self._page_count(pdf_path, profile.profile_id)
        self._check_page_count(page_count, profile.profile_id)
        pdf_sha256 = sha256_file(pdf_path)
        self._record_profile(
            pdf_path,
            profile,
            docx_sha256=docx_sha256,
            pdf_sha256=pdf_sha256,
            cache_key=cache_key,
            page_count=page_count,
        )
        return RenderArtifact(
            pdf_path=str(pdf_path.resolve()),
            pdf_sha256=pdf_sha256,
            render_profile_id=profile.profile_id,
            page_count=page_count,
            warnings=self._warnings(profile),
        )

    def render(
        self,
        docx_path: str | Path,
        output_dir: str | Path,
        profile_id: str = DEFAULT_PROFILE_ID,
    ) -> RenderArtifact:
        source = Path(docx_path).expanduser().resolve()
        if not source.is_file():
            self._executable()
            raise _render_failed(
                "DOCX input does not exist or is not a file",
                details={"profile_id": profile_id},
            )
        from alinea_docx.security import read_secure_docx

        safe_package = read_secure_docx(source)
        unsafe_relationships = [
            relationship
            for relationship in safe_package.report.external_relationships
            if relationship["type"].rsplit("/", 1)[-1]
            in {"image", "oleObject", "package", "attachedTemplate", "externalLink", "control"}
        ]
        if unsafe_relationships:
            raise AlineaError(
                "DOCX_UNSAFE_EXTERNAL_RESOURCE",
                "Documents with external embedded resources cannot be sent to the renderer",
                status_code=422,
                details={
                    "relationship_ids": [
                        relationship["id"] for relationship in unsafe_relationships
                    ]
                },
            )
        profile = self.describe_profile(profile_id)
        docx_digest = safe_package.sha256
        cache_key = render_cache_key(
            docx_digest,
            profile_id,
            profile.exporter_config_digest,
        )
        destination_root = Path(output_dir).expanduser().resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        cache_root = (
            self.cache_dir.expanduser().resolve()
            if self.cache_dir is not None
            else destination_root
        )
        cache_root.mkdir(parents=True, exist_ok=True)
        cached_path = cached_pdf_path(cache_root, cache_key)
        destination_path = cached_pdf_path(destination_root, cache_key)

        if cached_path.is_file():
            try:
                if cached_path != destination_path:
                    self._atomic_copy(cached_path, destination_path)
                return self._artifact(
                    destination_path,
                    profile,
                    docx_sha256=docx_digest,
                    cache_key=cache_key,
                )
            except AlineaError as exc:
                if exc.details.get("page_count") is not None:
                    raise

        executable = self._executable()
        with (
            tempfile.TemporaryDirectory(prefix="alinea-lo-profile-") as profile_dir,
            tempfile.TemporaryDirectory(prefix="alinea-lo-output-") as conversion_dir,
            tempfile.TemporaryDirectory(prefix="alinea-lo-input-") as input_dir,
        ):
            isolated_input = Path(input_dir) / "input.docx"
            shutil.copyfile(source, isolated_input)
            profile_uri = Path(profile_dir).resolve().as_uri()
            command = [
                str(executable),
                *_COMMAND_FLAGS,
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                self._export_spec(profile),
                "--outdir",
                str(Path(conversion_dir).resolve()),
                str(isolated_input.resolve()),
            ]
            try:
                result = subprocess.run(  # noqa: S603
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise _render_failed(
                    "LibreOffice PDF conversion timed out",
                    retryable=True,
                    details={
                        "profile_id": profile_id,
                        "timeout_seconds": self.timeout_seconds,
                    },
                ) from exc
            except OSError as exc:
                raise _unavailable(
                    "LibreOffice could not be started",
                    {"profile_id": profile_id, "reason": type(exc).__name__},
                ) from exc
            if result.returncode != 0:
                raise _render_failed(
                    "LibreOffice PDF conversion failed",
                    details={
                        "profile_id": profile_id,
                        "returncode": result.returncode,
                        "stdout": result.stdout[-4000:],
                        "stderr": result.stderr[-4000:],
                    },
                )
            converted_pdf = Path(conversion_dir).resolve() / "input.pdf"
            if (
                converted_pdf.parent != Path(conversion_dir).resolve()
                or not converted_pdf.is_file()
            ):
                raise _render_failed(
                    "LibreOffice did not produce the expected PDF",
                    details={
                        "profile_id": profile_id,
                        "stdout": result.stdout[-4000:],
                        "stderr": result.stderr[-4000:],
                    },
                )
            page_count = self._page_count(converted_pdf, profile_id)
            self._check_page_count(page_count, profile_id)
            self._atomic_copy(converted_pdf, cached_path)
        if cached_path != destination_path:
            self._atomic_copy(cached_path, destination_path)
        return self._artifact(
            destination_path,
            profile,
            docx_sha256=docx_digest,
            cache_key=cache_key,
        )
