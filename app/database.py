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
