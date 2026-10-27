from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth import get_project_auth
from app.db.database import get_db
from app.db.models import Project

Database = Annotated[Session, Depends(get_db)]
ProjectAuth = Annotated[Project, Depends(get_project_auth)]
