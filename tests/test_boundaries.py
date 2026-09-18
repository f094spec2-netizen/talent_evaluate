import io

import httpx
import pytest
from botocore.stub import Stubber
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.main import create_app
from app.config import Settings
from app.parsers import InvalidFile
from app.storage import Storage
from app.telegram import Telegram, TelegramError


def test_webhook_is_disabled_without_secret(context):
    settings, _, _ = context
    settings = settings.model_copy(
        update={"telegram_webhook_secret": Settings(_env_file=None).telegram_webhook_secret}
    )
    assert TestClient(create_app(settings)).post("/telegram/webhook", json={}).status_code == 503


def test_webhook_body_limit(context):
    settings, _, _ = context
    response = TestClient(create_app(settings)).post(
        "/telegram/webhook",
        content=b"0" * 256001,
        headers={"X-Telegram-Bot-Api-Secret-Token": "x" * 40},
    )
    assert response.status_code == 413


def test_production_requires_real_runtime_configuration():
    with pytest.raises(ValidationError, match="Production requires"):
        Settings(_env_file=None, app_env="production", database_url="sqlite:///:memory:")


def test_streamed_download_enforces_actual_size(context):
    settings, _, _ = context
    settings = settings.model_copy(update={"max_upload_bytes": 5})

    def response(request):
        if request.method == "POST":
            return httpx.Response(
                200, json={"ok": True, "result": {"file_path": "documents/file.html"}}
            )
        return httpx.Response(200, content=b"sixsix")

    telegram = Telegram(settings, httpx.Client(transport=httpx.MockTransport(response)))
    with pytest.raises(InvalidFile, match="EMPTY_OR_OVERSIZED_FILE"):
        telegram.download("test-file")
    telegram.close()


def test_token_is_not_in_exception(context):
    settings, _, _ = context
    telegram = Telegram(
        settings, httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    )
    with pytest.raises(TelegramError) as caught:
        telegram.download("test-file")
    assert "test-token" not in str(caught.value)
    assert "api.telegram.org" not in str(caught.value)
    telegram.close()


def test_local_storage_is_company_scoped_and_traversal_rejected(context):
    _, _, storage = context
    key_a, digest_a = storage.put("COMPANY_A", b"synthetic")
    key_b, digest_b = storage.put("COMPANY_B", b"synthetic")
    assert key_a != key_b and digest_a == digest_b
    assert storage.get(key_a) == b"synthetic"
    with pytest.raises(ValueError, match="Invalid storage key"):
        storage.get("../../secret")


def test_s3_store_and_read_contract(context):
    settings, _, _ = context
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=settings.database_url,
        storage_backend="s3",
        s3_endpoint_url="https://storage.example.invalid",
        s3_bucket_name="test-bucket",
        s3_access_key_id="synthetic",
        s3_secret_access_key="synthetic",
    )
    storage = Storage(settings)
    # Stub the official SDK; no network or real bucket is used.
    with Stubber(storage.client) as stub:
        stub.add_response("put_object", {}, None)
        key, digest = storage.put("DEMO", b"sample")
        stub.add_response(
            "get_object", {"Body": io.BytesIO(b"sample")}, {"Bucket": "test-bucket", "Key": key}
        )
        assert storage.get(key) == b"sample"
        assert key.endswith(digest)
