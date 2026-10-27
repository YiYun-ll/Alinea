from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from alinea_contracts.errors import AlineaError
from alinea_docx import DocxParser, OoxmlPackage, SecurityLimits, read_secure_docx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Project, Revision
from app.storage.local import LocalStorage

from .common import add_audit, isoformat, new_id, safe_filename, utc_now, write_snapshot
from .serializers import revision_out

_UPLOAD_TIMES: dict[str, deque[float]] = defaultdict(deque)
_UPLOAD_LIMIT_GUARD = Lock()


def enforce_upload_rate(project_id: str, *, maximum: int = 12, window_seconds: float = 60) -> None:
    now = time.monotonic()
    with _UPLOAD_LIMIT_GUARD:
        timestamps = _UPLOAD_TIMES[project_id]
        while timestamps and now - timestamps[0] >= window_seconds:
            timestamps.popleft()
        if len(timestamps) >= maximum:
            raise AlineaError(
                "UPLOAD_RATE_LIMITED",
                "Too many document uploads; retry after the upload window resets",
                status_code=429,
                retryable=True,
            )
        timestamps.append(now)


def create_document_revision(
    db: Session,
    project: Project,
    data: bytes,
    filename: str,
) -> Revision:
    settings = get_settings()
    limits = SecurityLimits(max_file_bytes=settings.max_file_bytes)
    revision_id = new_id()
    safe_package = read_secure_docx(data, limits=limits)
    package = OoxmlPackage(safe_package)
    snapshot = DocxParser(limits=limits).parse_package(package, revision_id=revision_id)
    original_name = safe_filename(filename, "document.docx")
    storage_key = LocalStorage.build_key(project.id, "originals", revision_id, "source.docx")
    from .common import storage

    storage().write(storage_key, safe_package.data)
    write_snapshot(project.id, snapshot)
    revision = Revision(
        id=revision_id,
        project_id=project.id,
        parent_revision_id=None,
        original_filename=original_name,
        sha256=safe_package.sha256,
        storage_key=storage_key,
        kind="ORIGINAL",
        validation_status="VALIDATED",
        created_at=utc_now(),
    )
    db.add(revision)
    project.active_revision_id = revision_id
    db.flush()
    add_audit(
        db,
        project.id,
        "document.uploaded",
        entity_id=revision_id,
        details={
            "sha256": revision.sha256,
            "paragraph_count": len(snapshot.paragraphs),
            "section_count": len(snapshot.sections),
        },
    )
    return revision


def upload_out(revision: Revision, paragraph_count: int | None = None) -> dict[str, object]:
    result = revision_out(revision)
    result["status"] = revision.validation_status
    if paragraph_count is not None:
        result["paragraph_count"] = paragraph_count
    result["created_at"] = isoformat(revision.created_at)
    return result
