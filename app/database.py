import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    delivery_key: Mapped[str] = mapped_column(String(150), unique=True)
    company_code: Mapped[str] = mapped_column(String(64), index=True)
    officer_code: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    file_id: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    declared_size: Mapped[int | None] = mapped_column(Integer)
    object_key: Mapped[str | None] = mapped_column(String(200))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="received")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    source_file_id: Mapped[str | None] = mapped_column(ForeignKey("source_files.id"))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Batch(Base):
    __tablename__ = "evaluation_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    logical_key: Mapped[str] = mapped_column(String(64), unique=True)
    company_code: Mapped[str] = mapped_column(String(64))
    officer_code: Mapped[str] = mapped_column(String(64))
    document_type: Mapped[str] = mapped_column(String(40))
    period_start: Mapped[str] = mapped_column(String(10))
    period_end: Mapped[str] = mapped_column(String(10))
    state: Mapped[str] = mapped_column(String(40), default="CREATED")
    latest_version: Mapped[int] = mapped_column(Integer, default=0)


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("batch_id", "version", name="uq_batch_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("evaluation_batches.id"))
    version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(200))
    receipt_id: Mapped[str] = mapped_column(String(36))


class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (UniqueConstraint("receipt_id", "locator", name="uq_receipt_locator"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    receipt_id: Mapped[str] = mapped_column(ForeignKey("receipts.id"), index=True)
    locator: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    # These are unverified source fragments, NOT confirmed contributions or facts.


class Job(Base):
    __tablename__ = "agent_jobs"
    __table_args__ = (Index("ix_job_claim", "state", "available_at", "lease_until"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[float] = mapped_column(Float, default=time.time)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    error_code: Mapped[str | None] = mapped_column(String(64))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    receipt_id: Mapped[str] = mapped_column(ForeignKey("receipts.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AcceptanceCase(Base):
    __tablename__ = "acceptance_cases"
    __table_args__ = (UniqueConstraint("case_key", "revision", name="uq_case_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_key: Mapped[str] = mapped_column(String(80), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    agent: Mapped[str] = mapped_column(String(40), index=True)
    track: Mapped[str] = mapped_column(String(40))
    source_family: Mapped[str] = mapped_column(String(100), index=True)
    split: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(255))
    visibility: Mapped[str] = mapped_column(String(20))
    task: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class GoldAnswer(Base):
    __tablename__ = "acceptance_answers"
    __table_args__ = (UniqueConstraint("case_id", "version", name="uq_answer_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("acceptance_cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    answer: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AcceptanceRun(Base):
    __tablename__ = "acceptance_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    request_key: Mapped[str] = mapped_column(String(100), unique=True)
    agent: Mapped[str] = mapped_column(String(40), index=True)
    mode: Mapped[str] = mapped_column(String(20))
    split: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20), default="queued")
    manifest: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    finished_at: Mapped[float | None] = mapped_column(Float)


class AcceptanceResult(Base):
    __tablename__ = "acceptance_results"
    __table_args__ = (UniqueConstraint("run_id", "case_id", name="uq_run_case"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("acceptance_runs.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("acceptance_cases.id"))
    snapshot: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    actual: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    finished_at: Mapped[float | None] = mapped_column(Float)


class AcceptanceAudit(Base):
    __tablename__ = "acceptance_audits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(50), index=True)
    target_id: Mapped[str] = mapped_column(String(100), index=True)
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AcceptanceSession(Base):
    __tablename__ = "acceptance_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf: Mapped[str] = mapped_column(String(80))
    expires_at: Mapped[float] = mapped_column(Float)


class Adjudication(Base):
    __tablename__ = "acceptance_adjudications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    result_id: Mapped[str] = mapped_column(ForeignKey("acceptance_results.id"), index=True)
    actor: Mapped[str] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AcceptanceArtifact(Base):
    __tablename__ = "acceptance_artifacts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    media_type: Mapped[str] = mapped_column(String(80))


def create_database(url: str):
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_setup(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")

    return engine, sessionmaker(engine, expire_on_commit=False)
