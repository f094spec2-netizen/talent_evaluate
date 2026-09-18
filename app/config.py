from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Account(BaseModel):
    company_code: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    officer_code: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: Literal["development", "test", "production"] = "development"
    service_mode: Literal["intake", "acceptance"] = "intake"
    acceptance_admin_password: SecretStr = SecretStr("")
    acceptance_embedded_worker: bool = False
    database_url: str = "sqlite:///./data/private/talent.db"
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: Path = Path("data/private/objects")
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_webhook_secret: SecretStr = SecretStr("")
    telegram_accounts: dict[str, Account] = Field(default_factory=dict)
    max_upload_bytes: int = Field(default=20_000_000, ge=1, le=20_000_000)
    worker_poll_seconds: float = Field(default=2, ge=0.1)
    job_lease_seconds: int = Field(default=300, ge=60)
    s3_endpoint_url: str = ""
    s3_bucket_name: str = ""
    s3_access_key_id: SecretStr = SecretStr("")
    s3_secret_access_key: SecretStr = SecretStr("")
    s3_region: str = "auto"

    @model_validator(mode="after")
    def guard_environment(self):
        # Railway supplies postgresql://; explicitly select the psycopg 3 driver.
        for prefix in ("postgres://", "postgresql://"):
            if self.database_url.startswith(prefix):
                self.database_url = self.database_url.replace(prefix, "postgresql+psycopg://", 1)
        secret = self.telegram_webhook_secret.get_secret_value()
        if secret and (
            len(secret) < 32
            or len(secret) > 256
            or not all(c.isascii() and (c.isalnum() or c in "_-") for c in secret)
        ):
            raise ValueError("Webhook secret must be 32–256 Telegram-compatible characters")
        if self.storage_backend == "s3" and not all(
            (
                self.s3_endpoint_url.startswith("https://"),
                self.s3_bucket_name,
                self.s3_access_key_id.get_secret_value(),
                self.s3_secret_access_key.get_secret_value(),
            )
        ):
            raise ValueError("S3 requires HTTPS endpoint, bucket and credentials")
        if self.app_env == "production":
            if make_url(self.database_url).get_backend_name() != "postgresql":
                raise ValueError("Production requires PostgreSQL")
            if self.storage_backend != "s3":
                raise ValueError("Production requires shared S3 storage")
            if self.service_mode == "intake" and (
                not secret
                or not self.telegram_bot_token.get_secret_value()
                or not self.telegram_accounts
            ):
                raise ValueError("Production requires Telegram credentials and account assignments")
        if self.service_mode == "acceptance":
            if len(self.acceptance_admin_password.get_secret_value()) < 16:
                raise ValueError("Acceptance requires a separate admin password of at least 16 characters")
            if self.app_env == "production" and self.acceptance_embedded_worker:
                raise ValueError("Production acceptance must use a separate queue worker")
        return self
