from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.config import get_settings
from app.db.models import Project
from app.services.common import storage, utc_now
from app.services.maintenance import cleanup_expired_projects
from app.services.projects import create_project
from app.storage.local import LocalStorage


def test_expired_projects_and_files_are_removed(database, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ALINEA_STORAGE_ROOT", str(tmp_path / "objects"))
    get_settings.cache_clear()
    with database.session_scope() as db:
        expired, _ = create_project(db, "expired")
        expired.expires_at = utc_now() - timedelta(hours=1)
        current, _ = create_project(db, "current")
        current.expires_at = utc_now() + timedelta(hours=1)
        key = LocalStorage.build_key(expired.id, "originals", uuid4(), "source.docx")
        storage().write(key, b"docx")
        expired_id = expired.id
        current_id = current.id
    assert cleanup_expired_projects() == 1
    with database.session_scope() as db:
        assert db.get(Project, expired_id) is None
        assert db.get(Project, current_id) is not None
    assert not storage().path_for(key).exists()
    assert cleanup_expired_projects() == 0
