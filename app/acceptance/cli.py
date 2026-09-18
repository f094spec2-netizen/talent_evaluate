"""Operator commands. Private state and credentials are never written into the repository index."""

import argparse
import json
import os
import secrets
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.acceptance.fixtures import public_cases, seed_cases
from app.acceptance.service import create_run, run_view
from app.acceptance.worker import run_once
from app.config import Settings
from app.database import AcceptanceRun, create_database

LOCAL_ROOT = Path("data/private/acceptance")


def local_settings(root=LOCAL_ROOT, qa=False):
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "local-access.json"
    if not config_path.exists():
        config_path.write_text(
            json.dumps(
                {
                    "password": secrets.token_urlsafe(24),
                    "url": "http://127.0.0.1:8765",
                    "username": "admin",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if os.name != "nt":
            config_path.chmod(0o600)
    password = json.loads(config_path.read_text(encoding="utf-8"))["password"]
    return Settings(
        _env_file=None,
        app_env="test" if qa else "development",
        service_mode="acceptance",
        acceptance_admin_password=password,
        acceptance_embedded_worker=True,
        database_url=f"sqlite:///{(root.resolve() / 'workbench.db').as_posix()}",
        storage_backend="local",
        local_storage_path=root / "objects",
    )


def migrate(settings):
    # Alembic's env uses Settings; only the scoped database setting is needed here.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = settings.database_url
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["init", "serve", "baseline", "import-private", "public-regression"]
    )
    parser.add_argument(
        "--cloud",
        action="store_true",
        help="Read operator-owned acceptance environment instead of local credentials",
    )
    parser.add_argument("--file", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--qa",
        action="store_true",
        help="Isolated browser rehearsal; never approves the real acceptance database",
    )
    parser.add_argument("--split", choices=["all", "development", "holdout"], default="all")
    args = parser.parse_args()
    settings = (
        Settings()
        if args.cloud
        else local_settings(Path("data/private/acceptance-qa") if args.qa else LOCAL_ROOT, args.qa)
    )
    if args.action == "public-regression":
        settings = local_settings(Path("data/private/public-regression"), qa=True)
    if settings.service_mode != "acceptance":
        raise SystemExit("SERVICE_MODE=acceptance required")
    migrate(settings)
    engine, sessions = create_database(settings.database_url)
    with sessions.begin() as session:
        inserted = seed_cases(session, public_cases())
    print(f"Public synthetic cases added: {len(inserted)} (answers remain draft)")
    if args.action == "import-private":
        if not args.file or not args.file.is_file():
            raise SystemExit("--file must be a private prepared case JSON")
        cases = json.loads(args.file.read_text(encoding="utf-8"))
        if any(c["visibility"] != "private_derived" for c in cases):
            raise SystemExit("Only private_derived cases may use this importer")
        with sessions.begin() as session:
            count = len(seed_cases(session, cases))
        print(f"Private derived cases imported: {count}; human approval still required")
    if args.action in ("baseline", "public-regression"):
        ids = []
        for agent in ("collection", "supervisor"):
            with sessions.begin() as session:
                run = create_run(session, agent, [], args.split, "trial", secrets.token_hex(16))
                ids.append(run.id)
        while run_once(sessions, settings):
            pass
        reports = []
        with sessions() as session:
            for row in session.scalars(select(AcceptanceRun).where(AcceptanceRun.id.in_(ids))):
                view = run_view(session, row)
                failures = [
                    r["snapshot"]["case_key"]
                    for r in view["results"]
                    if r["state"] != "completed" or not r["score"].get("correct")
                ]
                reports.append(
                    {
                        "agent": row.agent,
                        "run_id": row.id,
                        "mode": "trial",
                        "failures": failures,
                        "tracks": view["tracks"],
                    }
                )
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        if args.file:
            args.file.parent.mkdir(parents=True, exist_ok=True)
            args.file.write_text(
                json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if args.action == "public-regression" and any(r["failures"] for r in reports):
            raise SystemExit(1)
    engine.dispose()
    if args.action == "serve":
        if args.cloud:
            raise SystemExit("Use the separate Railway API/worker commands for cloud deployment")
        import uvicorn

        from app.acceptance.api import create_app

        print(
            f"Open http://127.0.0.1:{args.port}; login details are in {settings.local_storage_path.parent / 'local-access.json'}"
        )
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
