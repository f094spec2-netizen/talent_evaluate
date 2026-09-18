import time
from dataclasses import dataclass

from sqlalchemy import and_, or_, select, update

from app.database import AuditEvent, Job, Receipt, uid

MAX_ATTEMPTS = 3


def terminal_failure(session, job, code):
    job.state, job.error_code, job.lease_token = "failed", code, None
    receipt_id = job.payload.get("receipt_id")
    if receipt_id:
        receipt = session.get(Receipt, receipt_id)
        if receipt and job.kind != "notify":
            receipt.status = "processing_failed"
            receipt.result = {"issues": [code], "recommended_route": "red"}
        if receipt:
            session.add(
                AuditEvent(
                    receipt_id=receipt_id,
                    action="job_failed",
                    details={"job_id": job.id, "kind": job.kind, "code": code},
                )
            )


def enqueue(session, key: str, kind: str, payload: dict):
    existing = session.scalar(select(Job).where(Job.idempotency_key == key))
    if existing:
        return existing
    job = Job(idempotency_key=key, kind=kind, payload=payload)
    session.add(job)
    session.flush()
    return job


@dataclass(frozen=True)
class Lease:
    id: str
    token: str
    kind: str
    payload: dict


def claim(sessions, lease_seconds: int) -> Lease | None:
    now = time.time()
    eligible = or_(
        and_(Job.state == "queued", Job.available_at <= now),
        and_(Job.state == "running", Job.lease_until <= now),
    )
    with sessions.begin() as session:
        # A crashed final attempt must become visible as a failed job.
        exhausted = session.scalars(
            select(Job)
            .where(eligible, Job.attempts >= MAX_ATTEMPTS)
            .with_for_update(skip_locked=True)
        ).all()
        for job in exhausted:
            terminal_failure(session, job, "LEASE_EXHAUSTED")
        session.flush()
        job = session.scalar(
            select(Job)
            .where(eligible, Job.attempts < MAX_ATTEMPTS)
            .order_by(Job.available_at, Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        token = uid()
        result = session.execute(
            update(Job)
            .where(
                Job.id == job.id,
                eligible,
                Job.attempts == job.attempts,
            )
            .values(
                state="running",
                attempts=Job.attempts + 1,
                lease_until=now + lease_seconds,
                lease_token=token,
            )
        )
        if result.rowcount != 1:
            return None
        return Lease(job.id, token, job.kind, job.payload)


def lock_lease(session, lease: Lease) -> Job | None:
    return session.scalar(
        select(Job)
        .where(
            Job.id == lease.id,
            Job.state == "running",
            Job.lease_token == lease.token,
            Job.lease_until > time.time(),
        )
        .with_for_update()
    )


def fail(sessions, lease: Lease, error_code: str):
    with sessions.begin() as session:
        job = lock_lease(session, lease)
        if job is None:
            return
        if job.attempts >= MAX_ATTEMPTS:
            terminal_failure(session, job, error_code)
        else:
            job.state, job.error_code = "queued", error_code
        job.available_at = time.time() + 2**job.attempts
        job.lease_token = None
