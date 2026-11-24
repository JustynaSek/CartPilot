"""Settings parsing (env vars only, `.env` file disabled)."""

import pytest

from src.core.config import Settings


def _settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]


def test_database_url_is_built_from_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARTPILOT_DATABASE_URL", raising=False)
    s = _settings(postgres_user="u", postgres_password="p", postgres_host="h", postgres_port="1")
    assert s.database_url == "postgresql+asyncpg://u:p@h:1/cartpilot"


def test_database_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARTPILOT_DATABASE_URL", "postgresql+asyncpg://x:y@z:5/db")
    assert _settings().database_url == "postgresql+asyncpg://x:y@z:5/db"


def test_admin_ids_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", "123, 456,")
    assert _settings().admin_telegram_ids == [123, 456]


def test_secrets_are_masked_in_repr() -> None:
    s = _settings(postgres_password="super-secret")
    assert "super-secret" not in repr(s)
