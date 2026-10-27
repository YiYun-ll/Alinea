from __future__ import annotations

import pytest
from app.db import database as database_module


@pytest.fixture
def database(tmp_path):
    previous_url = str(database_module.engine.url)
    database_path = tmp_path / "nested" / "alinea-test.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    database_module.init_db(database_url)
    yield database_module
    database_module.configure_database(previous_url)
