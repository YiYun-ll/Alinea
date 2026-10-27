from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_real_document_full_flow() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(  # noqa: S603 - fixed local Python and script
        [sys.executable, "scripts/smoke_e2e.py"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"text_and_media_identical": true' in result.stdout
    assert '"repair_jobs": 2' in result.stdout
    assert '"retry_recovered": true' in result.stdout
