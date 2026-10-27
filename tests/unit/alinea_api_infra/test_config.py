from __future__ import annotations

from app.config import Settings


def test_settings_read_alinea_environment_and_resolve_paths(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    values = {
        "DATABASE_URL": "sqlite:///./db/alinea.db",
        "STORAGE_ROOT": "./private-objects",
        "REDIS_URL": "redis://localhost:6379/1",
        "LOCAL_WORKERS": "3",
        "SOFFICE_PATH": "./tools/soffice.exe",
        "RENDER_TIMEOUT_SECONDS": "50",
        "MAX_FILE_MB": "20",
        "MAX_PAGES": "80",
        "PROJECT_TTL_HOURS": "12",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "not-for-logs",
        "LLM_MODEL": "test-model",
        "LLM_TIMEOUT_SECONDS": "75",
        "WEB_ORIGINS": "https://one.example, https://two.example ,",
    }
    for name, value in values.items():
        monkeypatch.setenv(f"ALINEA_{name}", value)

    settings = Settings(_env_file=None)

    assert settings.database_url == values["DATABASE_URL"]
    assert settings.storage_root == (tmp_path / "private-objects").resolve()
    assert settings.soffice_path == (tmp_path / "tools" / "soffice.exe").resolve()
    assert settings.redis_url == values["REDIS_URL"]
    assert settings.local_workers == 3
    assert settings.render_timeout_seconds == 50
    assert settings.max_file_mb == 20
    assert settings.max_file_bytes == 20 * 1024 * 1024
    assert settings.max_pages == 80
    assert settings.project_ttl_hours == 12
    assert settings.llm_base_url == values["LLM_BASE_URL"]
    assert settings.llm_api_key.get_secret_value() == values["LLM_API_KEY"]
    assert settings.llm_model == "test-model"
    assert settings.llm_timeout_seconds == 75
    assert settings.web_origins == ["https://one.example", "https://two.example"]
    assert values["LLM_API_KEY"] not in repr(settings)
    assert "**********" in repr(settings)


def test_blank_optional_executable_path_is_none(monkeypatch):
    monkeypatch.setenv("ALINEA_SOFFICE_PATH", "")
    assert Settings(_env_file=None).soffice_path is None
