import time

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.main import create_app
from app.cli import ingest_local
from app.database import Batch, Job, Receipt, SourceFile, SourceRecord
from app.queue import claim, fail, lock_lease
from app.worker import run_once

NAME = "DEMO_OFFICER01_weekly_2026-W35_2026-08-24_2026-08-30_v01.html"


class FakeTelegram:
    def __init__(self, content):
        self.content = content
        self.sent = []

    def download(self, _):
        return self.content

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


def update(update_id=1, user=10001, chat_type="private", filename=NAME):
    return {
        "update_id": update_id,
        "message": {
            "from": {"id": user},
            "chat": {"id": user, "type": chat_type},
            "document": {"file_id": "test-file", "file_name": filename, "mime_type": "text/html"},
        },
    }


def drain(context, telegram):
    settings, sessions, storage = context
    for _ in range(20):
        if not run_once(sessions, settings, storage, telegram):
            return
    raise AssertionError("Queue did not drain")


def test_webhook_to_collection_and_idempotency(context, sample):
    settings, sessions, _ = context
    client = TestClient(create_app(settings))
    headers = {"X-Telegram-Bot-Api-Secret-Token": "x" * 40}
    assert client.post("/telegram/webhook", json=update()).status_code == 403
    assert client.post("/telegram/webhook", headers=headers, json=update(user=999)).json()[
        "ignored"
    ]
    assert client.post("/telegram/webhook", headers=headers, json=update(chat_type="group")).json()[
        "ignored"
    ]
    response = client.post("/telegram/webhook", headers=headers, json=update()).json()
    assert client.post("/telegram/webhook", headers=headers, json=update()).json()[
        "duplicate_update"
    ]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == 1
    tg = FakeTelegram(sample)
    drain(context, tg)
    with sessions() as session:
        receipt = session.get(Receipt, response["receipt_id"])
        assert receipt.status == "normalized"
        assert receipt.result["period_start"] == "2026-08-24"
        assert session.scalar(select(func.count()).select_from(SourceRecord)) == 2
        assert session.scalar(select(Batch)).state == "NORMALIZED"
    assert len(tg.sent) == 1
    assert client.get("/health/ready").status_code == 200


def test_webhook_rejects_before_download(context):
    settings, sessions, _ = context
    client = TestClient(create_app(settings))
    response = client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "x" * 40},
        json=update(filename="malware.exe"),
    )
    with sessions() as session:
        assert session.get(Receipt, response.json()["receipt_id"]).status == "rejected"
        assert session.scalar(select(Job)).kind == "notify"


def test_versions_duplicates_and_cross_period_reuse(context, sample, tmp_path):
    settings, sessions, _ = context
    tg = FakeTelegram(sample)

    def submit(name, content):
        path = tmp_path / name
        path.write_bytes(content)
        receipt_id = ingest_local(sessions, settings, path, "DEMO", "OFFICER01")
        drain(context, tg)
        with sessions() as session:
            return session.get(Receipt, receipt_id)

    first = submit(NAME, sample)
    assert submit(NAME, sample).status == "duplicate"
    conflicting = submit(NAME, sample + b"<p>Different result</p>")
    assert conflicting.result["issues"] == ["VERSION_CONTENT_CONFLICT"]
    second = submit(NAME.replace("v01", "v02"), sample + b"<p>Additional result</p>")
    assert second.status == "normalized"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Batch)) == 1
        assert session.scalar(select(Batch)).latest_version == 2
        assert session.scalar(select(func.count()).select_from(SourceFile)) == 2
        assert session.get(Receipt, first.id).source_file_id == first.source_file_id
    # A generic document reused in another period must not become a new achievement.
    generic = b"<html><p>Unchanged source text</p></html>"
    assert submit(NAME.replace("v01", "v03"), generic).status == "normalized"
    reused = submit("DEMO_OFFICER01_weekly_2026-W36_v01.html", generic)
    assert reused.status == "awaiting_confirmation"
    assert "CROSS_PERIOD_CONTENT_REUSE" in reused.result["issues"]


def test_unresolved_period_not_archived(context, sample, tmp_path):
    settings, sessions, _ = context
    path = tmp_path / "DEMO_OFFICER01_weekly_2026-08-31_v01.html"
    path.write_bytes(b"<html><p>No reporting period provided</p></html>")
    receipt_id = ingest_local(sessions, settings, path, "DEMO", "OFFICER01")
    drain(context, FakeTelegram(sample))
    with sessions() as session:
        row = session.get(Receipt, receipt_id)
        assert row.status == "awaiting_confirmation"
        assert row.result["issues"] == ["DATE_MAY_BE_PUBLICATION"]
        assert row.source_file_id is None


def test_queue_lease_recovery_stale_fence_and_failure(context, tmp_path, sample):
    settings, sessions, _ = context
    path = tmp_path / NAME
    path.write_bytes(sample)
    receipt_id = ingest_local(sessions, settings, path, "DEMO", "OFFICER01")
    old = claim(sessions, 300)
    assert claim(sessions, 300) is None
    with sessions.begin() as session:
        session.get(Job, old.id).lease_until = time.time() - 1
    new = claim(sessions, 300)
    assert old.id == new.id and old.token != new.token
    with sessions() as session:
        assert lock_lease(session, old) is None
    fail(sessions, new, "TEST_ERROR")
    with sessions.begin() as session:
        session.get(Job, old.id).available_at = 0
    last = claim(sessions, 300)
    fail(sessions, last, "TEST_ERROR")
    with sessions() as session:
        assert session.get(Job, old.id).state == "failed"
        assert session.get(Receipt, receipt_id).status == "processing_failed"


def test_expired_final_attempt_is_visible(context, tmp_path, sample):
    settings, sessions, _ = context
    path = tmp_path / NAME
    path.write_bytes(sample)
    receipt_id = ingest_local(sessions, settings, path, "DEMO", "OFFICER01")
    lease = claim(sessions, 300)
    with sessions.begin() as session:
        job = session.get(Job, lease.id)
        job.attempts, job.lease_until = 3, 0
    assert claim(sessions, 300) is None
    with sessions() as session:
        assert session.get(Receipt, receipt_id).status == "processing_failed"
