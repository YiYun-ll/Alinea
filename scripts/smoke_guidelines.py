from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".data" / "guideline-e2e"
if WORK.exists():
    shutil.rmtree(WORK)
WORK.mkdir(parents=True)
os.environ.update(
    ALINEA_DATABASE_URL=f"sqlite:///{(WORK / 'alinea.db').as_posix()}",
    ALINEA_STORAGE_ROOT=str(WORK / "storage"),
    ALINEA_LLM_API_KEY=os.environ["ALINEA_TEST_KEY"],
    ALINEA_LLM_TIMEOUT_SECONDS="180",
)

from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def wait_job(client: TestClient, job_id: str, headers: dict[str, str]) -> dict:
    for _ in range(240):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        job = response.json()
        if job["status"] == "SUCCEEDED":
            return job
        if job["status"] in {"FAILED", "CANCELLED"}:
            raise AssertionError(json.dumps(job))
        time.sleep(0.5)
    raise TimeoutError(job_id)


def main() -> None:
    with TestClient(create_app()) as client:
        project = client.post("/api/v1/projects", json={"name": "guideline-smoke"})
        assert project.status_code == 201, project.text
        project_id = project.json()["project_id"]
        headers = {"Authorization": f"Bearer {project.json()['token']}"}
        pdf = (ROOT / "examples" / "guideline.pdf").read_bytes()
        response = client.post(
            f"/api/v1/projects/{project_id}/guidelines",
            headers=headers,
            files={"file": ("guideline.pdf", pdf, "application/pdf")},
        )
        assert response.status_code == 201, response.text
        pdf_guideline = response.json()["guideline_id"]
        accepted = client.post(
            f"/api/v1/projects/{project_id}/rules/extract",
            headers=headers,
            json={"guideline_id": pdf_guideline},
        )
        assert accepted.status_code == 202, accepted.text
        wait_job(client, accepted.json()["job_id"], headers)
        pdf_rules = client.get(f"/api/v1/projects/{project_id}/rules", headers=headers).json()
        assert pdf_rules["rules"]
        assert any(rule["source"]["page"] is not None and rule["source"]["quote"] for rule in pdf_rules["rules"])

        response = client.post(
            f"/api/v1/projects/{project_id}/guidelines",
            headers=headers,
            json={"kind": "text", "text": "正文中文使用宋体，字号为小四（12 pt），1.5 倍行距。"},
        )
        assert response.status_code == 201, response.text
        text_guideline = response.json()["guideline_id"]
        accepted = client.post(
            f"/api/v1/projects/{project_id}/rules/extract",
            headers=headers,
            json={"guideline_id": text_guideline},
        )
        assert accepted.status_code == 202, accepted.text
        wait_job(client, accepted.json()["job_id"], headers)
        text_rules = client.get(f"/api/v1/projects/{project_id}/rules", headers=headers).json()
        assert text_rules["rules"]
        assert all(rule["source"]["quote"] for rule in text_rules["rules"] if rule["enabled"])
        result = {
            "pdf_rule_count": len(pdf_rules["rules"]),
            "pdf_sources_have_page_and_quote": True,
            "text_rule_count": len(text_rules["rules"]),
            "text_sources_have_quote": True,
        }
        (WORK / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
