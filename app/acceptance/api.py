import hashlib
import hmac
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.acceptance.contracts import CATALOG
from app.acceptance.service import (
    add_answer,
    adjudicate,
    audit,
    code_version,
    create_run,
    decide_answer,
    latest_answer,
    latest_cases,
    run_view,
)
from app.config import Settings
from app.database import (
    AcceptanceArtifact,
    AcceptanceAudit,
    AcceptanceCase,
    AcceptanceRun,
    AcceptanceSession,
    GoldAnswer,
    Receipt,
    create_database,
)

COOKIE = "talent_acceptance_session"


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Payload):
    password: str = Field(min_length=1, max_length=256)


class Decision(Payload):
    decision: Literal["approve", "return"]
    reason: str = Field(min_length=3, max_length=4000)


class Judgment(Payload):
    decision: Literal["accept", "return"]
    reason: str = Field(min_length=3, max_length=4000)


class NewAnswer(Payload):
    answer: dict


class RunRequest(Payload):
    agent: str
    case_ids: list[str] = Field(default_factory=list, max_length=500)
    split: Literal["all", "development", "holdout"] = "all"
    mode: Literal["trial", "formal"] = "trial"
    request_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


def create_app(settings=None):
    settings = settings or Settings()
    if settings.service_mode != "acceptance":
        raise ValueError("SERVICE_MODE=acceptance required; use an isolated acceptance database")
    engine, sessions = create_database(settings.database_url)
    password_salt = secrets.token_bytes(16)
    password_digest = hashlib.scrypt(
        settings.acceptance_admin_password.get_secret_value().encode(),
        salt=password_salt,
        n=16384,
        r=8,
        p=1,
    )
    stop = threading.Event()

    def token_hash(token):
        # Rotating the admin password invalidates existing cookies across all API replicas.
        return hmac.new(
            settings.acceptance_admin_password.get_secret_value().encode(),
            token.encode(),
            hashlib.sha256,
        ).hexdigest()

    @asynccontextmanager
    async def lifespan(app):
        with sessions() as session:
            if session.scalar(select(Receipt.id).limit(1)):
                raise RuntimeError("ACCEPTANCE_REQUIRES_DATABASE_WITHOUT_BUSINESS_RECEIPTS")
        thread = None
        if settings.acceptance_embedded_worker:

            def loop():
                from app.acceptance.worker import run_once

                while not stop.is_set():
                    try:
                        worked = run_once(sessions, settings)
                    except Exception:
                        worked = False
                    if not worked:
                        stop.wait(settings.worker_poll_seconds)

            thread = threading.Thread(target=loop, daemon=True)
            thread.start()
        yield
        stop.set()
        if thread:
            thread.join(timeout=10)
        engine.dispose()

    app = FastAPI(
        title="Agent 能力驗收台", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.sessions = sessions
    app.state.settings = settings

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            # Bound both chunked and declared bodies before parsing.
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 1_000_000:
                    return JSONResponse({"detail": "REQUEST_TOO_LARGE"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
                return JSONResponse({"detail": "CROSS_ORIGIN_DENIED"}, status_code=403)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        # Service errors are fixed codes; do not leak arbitrary exception text.
        code = str(exc)
        if not code.isupper() or len(code) > 100:
            code = "INVALID_REQUEST"
        return JSONResponse({"detail": code}, status_code=409)

    def auth(request: Request):
        token = request.cookies.get(COOKIE, "")
        with sessions() as session:
            login = session.get(AcceptanceSession, token_hash(token)) if token else None
            if not login or login.expires_at < time.time():
                raise HTTPException(401, "LOGIN_REQUIRED")
            if request.method != "GET" and not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""), login.csrf
            ):
                raise HTTPException(403, "CSRF_REQUIRED")
            return login

    @app.get("/health/ready")
    def health():
        with sessions() as session:
            session.scalar(select(AcceptanceCase.id).limit(1))
        return {"status": "ok", "service": "acceptance"}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    @app.post("/api/login")
    def login(body: Login, request: Request, response: Response):
        peer = hashlib.sha256(
            (request.client.host if request.client else "unknown").encode()
        ).hexdigest()
        with sessions.begin() as session:
            attempts = session.scalar(
                select(func.count())
                .select_from(AcceptanceAudit)
                .where(
                    AcceptanceAudit.action == "login_failed",
                    AcceptanceAudit.created_at > time.time() - 600,
                )
            )
            if attempts >= 10:
                raise HTTPException(429, "TOO_MANY_ATTEMPTS_WAIT_10_MINUTES")
            candidate = hashlib.scrypt(
                body.password.encode(), salt=password_salt, n=16384, r=8, p=1
            )
            valid = secrets.compare_digest(candidate, password_digest)
            if not valid:
                audit(session, "login_failed", peer, {}, actor="anonymous")
        if not valid:
            raise HTTPException(401, "INVALID_PASSWORD")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with sessions.begin() as session:
            session.add(
                AcceptanceSession(
                    token_hash=token_hash(token),
                    csrf=csrf,
                    expires_at=time.time() + 8 * 3600,
                )
            )
            audit(session, "login", "admin", {})
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            secure=settings.app_env == "production",
            samesite="strict",
            max_age=8 * 3600,
            path="/",
        )
        return {"actor": "admin", "csrf": csrf}

    auth_dependency = Depends(auth)

    @app.get("/api/session")
    def session_info(login=auth_dependency):
        return {"actor": "admin", "csrf": login.csrf}

    @app.post("/api/logout")
    def logout(response: Response, login=auth_dependency):
        with sessions.begin() as session:
            row = session.get(AcceptanceSession, login.token_hash)
            if row:
                session.delete(row)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/overview", dependencies=[Depends(auth)])
    def overview():
        with sessions() as session:
            rows = []
            for agent in CATALOG:
                cases = latest_cases(session, agent["id"])
                answers = [latest_answer(session, case.id) for case in cases]
                latest = session.scalar(
                    select(AcceptanceRun)
                    .where(AcceptanceRun.agent == agent["id"])
                    .order_by(AcceptanceRun.created_at.desc())
                    .limit(1)
                )
                run = run_view(session, latest) if latest else None
                if run:
                    run.pop("results")
                rows.append(
                    {
                        **agent,
                        "case_count": len(cases),
                        "approved_count": sum(bool(a and a.status == "approved") for a in answers),
                        "latest_run": run,
                    }
                )
        return {
            "agents": rows,
            "code": code_version(),
            "engineering": {
                "status": "separate_ci",
                "url": "https://github.com/f094spec2-netizen/talent_evaluate/actions/workflows/backend-check.yml",
                "note": "工程結果以 CI 為準；不等於業務能力達標。",
            },
            "integration": {"telegram": "not_verified", "s3": "not_verified"},
            "environment": "QA 操作演練"
            if settings.app_env == "test"
            else "本機驗收"
            if settings.app_env != "production"
            else "隔離雲端驗收",
        }

    @app.get("/api/cases", dependencies=[Depends(auth)])
    def cases(agent: str | None = None, split: str = "all"):
        with sessions() as session:
            output = []
            for row in latest_cases(session, agent, split):
                gold = latest_answer(session, row.id)
                output.append(
                    {
                        "id": row.id,
                        "case_key": row.case_key,
                        "revision": row.revision,
                        "agent": row.agent,
                        "track": row.track,
                        "split": row.split,
                        "source_family": row.source_family,
                        "title": row.title,
                        "visibility": row.visibility,
                        "answer_status": gold.status if gold else "missing",
                        "answer_version": gold.version if gold else None,
                    }
                )
            return output

    @app.get("/api/cases/{case_id}", dependencies=[Depends(auth)])
    def case_detail(case_id: str):
        with sessions() as session:
            row = session.get(AcceptanceCase, case_id)
            if not row:
                raise HTTPException(404, "CASE_NOT_FOUND")
            golds = session.scalars(
                select(GoldAnswer).where(GoldAnswer.case_id == case_id).order_by(GoldAnswer.version)
            ).all()
            return {
                "id": row.id,
                "case_key": row.case_key,
                "title": row.title,
                "task": row.task,
                "provenance": row.provenance,
                "track": row.track,
                "split": row.split,
                "source_family": row.source_family,
                "answers": [
                    {
                        "id": a.id,
                        "version": a.version,
                        "status": a.status,
                        "answer": a.answer,
                        "created_at": a.created_at,
                    }
                    for a in golds
                ],
            }

    @app.post("/api/answers/{answer_id}/decision", dependencies=[Depends(auth)])
    def answer_decision(answer_id: str, body: Decision):
        with sessions.begin() as session:
            decide_answer(session, answer_id, body.decision, body.reason)
        return {"ok": True}

    @app.post("/api/cases/{case_id}/answers", dependencies=[Depends(auth)])
    def new_answer(case_id: str, body: NewAnswer):
        with sessions.begin() as session:
            gold = add_answer(session, case_id, body.answer)
            return {"id": gold.id, "version": gold.version, "status": gold.status}

    @app.post("/api/runs", dependencies=[Depends(auth)], status_code=202)
    def run_create(body: RunRequest):
        for attempt in range(2):
            try:
                with sessions.begin() as session:
                    run = create_run(
                        session, body.agent, body.case_ids, body.split, body.mode, body.request_key
                    )
                    return {"id": run.id, "state": run.state}
            except IntegrityError:
                if attempt:
                    raise HTTPException(409, "CONCURRENT_REQUEST_RETRY_SAME_KEY") from None

    @app.get("/api/runs", dependencies=[Depends(auth)])
    def runs(agent: str | None = None):
        with sessions() as session:
            query = select(AcceptanceRun).order_by(AcceptanceRun.created_at.desc()).limit(100)
            if agent:
                query = query.where(AcceptanceRun.agent == agent)
            return [
                {
                    "id": r.id,
                    "agent": r.agent,
                    "mode": r.mode,
                    "split": r.split,
                    "state": r.state,
                    "created_at": r.created_at,
                    "manifest": r.manifest,
                }
                for r in session.scalars(query)
            ]

    @app.get("/api/runs/{run_id}", dependencies=[Depends(auth)])
    def run_detail(run_id: str):
        with sessions() as session:
            run = session.get(AcceptanceRun, run_id)
            if not run:
                raise HTTPException(404, "RUN_NOT_FOUND")
            return run_view(session, run)

    @app.post("/api/results/{result_id}/adjudication", dependencies=[Depends(auth)])
    def judgment(result_id: str, body: Judgment):
        with sessions.begin() as session:
            adjudicate(session, result_id, body.decision, body.reason)
        return {"ok": True}

    @app.get("/api/audit", dependencies=[Depends(auth)])
    def history(target_id: str | None = None):
        with sessions() as session:
            query = select(AcceptanceAudit).order_by(AcceptanceAudit.created_at.desc()).limit(200)
            if target_id:
                query = query.where(AcceptanceAudit.target_id == target_id)
            return [
                {
                    "id": a.id,
                    "actor": a.actor,
                    "action": a.action,
                    "target_id": a.target_id,
                    "details": a.details,
                    "created_at": a.created_at,
                }
                for a in session.scalars(query)
            ]

    @app.get("/api/code/{artifact_id}", dependencies=[Depends(auth)])
    def code_archive(artifact_id: str):
        with sessions() as session:
            artifact = session.get(AcceptanceArtifact, artifact_id)
            if not artifact:
                raise HTTPException(404, "ARTIFACT_NOT_FOUND")
            return Response(
                artifact.content,
                media_type=artifact.media_type,
                headers={
                    "Content-Disposition": f'attachment; filename="acceptance-code-{artifact_id[:12]}.zip"'
                },
            )

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    return app
