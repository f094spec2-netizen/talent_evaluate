import json
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.database import AuditEvent, Receipt, create_database
from app.parsers import InvalidFile, preflight
from app.queue import enqueue
from app.supervisor import reject


class Sender(BaseModel):
    id: int
    is_bot: bool = False


class Chat(BaseModel):
    id: int
    type: str


class Document(BaseModel):
    file_id: str = Field(max_length=1024)
    file_name: str = Field(default="", max_length=512)
    file_size: int | None = None
    mime_type: str | None = Field(default=None, max_length=255)


class Message(BaseModel):
    sender: Sender = Field(alias="from")
    chat: Chat
    document: Document | None = None
    text: str = Field(default="", max_length=10000)


class Update(BaseModel):
    update_id: int
    message: Message | None = None


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    engine, sessions = create_database(settings.database_url)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(_):
        yield
        engine.dispose()

    app = FastAPI(
        title="Talent Evaluate Intake",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
    )

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        try:
            with sessions() as session:
                session.execute(text("SELECT 1 FROM agent_jobs LIMIT 1"))
        except Exception:
            raise HTTPException(503, "Database or migrations not ready") from None
        return {"status": "ready"}

    def accept(update: Update):
        message = update.message
        if message is None:
            return {"ok": True, "ignored": True}
        account = settings.telegram_accounts.get(str(message.sender.id))
        if (
            not account
            or message.sender.is_bot
            or message.chat.type != "private"
            or message.chat.id != message.sender.id
        ):
            # Ack unauthorized updates to avoid Telegram retry storms; perform no writes.
            return {"ok": True, "ignored": True}
        delivery_key = f"telegram:{update.update_id}"
        try:
            with sessions.begin() as session:
                if not message.document:
                    command = message.text.split(maxsplit=1)[0] if message.text else ""
                    if command in ("/start", "/help", "/status"):
                        enqueue(
                            session,
                            delivery_key,
                            "command",
                            {
                                "chat_id": message.chat.id,
                                "user_id": message.sender.id,
                                "company_code": account.company_code,
                                "command": command,
                            },
                        )
                    return {"ok": True}
                existing = session.scalar(
                    select(Receipt).where(Receipt.delivery_key == delivery_key)
                )
                if existing:
                    return {"ok": True, "receipt_id": existing.id, "duplicate_update": True}
                doc = message.document
                receipt = Receipt(
                    delivery_key=delivery_key,
                    company_code=account.company_code,
                    officer_code=account.officer_code,
                    user_id=message.sender.id,
                    chat_id=message.chat.id,
                    file_id=doc.file_id,
                    filename=doc.file_name,
                    mime_type=doc.mime_type,
                    declared_size=doc.file_size,
                )
                session.add(receipt)
                session.flush()
                session.add(
                    AuditEvent(
                        receipt_id=receipt.id, action="received", details={"channel": "telegram"}
                    )
                )
                try:
                    preflight(
                        doc.file_name, doc.file_size, doc.mime_type, settings.max_upload_bytes
                    )
                except InvalidFile as exc:
                    reject(session, receipt, str(exc))
                else:
                    enqueue(
                        session, f"download:{receipt.id}", "download", {"receipt_id": receipt.id}
                    )
                return {"ok": True, "receipt_id": receipt.id}
        except IntegrityError:
            # A concurrent delivery of the same update may win the unique-key race.
            with sessions() as session:
                existing = session.scalar(
                    select(Receipt).where(Receipt.delivery_key == delivery_key)
                )
                if existing:
                    return {"ok": True, "receipt_id": existing.id, "duplicate_update": True}
            if not message.document:
                return {"ok": True}
            raise

    @app.post("/telegram/webhook")
    async def webhook(request: Request):
        expected = settings.telegram_webhook_secret.get_secret_value()
        actual = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not expected:
            raise HTTPException(503, "Telegram webhook is not configured")
        if not secrets.compare_digest(actual.encode(), expected.encode()):
            raise HTTPException(403, "Invalid webhook secret")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 256_000:
                raise HTTPException(413, "Webhook body too large")
        try:
            update = Update.model_validate(json.loads(body))
        except (ValueError, ValidationError):
            raise HTTPException(400, "Invalid Telegram update") from None
        return await run_in_threadpool(accept, update)

    return app
