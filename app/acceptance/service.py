import copy
import hashlib
import io
import json
import os
import platform
import subprocess
import time
import zipfile
from importlib.metadata import version
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.acceptance.contracts import CONTRACT_VERSION, contract
from app.acceptance.scoring import SCORER_VERSION, metrics
from app.agents.collection import RULE_VERSION
from app.database import (
    AcceptanceArtifact,
    AcceptanceAudit,
    AcceptanceCase,
    AcceptanceResult,
    AcceptanceRun,
    Adjudication,
    GoldAnswer,
)
from app.queue import enqueue


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def code_files():
    root = Path(__file__).resolve().parents[2]
    files = sorted(
        p for p in (root / "app").rglob("*") if p.suffix in (".py", ".js", ".css", ".html")
    )
    files += sorted((root / "migrations").rglob("*.py"))
    files += [
        root / name
        for name in (
            "requirements.txt",
            "requirements-dev.txt",
            "pyproject.toml",
            "alembic.ini",
            "Dockerfile",
        )
        if (root / name).exists()
    ]
    return root, files


def code_version():
    root, files = code_files()
    hashes = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }
    commit = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")
    dirty = None
    try:
        commit = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, timeout=5, stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--", "app"], cwd=root, timeout=5
            ).strip()
        )
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "commit": commit or "unavailable",
        "dirty": dirty,
        "source_hash": digest(hashes),
        "python": platform.python_version(),
        "dependencies": {
            name: version(name)
            for name in ("fastapi", "sqlalchemy", "openpyxl", "beautifulsoup4", "pydantic")
        },
    }


def capture_code(session):
    root, files = code_files()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(root).as_posix(), (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    content = stream.getvalue()
    artifact_id = hashlib.sha256(content).hexdigest()
    if not session.get(AcceptanceArtifact, artifact_id):
        try:
            with session.begin_nested():
                session.add(
                    AcceptanceArtifact(
                        id=artifact_id, content=content, media_type="application/zip"
                    )
                )
                session.flush()
        except IntegrityError:
            if not session.get(AcceptanceArtifact, artifact_id):
                raise
    return artifact_id


def audit(session, action, target, details, actor="admin"):
    session.add(AcceptanceAudit(actor=actor, action=action, target_id=target, details=details))


def latest_cases(session, agent=None, split=None):
    query = select(AcceptanceCase).order_by(AcceptanceCase.case_key, AcceptanceCase.revision)
    if agent:
        query = query.where(AcceptanceCase.agent == agent)
    if split and split != "all":
        query = query.where(AcceptanceCase.split == split)
    latest = {row.case_key: row for row in session.scalars(query)}
    return list(latest.values())


def latest_answer(session, case_id):
    return session.scalar(
        select(GoldAnswer)
        .where(GoldAnswer.case_id == case_id)
        .order_by(GoldAnswer.version.desc())
        .limit(1)
    )


def validate_answer(answer):
    if not isinstance(answer, dict) or not isinstance(answer.get("expected_human"), bool):
        raise ValueError("ANSWER_EXPECTED_HUMAN_REQUIRED")
    if not isinstance(answer.get("checks"), list) or not answer["checks"]:
        raise ValueError("ANSWER_CHECKS_REQUIRED")
    for check in answer["checks"]:
        if (
            not isinstance(check, dict)
            or not isinstance(check.get("path"), str)
            or "value" not in check
            or check.get("op", "eq") not in ("eq", "contains", "set_eq", "gte")
        ):
            raise ValueError("INVALID_CHECK")
    if not isinstance(answer.get("basis"), str) or not answer["basis"].strip():
        raise ValueError("ANSWER_BASIS_REQUIRED")
    if not isinstance(answer.get("evidence", []), list):
        raise ValueError("INVALID_EVIDENCE")
    for item in answer.get("evidence", []):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("quote"), str)
            or not item["quote"]
        ):
            raise ValueError("INVALID_EVIDENCE")
    if not isinstance(answer.get("rubric", []), list):
        raise ValueError("INVALID_RUBRIC")


def add_answer(session, case_id, answer):
    validate_answer(answer)
    # Serialize revisions on the parent (PostgreSQL); SQLite is single-writer only.
    if not session.get(AcceptanceCase, case_id, with_for_update=True):
        raise ValueError("CASE_NOT_FOUND")
    previous = latest_answer(session, case_id)
    gold = GoldAnswer(
        case_id=case_id, version=previous.version + 1 if previous else 1, answer=answer
    )
    session.add(gold)
    session.flush()
    audit(
        session,
        "answer_created",
        gold.id,
        {"case_id": case_id, "version": gold.version, "hash": digest(answer)},
    )
    return gold


def decide_answer(session, answer_id, decision, reason):
    gold = session.get(GoldAnswer, answer_id, with_for_update=True)
    if not gold:
        raise ValueError("ANSWER_NOT_FOUND")
    session.get(AcceptanceCase, gold.case_id, with_for_update=True)
    if gold.status != "draft":
        raise ValueError("ANSWER_DECISION_IMMUTABLE_CREATE_NEW_VERSION")
    if latest_answer(session, gold.case_id).id != gold.id:
        raise ValueError("ANSWER_SUPERSEDED")
    gold.status = "approved" if decision == "approve" else "returned"
    audit(
        session,
        f"answer_{gold.status}",
        gold.id,
        {"reason": reason, "answer_hash": digest(gold.answer), "version": gold.version},
    )


def create_run(session, agent, selected_ids, split, mode, request_key):
    existing = session.scalar(select(AcceptanceRun).where(AcceptanceRun.request_key == request_key))
    if existing:
        if existing.manifest["request"] != {
            "agent": agent,
            "case_ids": selected_ids,
            "split": split,
            "mode": mode,
        }:
            raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
        return existing
    info = contract(agent)
    if not info or not info["implemented"]:
        raise ValueError("AGENT_NOT_IMPLEMENTED")
    cases = latest_cases(session, agent, split)
    selected = [c for c in cases if not selected_ids or c.id in selected_ids]
    if not selected or (selected_ids and set(selected_ids) != {c.id for c in selected}):
        raise ValueError("CASE_SELECTION_INVALID")
    snapshots = []
    for case in selected:
        gold = latest_answer(session, case.id)
        if not gold or (mode == "formal" and gold.status != "approved"):
            raise ValueError("UNAPPROVED_ANSWERS_TRIAL_ONLY")
        snapshots.append(
            {
                "case_id": case.id,
                "case_key": case.case_key,
                "revision": case.revision,
                "track": case.track,
                "split": case.split,
                "source_family": case.source_family,
                "task": copy.deepcopy(case.task),
                "answer": copy.deepcopy(gold.answer),
                "answer_id": gold.id,
                "answer_version": gold.version,
                "approved": gold.status == "approved",
                "provenance": case.provenance,
            }
        )
    required, required_decidable = {}, {}
    for case in cases:
        required.setdefault(case.track, []).append(case.id)
        required_decidable.setdefault(case.track, [])
        required_gold = latest_answer(session, case.id)
        if not required_gold or not required_gold.answer["expected_human"]:
            required_decidable[case.track].append(case.id)
    required_counts = {
        "collection": {"standard": 12, "historical": 12, "anomaly": 12},
        "supervisor": {"workflow": 12},
    }[agent]
    installed = latest_cases(session, agent)
    inventory_ok = all(
        sum(c.track == t for c in installed) >= count for t, count in required_counts.items()
    )
    manifest = {
        "request": {"agent": agent, "case_ids": selected_ids, "split": split, "mode": mode},
        "code": code_version(),
        "code_artifact": capture_code(session),
        "dataset_hash": digest(snapshots),
        "rule_version": RULE_VERSION,
        "contract_version": CONTRACT_VERSION,
        "scorer_version": SCORER_VERSION,
        "model": None,
        "prompt_version": None,
        "repetition": 1,
        "integration": "business_acceptance_with_fixture_transport",
        "required": required,
        "required_decidable": required_decidable,
        "inventory_complete": inventory_ok,
    }
    run = AcceptanceRun(
        request_key=request_key, agent=agent, mode=mode, split=split, manifest=manifest
    )
    session.add(run)
    session.flush()
    for snapshot in snapshots:
        session.add(AcceptanceResult(run_id=run.id, case_id=snapshot["case_id"], snapshot=snapshot))
    enqueue(session, f"acceptance:{run.id}", "acceptance_run", {"run_id": run.id})
    audit(session, "run_created", run.id, {"mode": mode, "dataset_hash": manifest["dataset_hash"]})
    return run


def serialize_result(session, result, include_snapshot=True):
    adjudications = session.scalars(
        select(Adjudication)
        .where(Adjudication.result_id == result.id)
        .order_by(Adjudication.created_at)
    ).all()
    output = {
        "id": result.id,
        "case_id": result.case_id,
        "state": result.state,
        "actual": result.actual,
        "score": result.score,
        "error_code": result.error_code,
        "finished_at": result.finished_at,
        "adjudication": adjudications[-1].decision if adjudications else None,
        "adjudications": [
            {
                "decision": a.decision,
                "reason": a.reason,
                "actor": a.actor,
                "created_at": a.created_at,
            }
            for a in adjudications
        ],
    }
    if include_snapshot:
        output["snapshot"] = result.snapshot
    return output


def run_view(session, run):
    results = [
        serialize_result(session, row)
        for row in session.scalars(
            select(AcceptanceResult).where(AcceptanceResult.run_id == run.id)
        )
    ]
    tracks = metrics(
        results,
        run.manifest["required"],
        run.mode == "formal" and run.state == "completed",
        run.manifest["required_decidable"],
    )
    inventory_ok = run.manifest["inventory_complete"]
    full_suite = run.split == "all" and inventory_ok
    return {
        "id": run.id,
        "agent": run.agent,
        "mode": run.mode,
        "split": run.split,
        "state": run.state,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "manifest": run.manifest,
        "tracks": tracks,
        "results": results,
        "passed": full_suite and bool(tracks) and all(t["passed"] for t in tracks.values()),
        "inventory_complete": inventory_ok,
        "full_suite": full_suite,
    }


def adjudicate(session, result_id, decision, reason):
    result = session.get(AcceptanceResult, result_id)
    if not result or result.state != "completed":
        raise ValueError("COMPLETED_RESULT_REQUIRED")
    # Human acceptance never erases deterministic failures or critical errors.
    session.add(Adjudication(result_id=result_id, actor="admin", decision=decision, reason=reason))
    audit(
        session,
        "result_adjudicated",
        result_id,
        {"decision": decision, "reason": reason, "at": time.time()},
    )
