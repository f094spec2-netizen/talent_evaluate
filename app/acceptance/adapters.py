"""Adapters receive task/evidence ONLY. No answer, score, rubric or case metadata."""

import base64
import tempfile
from pathlib import Path

from sqlalchemy import func, select

from app.agents.collection import collect
from app.config import Settings
from app.database import Base, Batch, Job, Receipt, SourceFile, SourceRecord, create_database
from app.parsers import InvalidFile, preflight
from app.queue import claim, enqueue
from app.storage import Storage
from app.worker import run_once


def file_bytes(file):
    return base64.b64decode(file["content_base64"], validate=True)


def collection(task):
    file = task["files"][0]
    content = file_bytes(file)
    try:
        preflight(file["filename"], len(content), file.get("mime"), 20_000_000)
        result = collect(file["filename"], content)
        return {
            "disposition": "human" if result.summary["issues"] else "automatic",
            "summary": result.summary,
            "records": result.records,
        }
    except InvalidFile as exc:
        return {
            "disposition": "human",
            "summary": {"issues": [str(exc)], "recommended_route": "red"},
            "records": [],
        }


class FixtureTransport:
    """Only Telegram transport is replaced. Downloads/queue/parser/supervisor are real."""

    def __init__(self, files, failures):
        self.files, self.failures = files, failures.copy()

    def download(self, file_id):
        if self.failures.get(file_id, 0):
            self.failures[file_id] -= 1
            raise ConnectionError("INJECTED_TRANSPORT_FAILURE")
        return file_bytes(self.files[int(file_id)])

    def send(self, chat_id, message):
        raise AssertionError("No external notifications are authorized in acceptance")


def supervisor(task):
    # A fresh database AND object namespace per case/retry. Never touch production intake.
    with tempfile.TemporaryDirectory(prefix="talent-acceptance-") as directory:
        root = Path(directory)
        settings = Settings(
            _env_file=None,
            app_env="test",
            service_mode="intake",
            database_url=f"sqlite:///{(root / 'intake.db').as_posix()}",
            storage_backend="local",
            local_storage_path=root / "objects",
        )
        engine, sessions = create_database(settings.database_url)
        Base.metadata.create_all(engine)
        transport = FixtureTransport(task["files"], task.get("transport_failures", {}))
        storage = Storage(settings)
        try:
            for delivery in task["deliveries"]:
                with sessions.begin() as session:
                    existing = session.scalar(
                        select(Receipt).where(Receipt.delivery_key == delivery["key"])
                    )
                    if not existing:
                        file = task["files"][delivery["file"]]
                        receipt = Receipt(
                            delivery_key=delivery["key"],
                            company_code=task["company_code"],
                            officer_code=task["officer_code"],
                            filename=file["filename"],
                            mime_type=file.get("mime"),
                            file_id=str(delivery["file"]),
                        )
                        session.add(receipt)
                        session.flush()
                        enqueue(
                            session,
                            f"download:{receipt.id}",
                            "download",
                            {"receipt_id": receipt.id},
                        )
                if task.get("crash_final_attempt"):
                    lease = claim(sessions, 60, ("download",))
                    if lease:
                        with sessions.begin() as session:
                            job = session.get(Job, lease.id)
                            job.attempts, job.lease_until = 3, 0
                for _ in range(32):
                    # Controlled retry clock; business handlers and lease/failure logic are unchanged.
                    with sessions.begin() as session:
                        for job in session.scalars(select(Job).where(Job.state == "queued")):
                            job.available_at = 0
                    if not run_once(sessions, settings, storage, transport):
                        break
                else:
                    raise RuntimeError("FIXTURE_DID_NOT_QUIESCE")
            if task.get("replay_collection"):
                with sessions.begin() as session:
                    for receipt in session.scalars(select(Receipt)):
                        enqueue(
                            session, f"replay:{receipt.id}", "collect", {"receipt_id": receipt.id}
                        )
                while run_once(sessions, settings, storage, transport):
                    pass
            with sessions() as session:
                receipts = session.scalars(
                    select(Receipt).order_by(Receipt.created_at, Receipt.id)
                ).all()
                batches = session.scalars(select(Batch)).all()
                jobs = session.scalars(select(Job).order_by(Job.id)).all()
                records = []
                for index, receipt in enumerate(receipts):
                    for row in session.scalars(
                        select(SourceRecord).where(SourceRecord.receipt_id == receipt.id)
                    ):
                        records.append(
                            {"locator": f"receipt:{index}/{row.locator}", "text": row.text}
                        )
                statuses = [r.status for r in receipts]
                return {
                    "disposition": "automatic"
                    if all(s in ("normalized", "duplicate") for s in statuses)
                    else "human",
                    "statuses": statuses,
                    "issues": [r.result.get("issues", []) for r in receipts],
                    "source_count": session.scalar(select(func.count()).select_from(SourceFile)),
                    "receipt_count": len(receipts),
                    "batch_count": len(batches),
                    "batch_states": sorted(b.state for b in batches),
                    "latest_versions": sorted(b.latest_version for b in batches),
                    "failed_jobs": sum(j.state == "failed" for j in jobs),
                    "max_attempts": max((j.attempts for j in jobs), default=0),
                    "records": records,
                    "transport": "fixture; not live Telegram/S3",
                    "scope": "intake_only",
                }
        finally:
            engine.dispose()


ADAPTERS = {"collection": collection, "supervisor": supervisor}


def execute(agent, task):
    if agent not in ADAPTERS:
        raise ValueError("AGENT_NOT_IMPLEMENTED")
    if set(task) - {
        "files",
        "company_code",
        "officer_code",
        "deliveries",
        "transport_failures",
        "crash_final_attempt",
        "replay_collection",
    }:
        raise ValueError("UNEXPECTED_AGENT_INPUT")
    return ADAPTERS[agent](task)
