import pytest

from app.config import Settings
from app.database import Base, create_database
from app.storage import Storage


@pytest.fixture
def context(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        local_storage_path=tmp_path / "objects",
        storage_backend="local",
        telegram_bot_token="test-token",
        telegram_webhook_secret="x" * 40,
        telegram_accounts={"10001": {"company_code": "DEMO", "officer_code": "OFFICER01"}},
    )
    engine, sessions = create_database(settings.database_url)
    Base.metadata.create_all(engine)
    yield settings, sessions, Storage(settings)
    engine.dispose()


@pytest.fixture
def sample():
    return b"<html><body><p>Reporting period: 2026-08-24 to 2026-08-30</p><p>Example task</p></body></html>"
