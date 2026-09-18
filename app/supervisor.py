import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import AuditEvent, Batch, Receipt, SourceFile, SourceRecord
from app.queue import enqueue


def notify_result(session, receipt):
    if receipt.chat_id is not None:
        enqueue(session, f"notify:{receipt.id}", "notify", {"receipt_id": receipt.id})


def reject(session, receipt, code):
    receipt.status = "rejected"
    receipt.result = {"issues": [code], "recommended_route": "red"}
    session.add(AuditEvent(receipt_id=receipt.id, action="file_rejected", details={"code": code}))
    notify_result(session, receipt)


def finalize_collection(session, receipt: Receipt, result):
    if receipt.status not in ("received", "queued"):
        return
    if not receipt.filename.startswith(f"{receipt.company_code}_{receipt.officer_code}_"):
        result.summary["issues"].append("FILENAME_IDENTITY_UNCONFIRMED")
        result.summary["recommended_route"] = "yellow"
    receipt.result = dict(result.summary)
    for row in result.records:
        session.add(SourceRecord(receipt_id=receipt.id, **row))
    if result.summary["issues"]:
        receipt.status = "awaiting_confirmation"
    else:
        s = result.summary
        # A batch is one company/officer/type/reporting period, not one uploaded file.
        key_fields = [
            receipt.company_code,
            receipt.officer_code,
            s["document_type"],
            s["period_start"],
            s["period_end"],
        ]
        logical_key = hashlib.sha256(json.dumps(key_fields).encode()).hexdigest()
        batch = session.scalar(
            select(Batch).where(Batch.logical_key == logical_key).with_for_update()
        )
        if batch is None:
            try:
                with session.begin_nested():
                    batch = Batch(
                        logical_key=logical_key,
                        company_code=receipt.company_code,
                        officer_code=receipt.officer_code,
                        document_type=s["document_type"],
                        period_start=s["period_start"],
                        period_end=s["period_end"],
                    )
                    session.add(batch)
                    session.flush()
            except IntegrityError:
                batch = session.scalar(
                    select(Batch).where(Batch.logical_key == logical_key).with_for_update()
                )
        existing = session.scalar(
            select(SourceFile).where(
                SourceFile.batch_id == batch.id,
                SourceFile.version == s["version"],
            )
        )
        if existing:
            if existing.sha256 == receipt.sha256:
                receipt.status = "duplicate"
                receipt.source_file_id = existing.id
            else:
                receipt.status = "awaiting_confirmation"
                receipt.result = {
                    **s,
                    "issues": ["VERSION_CONTENT_CONFLICT"],
                    "recommended_route": "yellow",
                }
        else:
            reused = session.scalar(
                select(SourceFile)
                .join(Batch)
                .where(
                    Batch.company_code == receipt.company_code,
                    Batch.logical_key != logical_key,
                    SourceFile.sha256 == receipt.sha256,
                )
                .limit(1)
            )
            if reused:
                receipt.status = "awaiting_confirmation"
                receipt.result = {
                    **s,
                    "issues": ["CROSS_PERIOD_CONTENT_REUSE"],
                    "recommended_route": "yellow",
                }
            else:
                source = SourceFile(
                    batch_id=batch.id,
                    version=s["version"],
                    sha256=receipt.sha256,
                    object_key=receipt.object_key,
                    receipt_id=receipt.id,
                )
                session.add(source)
                session.flush()
                receipt.source_file_id = source.id
                receipt.status = "normalized"
                batch.latest_version = max(batch.latest_version, s["version"])
                batch.state = "NORMALIZED"
                # Stop at source normalization: identity, contributions, and grades are not implemented.
        receipt.result = {**receipt.result, "batch_id": batch.id}
    session.add(
        AuditEvent(
            receipt_id=receipt.id,
            action="collection_completed",
            details={
                "status": receipt.status,
                "rule_version": receipt.result["rule_version"],
                "issues": receipt.result["issues"],
            },
        )
    )
    notify_result(session, receipt)
