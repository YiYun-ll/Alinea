from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select

from app.config import Settings, get_settings
from app.db.database import session_scope
from app.db.models import Project

from .common import project_lock, utc_now
from .projects import delete_project


def cleanup_expired_projects(now: datetime | None = None) -> int:
    cutoff = now or utc_now()
    deleted = 0
    with session_scope() as db:
        expired_ids = list(
            db.scalars(select(Project.id).where(Project.expires_at <= cutoff)).all()
        )
    for project_id in expired_ids:
        with project_lock(project_id), session_scope() as db:
            project = db.get(Project, project_id)
            if project is not None:
                delete_project(db, project)
                deleted += 1
    return deleted


async def _maintenance_loop(settings: Settings) -> None:
    while True:
        await asyncio.to_thread(cleanup_expired_projects)
        await asyncio.sleep(900)


def start_maintenance(settings: Settings | None = None) -> asyncio.Task[None]:
    settings = settings or get_settings()
    return asyncio.create_task(_maintenance_loop(settings))
