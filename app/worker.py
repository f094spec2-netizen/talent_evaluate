import argparse
import logging
import time

from sqlalchemy import select

from app.agents.collection import collect
from app.config import Settings
from app.database import AuditEvent, Receipt, create_database
from app.parsers import InvalidFile, preflight
from app.queue import claim, enqueue, fail, lock_lease
from app.storage import Storage
from app.supervisor import finalize_collection, reject
from app.telegram import Telegram, receipt_message

logger = logging.getLogger(__name__)


def run_once(sessions, settings, storage, telegram) -> bool:
    lease = claim(sessions, settings.job_lease_seconds, ("command", "notify", "download", "collect"))
    if lease is None:
        return False
    try:
        if lease.kind == "command":
            command = lease.payload["command"]
            if command == "/status":
                with sessions() as session:
                    rows = session.scalars(
                        select(Receipt)
                        .where(
                            Receipt.user_id == lease.payload["user_id"],
                            Receipt.company_code == lease.payload["company_code"],
                        )
                        .order_by(Receipt.created_at.desc())
                        .limit(5)
                    ).all()
                    message = "\n\n".join(receipt_message(row) for row in rows) or "暂无收件记录。"
            else:
                message = (
                    "请在私聊上传文件。公司与责任人由管理员绑定。\n"
                    "周报示例：DEMO_OFFICER01_周报_2026-W35_2026-08-24_2026-08-30_v01.html\n"
                    "支持 HTML、CSV、JSON、XLSX、XLSM、DOCX，最大 20 MB。\n"
                    "发送 /status 查询最近 5 次收件状态。"
                )
            telegram.send(lease.payload["chat_id"], message)
        else:
            with sessions() as session:
                receipt = session.get(Receipt, lease.payload["receipt_id"])
            if receipt is None:
                raise ValueError("RECEIPT_NOT_FOUND")
            if lease.kind == "notify":
                telegram.send(receipt.chat_id, receipt_message(receipt))
            elif lease.kind == "download":
                if receipt.status == "received":
                    content = telegram.download(receipt.file_id)
                    preflight(
                        receipt.filename, len(content), receipt.mime_type, settings.max_upload_bytes
                    )
                    key, digest = storage.put(receipt.company_code, content)
                    with sessions.begin() as session:
                        if lock_lease(session, lease) is None:
                            return True
                        current = session.get(Receipt, receipt.id, with_for_update=True)
                        if current.status == "received":
                            current.object_key, current.sha256, current.status = (
                                key,
                                digest,
                                "queued",
                            )
                            enqueue(
                                session,
                                f"collect:{receipt.id}",
                                "collect",
                                {"receipt_id": receipt.id},
                            )
                            session.add(
                                AuditEvent(
                                    receipt_id=receipt.id,
                                    action="file_stored",
                                    details={"sha256": digest},
                                )
                            )
            elif lease.kind == "collect":
                if receipt.status in ("received", "queued"):
                    content = storage.get(receipt.object_key)
                    preflight(
                        receipt.filename, len(content), receipt.mime_type, settings.max_upload_bytes
                    )
                    result = collect(receipt.filename, content)
                    with sessions.begin() as session:
                        if lock_lease(session, lease) is None:
                            return True
                        current = session.get(Receipt, receipt.id, with_for_update=True)
                        finalize_collection(session, current, result)
            else:
                raise ValueError("UNKNOWN_JOB_KIND")
        with sessions.begin() as session:
            job = lock_lease(session, lease)
            if job:
                job.state, job.lease_token = "completed", None
    except InvalidFile as exc:
        with sessions.begin() as session:
            job = lock_lease(session, lease)
            if job:
                current = session.get(Receipt, lease.payload["receipt_id"], with_for_update=True)
                reject(session, current, str(exc))
                job.state, job.lease_token = "completed", None
    except Exception as exc:
        # Never log exception text, credentials, filenames, or document contents.
        code = type(exc).__name__[:64]
        fail(sessions, lease, code)
        logger.warning("Job %s failed (%s); retry policy applied", lease.id, code)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = Settings()
    engine, sessions = create_database(settings.database_url)
    storage, telegram = Storage(settings), Telegram(settings)
    try:
        while True:
            worked = run_once(sessions, settings, storage, telegram)
            if args.once:
                break
            if not worked:
                time.sleep(settings.worker_poll_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        telegram.close()
        engine.dispose()


if __name__ == "__main__":
    main()
