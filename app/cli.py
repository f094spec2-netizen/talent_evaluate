import argparse
import json
from pathlib import Path

from sqlalchemy import func, select

from app.config import Account, Settings
from app.database import AuditEvent, Job, Receipt, create_database, uid
from app.parsers import preflight
from app.queue import enqueue
from app.storage import Storage


def ingest_local(sessions, settings, path, company, officer):
    if settings.app_env == "production":
        raise ValueError("Local file ingestion is a development-only helper")
    account = Account(company_code=company, officer_code=officer)
    path = Path(path)
    preflight(path.name, path.stat().st_size, None, settings.max_upload_bytes)
    with path.open("rb") as stream:
        content = stream.read(settings.max_upload_bytes + 1)
    preflight(path.name, len(content), None, settings.max_upload_bytes)
    key, digest = Storage(settings).put(company, content)
    with sessions.begin() as session:
        receipt = Receipt(
            delivery_key=f"local:{uid()}",
            company_code=account.company_code,
            officer_code=account.officer_code,
            filename=path.name,
            status="queued",
            object_key=key,
            sha256=digest,
            declared_size=len(content),
        )
        session.add(receipt)
        session.flush()
        session.add(
            AuditEvent(receipt_id=receipt.id, action="received", details={"channel": "local_cli"})
        )
        enqueue(session, f"collect:{receipt.id}", "collect", {"receipt_id": receipt.id})
        return receipt.id


def main():
    parser = argparse.ArgumentParser(
        description="Trusted operator tools; never expose as public API"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("path")
    ingest.add_argument("--company", required=True)
    ingest.add_argument("--officer", required=True)
    status = sub.add_parser("status")
    status.add_argument("receipt_id")
    sub.add_parser("jobs")
    args = parser.parse_args()
    settings = Settings()
    engine, sessions = create_database(settings.database_url)
    try:
        if args.command == "ingest":
            print(ingest_local(sessions, settings, args.path, args.company, args.officer))
        elif args.command == "status":
            with sessions() as session:
                receipt = session.get(Receipt, args.receipt_id)
                if receipt is None:
                    parser.error("Receipt not found")
                print(
                    json.dumps(
                        {
                            "receipt_id": receipt.id,
                            "status": receipt.status,
                            "result": receipt.result,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
        elif args.command == "jobs":
            with sessions() as session:
                print(
                    json.dumps(
                        dict(
                            session.execute(
                                select(Job.state, func.count()).group_by(Job.state)
                            ).all()
                        )
                    )
                )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
