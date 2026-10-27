from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".data" / "e2e"
WORK.mkdir(parents=True, exist_ok=True)
for database_file in WORK.glob("alinea.db*"):
    database_file.unlink()
for derived in (WORK / "storage" / "projects", WORK / "storage" / "_renders"):
    if derived.exists():
        shutil.rmtree(derived)
os.environ.update(
    ALINEA_DATABASE_URL=f"sqlite:///{(WORK / 'alinea.db').as_posix()}",
    ALINEA_STORAGE_ROOT=str(WORK / "storage"),
    ALINEA_LOCAL_WORKERS="2",
    ALINEA_SOFFICE_PATH=str(ROOT / ".tools" / "LibreOffice" / "program" / "soffice.com"),
    ALINEA_RENDER_TIMEOUT_SECONDS="120",
    ALINEA_LLM_API_KEY="",
)

from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from lxml import etree  # noqa: E402


def required(response, expected: int | set[int] = 200):
    if isinstance(expected, int):
        expected = {expected}
    if response.status_code not in expected:
        message = response.text[:2000]
        try:
            payload = response.json()
            if isinstance(payload, dict) and "token" in payload:
                payload["token"] = None
                message = json.dumps(payload)
        except ValueError:
            pass
        raise AssertionError(
            f"{response.request.method} {response.request.url}: "
            f"{response.status_code} {message}"
        )
    return response


def wait_job(
    client: TestClient,
    job_id: str,
    headers: dict[str, str],
    timeout: int = 240,
    expected_status: str = "SUCCEEDED",
):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        job = required(client.get(f"/api/v1/jobs/{job_id}", headers=headers)).json()
        if job["status"] == expected_status:
            return job
        if job["status"] in {"FAILED", "CANCELLED", "SUCCEEDED"}:
            raise AssertionError(f"Unexpected job outcome: {json.dumps(job, ensure_ascii=True)}")
        time.sleep(0.5)
    raise TimeoutError(f"Job {job_id} did not finish in {timeout}s")


def text_and_media(data: bytes):
    texts = {}
    media = {}
    with zipfile.ZipFile(BytesIO(data)) as package:
        for name in package.namelist():
            if name.startswith("word/media/"):
                media[name] = hashlib.sha256(package.read(name)).hexdigest()
            if name.endswith(".xml"):
                root = etree.fromstring(package.read(name))
                values = [
                    element.text or ""
                    for element in root.iter()
                    if isinstance(element.tag, str)
                    and etree.QName(element).localname in {"t", "instrText", "delText"}
                ]
                if values:
                    texts[name] = values
    return texts, media


def main() -> None:
    started = time.monotonic()
    with TestClient(create_app()) as client:
        required(client.get("/health"))
        created = required(client.post("/api/v1/demo", json={}), 201).json()
        project_id = created["project_id"]
        original_revision_id = created["revision_id"]
        headers = {"Authorization": f"Bearer {created['token']}"}
        other_project = required(
            client.post("/api/v1/projects", json={"name": "other"}), 201
        ).json()
        other_headers = {"Authorization": f"Bearer {other_project['token']}"}
        required(client.get(f"/api/v1/projects/{project_id}", headers=other_headers), 403)
        rules = required(client.get(f"/api/v1/projects/{project_id}/rules", headers=headers)).json()
        required(
            client.post(
                f"/api/v1/projects/{project_id}/inspections",
                headers={**headers, "Idempotency-Key": "unapproved-rules"},
                json={
                    "revision_id": original_revision_id,
                    "rule_set_id": rules["rule_set_id"],
                    "rule_set_version": rules["version"],
                    "include_page_mapping": False,
                },
            ),
            409,
        )
        rules = required(
            client.put(f"/api/v1/projects/{project_id}/rules/{rules['rule_set_id']}/approve", headers=headers)
        ).json()
        inspection_request = {
            "revision_id": original_revision_id,
            "rule_set_id": rules["rule_set_id"],
            "rule_set_version": rules["version"],
            "include_page_mapping": True,
        }
        accepted = required(
            client.post(
                f"/api/v1/projects/{project_id}/inspections",
                headers={**headers, "Idempotency-Key": "inspect-demo-v1"},
                json=inspection_request,
            ),
            202,
        ).json()
        assert accepted["reused"] is False
        initial_job = wait_job(client, accepted["job_id"], headers)
        inspection = required(
            client.get(f"/api/v1/inspections/{accepted['inspection_id']}", headers=headers)
        ).json()
        repeated = required(
            client.post(
                f"/api/v1/projects/{project_id}/inspections",
                headers={**headers, "Idempotency-Key": "inspect-demo-v2"},
                json=inspection_request,
            ),
            202,
        ).json()
        assert repeated["reused"] is True
        assert repeated["inspection_id"] == accepted["inspection_id"]
        assert repeated["job_id"] == accepted["job_id"]
        assert required(client.get(f"/api/v1/jobs/{accepted['job_id']}", headers=headers)).json() == initial_job
        assert required(
            client.get(f"/api/v1/inspections/{accepted['inspection_id']}", headers=headers)
        ).json() == inspection
        inspection_jobs = required(
            client.get(f"/api/v1/projects/{project_id}/jobs", headers=headers)
        ).json()["data"]
        assert sum(
            item["job_type"] == "inspection"
            and item["inspection_id"] == accepted["inspection_id"]
            for item in inspection_jobs
        ) == 1
        original_preview = required(
            client.get(f"/api/v1/revisions/{original_revision_id}/preview", headers=headers)
        ).content
        assert original_preview.startswith(b"%PDF-")
        issues = inspection["issues"]
        safe = [
            issue
            for issue in issues
            if issue["detection_status"] == "CONFIRMED_VIOLATION"
            and issue["repair"]["eligibility"] == "SAFE_SINGLE_TARGET"
        ]
        assert len(safe) >= 2
        selected = [issue["issue_id"] for issue in safe[:2]]
        plan = required(
            client.post(
                f"/api/v1/projects/{project_id}/repair-plans",
                headers=headers,
                json={
                    "base_revision_id": original_revision_id,
                    "inspection_id": inspection["inspection_id"],
                    "selected_issue_ids": selected,
                },
            ),
            201,
        ).json()
        required(
            client.post(
                f"/api/v1/repair-plans/{plan['plan_id']}/execute",
                headers={**headers, "Idempotency-Key": "unapproved-repair"},
            ),
            409,
        )
        plan = required(
            client.post(
                f"/api/v1/repair-plans/{plan['plan_id']}/approve",
                headers=headers,
                json={"plan_digest": plan["plan_digest"]},
            )
        ).json()
        from unittest.mock import patch

        from alinea_contracts import AlineaError

        with patch(
            "app.services.repairs.apply_approved_patch",
            side_effect=AlineaError(
                "TEMPORARY_REPAIR_FAILURE", "Injected transient failure", status_code=503, retryable=True
            ),
        ):
            execution = required(
                client.post(
                    f"/api/v1/repair-plans/{plan['plan_id']}/execute",
                    headers={**headers, "Idempotency-Key": "repair-demo-client"},
                ),
                202,
            ).json()
            failed = wait_job(client, execution["job_id"], headers, expected_status="FAILED")
        assert failed["retryable"] is True
        retried = required(
            client.post(f"/api/v1/jobs/{execution['job_id']}/retry", headers=headers), 202
        ).json()
        assert retried["job_id"] != execution["job_id"]
        assert retried["retry_of"] == execution["job_id"]
        retried_job = wait_job(client, retried["job_id"], headers)
        completed_plan = required(
            client.get(f"/api/v1/repair-plans/{plan['plan_id']}", headers=headers)
        ).json()
        revision_id = completed_plan["result_revision_id"]
        assert revision_id
        report = required(client.get(f"/api/v1/revisions/{revision_id}/report", headers=headers)).json()
        after = required(client.get(f"/api/v1/inspections/{report['inspection_id']}", headers=headers)).json()
        published_before = required(
            client.get(f"/api/v1/projects/{project_id}/revisions", headers=headers)
        ).json()["data"]
        duplicate = required(
            client.post(f"/api/v1/jobs/{execution['job_id']}/retry", headers=headers), 202
        ).json()
        assert duplicate["job_id"] == retried["job_id"]
        assert duplicate["status"] == "SUCCEEDED"
        assert required(client.get(f"/api/v1/jobs/{retried['job_id']}", headers=headers)).json() == retried_job
        assert required(
            client.get(f"/api/v1/repair-plans/{plan['plan_id']}", headers=headers)
        ).json() == completed_plan
        assert required(
            client.get(f"/api/v1/inspections/{accepted['inspection_id']}", headers=headers)
        ).json() == inspection
        assert required(
            client.get(f"/api/v1/inspections/{report['inspection_id']}", headers=headers)
        ).json() == after
        assert required(client.get(f"/api/v1/revisions/{revision_id}/report", headers=headers)).json() == report
        assert required(
            client.get(f"/api/v1/projects/{project_id}/revisions", headers=headers)
        ).json()["data"] == published_before
        assert report["selected_count"] == 2 and report["resolved_count"] == 2, report
        repaired = required(client.get(f"/api/v1/revisions/{revision_id}/download", headers=headers)).content
        original = Path(ROOT / "examples" / "alinea-demo.docx").read_bytes()
        assert text_and_media(original) == text_and_media(repaired)
        (WORK / "repaired.docx").write_bytes(repaired)
        repaired_preview = required(client.get(f"/api/v1/revisions/{revision_id}/preview", headers=headers)).content
        assert repaired_preview.startswith(b"%PDF-")
        markdown = required(
            client.get(f"/api/v1/revisions/{revision_id}/report?format=markdown", headers=headers)
        ).content
        assert b"G1" in markdown and b"G5" in markdown
        before_selected = [issue for issue in issues if issue["issue_id"] in selected]
        for old in before_selected:
            ref = old["element_ref"]
            matches = [
                issue
                for issue in after["issues"]
                if issue["rule_id"] == old["rule_id"]
                and issue["property"] == old["property"]
                and issue["element_ref"]["part_uri"] == ref["part_uri"]
                and issue["element_ref"]["paragraph_ordinal"] == ref["paragraph_ordinal"]
                and issue["element_ref"]["run_range"] == ref["run_range"]
                and issue["detection_status"] == "CONFIRMED_VIOLATION"
            ]
            assert not matches, (old, matches)
        revisions = required(client.get(f"/api/v1/projects/{project_id}/revisions", headers=headers)).json()["data"]
        assert sum(item["kind"] == "PUBLISHED" for item in revisions) == 1
        jobs = required(client.get(f"/api/v1/projects/{project_id}/jobs", headers=headers)).json()["data"]
        assert sum(item["job_type"] == "repair" for item in jobs) == 2
        required(client.delete(f"/api/v1/projects/{project_id}", headers=headers), 204)
        required(client.get(f"/api/v1/revisions/{revision_id}/download", headers=headers), {401, 403, 404})
        result = {
            "initial_violations": inspection["summary"]["violations"],
            "initial_fixable": inspection["summary"]["fixable"],
            "initial_located": inspection["summary"]["located"],
            "selected_repaired": report["resolved_count"],
            "verification": report["status"],
            "gates": {gate["gate"]: gate["status"] for gate in report["gates"]},
            "after_violations": after["summary"]["violations"],
            "after_located": after["summary"]["located"],
            "published_revisions": 1,
            "repair_jobs": 2,
            "retry_recovered": True,
            "text_and_media_identical": True,
            "delete_invalidates_download": True,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        (WORK / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
