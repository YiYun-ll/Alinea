from __future__ import annotations

import subprocess
from pathlib import Path

from alinea_mapping.renderer import LibreOfficeRenderer, font_environment_hash


def test_version_probe_is_cached_per_executable(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "soffice.com"
    executable.write_bytes(b"fake")
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="LibreOffice Test 1.0", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    first = LibreOfficeRenderer(executable, font_dirs=[])
    second = LibreOfficeRenderer(executable, font_dirs=[])
    assert first._version(executable) == second._version(executable) == "LibreOffice Test 1.0"
    assert len(calls) == 1


def test_font_hash_cache_hits_and_invalidates_on_metadata_change(tmp_path) -> None:
    font = tmp_path / "fixture.ttf"
    font.write_bytes(b"first-font")
    original_open = Path.open
    calls = []
    def counted_open(self, *args, **kwargs):
        calls.append(self)
        return original_open(self, *args, **kwargs)
    Path.open = counted_open
    first = font_environment_hash([tmp_path])
    calls.clear()
    assert font_environment_hash([tmp_path]) == first
    assert calls == []
    font.write_bytes(b"changed-font-content")
    assert font_environment_hash([tmp_path]) != first
    Path.open = original_open
