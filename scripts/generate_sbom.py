from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def run_json(command: list[str], cwd: Path) -> object:
    result = subprocess.run(  # noqa: S603 - fixed local executable and arguments
        command, cwd=cwd, capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def main() -> None:
    REPORTS.mkdir(exist_ok=True)
    executable_dir = Path(sys.executable).parent
    pip_licenses = executable_dir / ("pip-licenses.exe" if os.name == "nt" else "pip-licenses")
    python_packages = run_json(
        [str(pip_licenses), "--format=json", "--with-urls", "--with-system"], ROOT
    )
    license_checker = ROOT / "apps" / "web" / "node_modules" / ".bin" / (
        "license-checker.cmd" if os.name == "nt" else "license-checker"
    )
    javascript_packages = run_json([str(license_checker), "--json"], ROOT / "apps" / "web")
    renderer = ROOT / ".tools" / "LibreOffice" / "program" / (
        "soffice.com" if os.name == "nt" else "soffice"
    )
    renderer_version = None
    if renderer.exists():
        renderer_version = subprocess.run(  # noqa: S603 - fixed renderer path and version flag
            [str(renderer), "--version"], capture_output=True, text=True, check=True
        ).stdout.strip()
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "python": python_packages,
        "javascript": javascript_packages,
        "renderer": {"version": renderer_version, "path_scope": "project-local or system"},
        "container_images": {"status": "not_built", "digests": []},
        "notes": [
            "Generated from installed dependencies, not from an imagined dependency list.",
            "Container digests require an actual Docker build; unavailable builds "
            "remain unverified.",
            "Font packages require separate distribution review; restricted fonts are not bundled.",
        ],
    }
    destination = REPORTS / "SBOM.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
