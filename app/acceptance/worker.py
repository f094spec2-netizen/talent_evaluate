import copy
import logging
import time

from sqlalchemy import select

from app.acceptance.adapters import execute
from app.acceptance.scoring import score
from app.acceptance.service import code_version
from app.config import Settings
from app.database import AcceptanceResult, AcceptanceRun, create_database
from app.queue import claim, fail, lock_lease

logger = logging.getLogger(__name__)
LOADED_SOURCE_HASH = code_version()["source_hash"]


def run_once(sessions, settings):
    lease = claim(sessions, settings.job_lease_seconds, ("acceptance_run",))
    if not lease:
        return False
    try:
        with sessions.begin() as session:
            if not lock_lease(session, lease):
                return True
            run = session.get(AcceptanceRun, lease.payload["run_id"])
            run.state = "running"
            agent, expected_hash = run.agent, run.manifest["code"]["source_hash"]
            ids = list(
                session.scalars(
                    select(AcceptanceResult.id).where(AcceptanceResult.run_id == run.id)
                )
            )
        if code_version()["source_hash"] != expected_hash or LOADED_SOURCE_HASH != expected_hash:
            with sessions.begin() as session:
                job = lock_lease(session, lease)
                if job:
                    from app.queue import terminal_failure

                    terminal_failure(session, job, "CODE_VERSION_MISMATCH_CREATE_NEW_RUN")
            return True
        for result_id in ids:
            with sessions() as session:
                result = session.get(AcceptanceResult, result_id)
                if result.state in ("completed", "failed"):
                    continue
                snapshot = copy.deepcopy(result.snapshot)
            try:
                # Only this projection crosses the adapter boundary. Gold stays in the evaluator.
                actual = execute(agent, copy.deepcopy(snapshot["task"]))
                grade = score(snapshot["answer"], actual)
                state, error = "completed", None
            except Exception as exc:
                actual, grade, state, error = {}, {}, "failed", type(exc).__name__[:80]
            with sessions.begin() as session:
                job = lock_lease(session, lease)
                if not job:
                    return True
                job.lease_until = time.time() + settings.job_lease_seconds
                result = session.get(AcceptanceResult, result_id, with_for_update=True)
                result.actual, result.score, result.state = actual, grade, state
                result.error_code, result.finished_at = error, time.time()
        with sessions.begin() as session:
            job = lock_lease(session, lease)
            if job:
                run = session.get(AcceptanceRun, lease.payload["run_id"])
                failures = session.scalar(
                    select(AcceptanceResult.id)
                    .where(AcceptanceResult.run_id == run.id, AcceptanceResult.state == "failed")
                    .limit(1)
                )
                run.state, run.finished_at = "failed" if failures else "completed", time.time()
                job.state, job.lease_token = "completed", None
    except Exception as exc:
        fail(sessions, lease, type(exc).__name__[:64])
        logger.warning("Acceptance job %s failed (%s)", lease.id, type(exc).__name__)
    return True


def main():
    settings = Settings()
    if settings.service_mode != "acceptance":
        raise SystemExit("SERVICE_MODE=acceptance required")
    engine, sessions = create_database(settings.database_url)
    try:
        while True:
            if not run_once(sessions, settings):
                time.sleep(settings.worker_poll_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
