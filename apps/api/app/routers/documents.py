from __future__ import annotations

from typing import Annotated

from alinea_contracts.errors import AlineaError
from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.auth import get_project_auth
from app.config import get_settings
from app.db.database import get_db
from app.db.models import Project
from app.services.common import require_active, safe_filename
from app.services.documents import create_document_revision, enforce_upload_rate, upload_out

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])
_DOCX_MIME = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
    "application/zip",
    "",
}


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    project: Annotated[Project, Depends(get_project_auth)],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> dict[str, object]:
    require_active(project)
    filename = safe_filename(file.filename, "document.docx")
    if (
        not filename.lower().endswith(".docx")
        or (file.content_type or "").lower() not in _DOCX_MIME
    ):
        raise AlineaError(
            "UNSUPPORTED_FILE_FORMAT",
            "Only an unencrypted .docx WordprocessingML document is supported",
            status_code=415,
        )
    enforce_upload_rate(project.id)
    maximum = get_settings().max_file_bytes
    data = await file.read(maximum + 1)
    if len(data) > maximum:
        raise AlineaError(
            "FILE_TOO_LARGE",
            "The DOCX exceeds the configured compressed-file size limit",
            status_code=413,
            details={"max_bytes": maximum},
        )
    revision = create_document_revision(db, project, data, filename)
    db.commit()
    return upload_out(revision)
