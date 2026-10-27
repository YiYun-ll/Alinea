from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import DocumentSnapshot
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuditEvent, Job, Project
from app.storage.local import LocalStorage

_PROJECT_LOCKS: dict[str, Lock] = {}
_PROJECT_LOCKS_GUARD = Lock()
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def request_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def storage() -> LocalStorage:
    return LocalStorage(get_settings().storage_root)


def snapshot_key(project_id: str, revision_id: str) -> str:
    return LocalStorage.build_key(project_id, "snapshots", revision_id, "snapshot.json")


def write_snapshot(project_id: str, snapshot: DocumentSnapshot) -> str:
    key = snapshot_key(project_id, snapshot.revision_id)
    data = canonical_json(snapshot.model_dump(mode="json")).encode("utf-8")
    storage().write(key, data)
    return key


def read_snapshot(project_id: str, revision_id: str) -> DocumentSnapshot:
    try:
        data = storage().read(snapshot_key(project_id, revision_id))
    except FileNotFoundError as exc:
        raise AlineaError(
            "SNAPSHOT_NOT_FOUND",
            "The immutable document snapshot is unavailable",
            status_code=404,
        ) from exc
    return DocumentSnapshot.model_validate_json(data)


def safe_filename(value: str | None, fallback: str) -> str:
    name = Path(value or "").name
    name = "".join(character for character in name if character >= " " and character != "\x7f")
    return (name or fallback)[:255]


@contextmanager
def project_lock(project_id: str) -> Iterator[None]:
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.setdefault(project_id, Lock())
    with lock:
        yield


def require_active(project: Project) -> None:
    if project.status != "ACTIVE":
        raise AlineaError("PROJECT_NOT_ACTIVE", "The project is not active", status_code=409)


def require_ownership(project: Project, resource_project_id: str) -> None:
    if project.id != resource_project_id:
        raise AlineaError(
            "FORBIDDEN",
            "The token does not grant access to this resource",
            status_code=403,
        )


def require_found[T](value: T | None, code: str, message: str) -> T:
    if value is None:
        raise AlineaError(code, message, status_code=404)
    return value


def add_audit(
    db: Session,
    project_id: str,
    event_type: str,
    *,
    job: Job | None = None,
    actor: str = "USER",
    entity_id: str | None = None,
    details: dict[str, object] | None = None,
) -> AuditEvent:
    payload = dict(details or {})
    if entity_id is not None:
        payload.setdefault("entity_id", entity_id)
    event = AuditEvent(
        id=new_id(),
        project_id=project_id,
        job_id=job.id if job else None,
        actor=actor,
        event_type=event_type,
        details_json=payload,
        created_at=utc_now(),
    )
    db.add(event)
    return event


def validated_request_id(value: str | None) -> str:
    if value and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return f"req_{uuid4().hex}"
