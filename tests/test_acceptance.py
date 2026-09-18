import base64
import copy
import hashlib
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select

from app.acceptance.adapters import execute
from app.acceptance.api import COOKIE, create_app
from app.acceptance.contracts import CATALOG
from app.acceptance.fixtures import public_cases, seed_cases
from app.acceptance.scoring import metrics, score
from app.acceptance.service import (
    add_answer,
    create_run,
    decide_answer,
    latest_answer,
    latest_cases,
    run_view,
)
from app.acceptance.worker import run_once
from app.config import Settings
from app.database import (
    AcceptanceAudit,
    AcceptanceResult,
    AcceptanceRun,
    Job,
    Receipt,
    SourceFile,
)
from app.queue import claim


@pytest.fixture
def lab(context):
    settings, sessions, _ = context
    settings = settings.model_copy(
        update={
            "service_mode": "acceptance",
            "acceptance_admin_password": SecretStr("test-only-long-password-123"),
        }
    )
    with sessions.begin() as session:
        seed_cases(session, public_cases())
    return settings, sessions


@pytest.mark.parametrize("spec", public_cases(), ids=lambda c: c["case_key"])
def test_public_business_regression(spec):
    output = execute(spec["agent"], copy.deepcopy(spec["task"]))
    result = score(spec["answer"], output)
    assert result["correct"], result
    assert result["critical_errors"] == 0


def test_catalog_and_case_inventory():
    assert len(CATALOG) == 9
    assert sum(a["implemented"] for a in CATALOG) == 2
    assert (
        len(public_cases()) == 36
    )  # 12 standard + 12 anomalies + 12 supervisor; history stays private.
    assert public_cases() == public_cases()  # Office ZIP and core timestamps must be reproducible.
    sources = {}
    for case in public_cases():
        for source in case["task"]["files"]:
            if len(base64.b64decode(source["content_base64"])) > 60:
                prior = sources.setdefault(source["content_base64"], case["split"])
                assert prior == case["split"], "same source leaked across development/holdout"


def test_seed_idempotent_and_source_split_isolation(lab):
    _, sessions = lab
    with sessions.begin() as session:
        assert not seed_cases(session, public_cases())
        bad = copy.deepcopy(public_cases()[0])
        bad["case_key"] = "BAD-SPLIT"
        bad["split"] = "holdout"
        with pytest.raises(ValueError, match="SOURCE_FAMILY_SPLIT"):
            seed_cases(session, [bad])


def test_answers_versions_immutable_and_audited(lab):
    _, sessions = lab
    with sessions.begin() as session:
        case = latest_cases(session, "collection")[0]
        first = latest_answer(session, case.id)
        decide_answer(session, first.id, "approve", "checked source")
        with pytest.raises(ValueError, match="IMMUTABLE"):
            decide_answer(session, first.id, "return", "changed mind")
        second = add_answer(session, case.id, copy.deepcopy(first.answer))
        assert second.version == 2 and second.status == "draft"
        assert first.status == "approved"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AcceptanceAudit)
                .where(AcceptanceAudit.action == "answer_approved")
            )
            == 1
        )


def test_pending_answers_trial_only_and_snapshots_dont_change(lab):
    settings, sessions = lab
    with sessions.begin() as session:
        with pytest.raises(ValueError, match="UNAPPROVED"):
            create_run(session, "collection", [], "all", "formal", "formal-pending-key")
        run = create_run(session, "collection", [], "all", "trial", "trial-pending-key")
        result = session.scalar(select(AcceptanceResult).where(AcceptanceResult.run_id == run.id))
        old = copy.deepcopy(result.snapshot)
        decide_answer(session, old["answer_id"], "approve", "source checked")
        add_answer(session, result.case_id, old["answer"])
    assert run_once(sessions, settings)
    with sessions() as session:
        result = session.get(AcceptanceResult, result.id)
        assert result.snapshot == old
        assert not result.snapshot["approved"]
        assert not run_view(session, session.get(AcceptanceRun, run.id))["passed"]


def test_no_gold_or_case_metadata_crosses_adapter_boundary(lab, monkeypatch):
    settings, sessions = lab
    seen = []

    def adapter(agent, task):
        seen.append(copy.deepcopy(task))
        return execute(agent, task)

    monkeypatch.setattr("app.acceptance.worker.execute", adapter)
    with sessions.begin() as session:
        case = next(c for c in latest_cases(session, "collection") if c.case_key == "C-S01")
        expected_task = copy.deepcopy(case.task)
        create_run(session, "collection", [case.id], "all", "trial", "no-answer-leakage-key")
    run_once(sessions, settings)
    assert seen == [expected_task]
    assert set(seen[0]) == {"files"}
    with pytest.raises(ValueError, match="UNEXPECTED_AGENT_INPUT"):
        execute("collection", {**expected_task, "answer": {}})


def test_failure_never_becomes_success(lab, monkeypatch):
    settings, sessions = lab

    def crash(*args):
        raise RuntimeError("secret error must not appear")

    monkeypatch.setattr("app.acceptance.worker.execute", crash)
    with sessions.begin() as session:
        case = latest_cases(session, "collection")[0]
        run = create_run(session, "collection", [case.id], "all", "trial", "crashing-adapter-key")
    run_once(sessions, settings)
    with sessions() as session:
        view = run_view(session, session.get(AcceptanceRun, run.id))
        assert view["state"] == "failed" and not view["passed"]
        assert view["results"][0]["error_code"] == "RuntimeError"
        assert view["results"][0]["score"] == {}


def result_fixture(human=False, disposition="automatic"):
    answer = {
        "expected_human": human,
        "checks": [{"path": "count", "value": 1}],
        "basis": "test",
        "evidence": [],
    }
    actual = {"disposition": disposition, "count": 1, "records": []}
    return {
        "case_id": "one",
        "snapshot": {"track": "standard", "answer": answer, "approved": True},
        "state": "completed",
        "actual": actual,
        "score": score(answer, actual),
        "adjudication": None,
    }


def test_all_defer_fails_and_missing_cases_block():
    row = result_fixture(disposition="human")
    m = metrics([row], {"standard": ["one"]}, True)["standard"]
    assert m["coverage"] == 0 and m["precision"] is None and not m["passed"]
    good = result_fixture()
    assert metrics([good], {"standard": ["one"]}, True)["standard"]["passed"]
    assert not metrics([good], {"standard": ["one", "missing"]}, True)["standard"]["passed"]
    m = metrics([good], {"standard": ["one", "missing"]}, True, {"standard": ["one", "missing"]})[
        "standard"
    ]
    assert m["coverage"] == 0.5


def test_human_case_excluded_from_coverage_but_escalation_required():
    row = result_fixture(human=True, disposition="human")
    m = metrics([row], {"standard": ["one"]}, True)["standard"]
    assert m["coverage"] is None and m["decidable"] == 0 and m["human_ok"]
    row = result_fixture(human=True, disposition="automatic")
    assert not metrics([row], {"standard": ["one"]}, True)["standard"]["passed"]


def test_human_judgment_cannot_override_critical_errors():
    row = result_fixture()
    row["score"]["human_required"] = True
    assert not metrics([row], {"standard": ["one"]}, True)["standard"]["passed"]
    row["adjudication"] = "accept"
    assert metrics([row], {"standard": ["one"]}, True)["standard"]["passed"]
    row["score"]["critical_errors"] = 1
    assert not metrics([row], {"standard": ["one"]}, True)["standard"]["passed"]
    row["score"]["critical_errors"] = 0
    row["adjudication"] = "return"
    row["score"]["human_required"] = False
    assert not metrics([row], {"standard": ["one"]}, True)["standard"]["passed"]


def test_evidence_missing_or_duplicate_locator_fails():
    answer = {
        "expected_human": False,
        "checks": [{"path": "count", "value": 1}],
        "evidence": [{"locator": "row:1", "quote": "proof"}],
    }
    actual = {
        "count": 1,
        "disposition": "automatic",
        "records": [{"locator": "row:2", "text": "proof"}],
    }
    assert score(answer, actual)["critical_errors"] == 1
    actual["records"] = [{"locator": "row:1", "text": "proof"}] * 2
    assert score(answer, actual)["critical_errors"] == 1


def test_cross_run_isolation_and_request_idempotency(lab):
    settings, sessions = lab
    with sessions.begin() as session:
        r1 = create_run(session, "supervisor", [], "all", "trial", "isolated-run-key-one")
        assert (
            create_run(session, "supervisor", [], "all", "trial", "isolated-run-key-one").id
            == r1.id
        )
        with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_CONFLICT"):
            create_run(session, "collection", [], "all", "trial", "isolated-run-key-one")
        r2 = create_run(session, "supervisor", [], "all", "trial", "isolated-run-key-two")
    while run_once(sessions, settings):
        pass
    with sessions() as session:
        views = [run_view(session, session.get(AcceptanceRun, r.id)) for r in (r1, r2)]
        outputs = [{r["snapshot"]["case_key"]: r["actual"] for r in v["results"]} for v in views]
        assert outputs[0] == outputs[1]
        assert session.scalar(select(func.count()).select_from(Receipt)) == 0
        assert session.scalar(select(func.count()).select_from(SourceFile)) == 0


def test_code_drift_blocks_execution(lab, monkeypatch):
    settings, sessions = lab
    with sessions.begin() as session:
        run = create_run(session, "collection", [], "all", "trial", "code-drift-key-one")
    monkeypatch.setattr("app.acceptance.worker.code_version", lambda: {"source_hash": "changed"})
    run_once(sessions, settings)
    with sessions() as session:
        view = run_view(session, session.get(AcceptanceRun, run.id))
        assert view["state"] == "failed"
        assert all(
            r["error_code"] == "CODE_VERSION_MISMATCH_CREATE_NEW_RUN" for r in view["results"]
        )


def test_exhausted_acceptance_job_fails_run(lab):
    _, sessions = lab
    with sessions.begin() as session:
        run = create_run(session, "supervisor", [], "all", "trial", "exhausted-run-key")
        job = session.scalar(select(Job).where(Job.kind == "acceptance_run"))
        job.state, job.attempts, job.lease_until = "running", 3, 0
    assert claim(sessions, 60, ("acceptance_run",)) is None
    with sessions() as session:
        assert session.get(AcceptanceRun, run.id).state == "failed"


def test_unimplemented_agents_cannot_run(lab):
    _, sessions = lab
    with sessions.begin() as session, pytest.raises(ValueError, match="NOT_IMPLEMENTED"):
        create_run(session, "potential", [], "all", "trial", "unimplemented-key")


def test_production_acceptance_requires_auth_not_telegram():
    settings = Settings(
        _env_file=None,
        service_mode="acceptance",
        app_env="production",
        database_url="postgresql://user:pass@localhost/isolated_acceptance",
        storage_backend="s3",
        s3_endpoint_url="https://s3.example.invalid",
        s3_bucket_name="eval-only",
        s3_access_key_id="test",
        s3_secret_access_key="test",
        acceptance_admin_password="long-test-only-password",
    )
    assert not settings.telegram_bot_token.get_secret_value()
    with pytest.raises(ValidationError):
        Settings(_env_file=None, service_mode="acceptance", acceptance_admin_password="short")


def test_browser_api_auth_csrf_approval_run_and_audit(lab):
    settings, sessions = lab
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 200
        for path in ("/api/overview", "/api/cases", "/api/runs", "/api/audit"):
            assert client.get(path).status_code == 401
        assert client.post("/api/login", json={"password": "bad"}).status_code == 401
        login = client.post("/api/login", json={"password": "test-only-long-password-123"})
        assert login.status_code == 200
        assert (
            "HttpOnly" in login.headers["set-cookie"]
            and "SameSite=strict" in login.headers["set-cookie"]
        )
        headers = {"X-CSRF-Token": login.json()["csrf"]}
        cases = client.get("/api/cases?agent=collection").json()
        detail = client.get(f"/api/cases/{cases[0]['id']}").json()
        gold = detail["answers"][-1]
        path = f"/api/answers/{gold['id']}/decision"
        decision = {"decision": "approve", "reason": "checked against source"}
        assert client.post(path, json=decision).status_code == 403
        assert (
            client.post(
                path, json=decision, headers={**headers, "Origin": "https://evil.invalid"}
            ).status_code
            == 403
        )
        assert client.post(path, json=decision, headers=headers).status_code == 200
        assert client.post(path, json=decision, headers=headers).status_code == 409
        run = client.post(
            "/api/runs",
            headers=headers,
            json={
                "agent": "collection",
                "case_ids": [detail["id"]],
                "mode": "formal",
                "request_key": "browser-api-run-key",
            },
        ).json()
        run_once(sessions, settings)
        view = client.get(f"/api/runs/{run['id']}").json()
        assert view["state"] == "completed" and not view["passed"]  # subset cannot certify a suite.
        result = view["results"][0]
        assert (
            client.post(
                f"/api/results/{result['id']}/adjudication",
                headers=headers,
                json={"decision": "return", "reason": "require follow-up evidence"},
            ).status_code
            == 200
        )
        assert any(a["action"] == "answer_approved" for a in client.get("/api/audit").json())
        assert client.post("/api/logout", json={}, headers=headers).status_code == 200
        assert COOKIE not in client.cookies
        assert client.get("/api/cases").status_code == 401


def test_login_rate_limit_and_payload_bound(lab):
    settings, _ = lab
    with TestClient(create_app(settings)) as client:
        for _ in range(10):
            assert client.post("/api/login", json={"password": "bad"}).status_code == 401
        assert client.post("/api/login", json={"password": "bad"}).status_code == 429
        assert client.post("/api/login", content=b"x" * 1_000_001).status_code == 413


def test_legacy_metadata_and_partial_week_never_expanded():
    from app.agents.collection import collect

    content = (
        b"<p>Supplement: Reporting period: 2026-08-10 ~ 2026-08-15 / Task date: 2026-08-29</p>"
    )
    output = collect("ORG_OFF_weekly_2026-W33_v01.html", content)
    assert output.summary["period_end"] == "2026-08-15"
    assert "NON_ISO_WEEK_RANGE" in output.summary["issues"]
    assert output.summary["period_evidence"][0]["locator"] == "text_line:1"


def test_private_sanitizer_removes_text_attributes_and_scripts():
    from app.acceptance.private_cases import anonymize

    raw = '<html><script>secret()</script><p data-secret="abc">EMPLOYEE_TEST</p><p>覆盖周期:2026-07-27 ~ 2026-08-02</p></html>'
    mapping = {}
    content = anonymize(raw, mapping).decode()
    assert (
        "EMPLOYEE_TEST" not in content and "secret" not in content and "data-secret" not in content
    )
    assert "覆盖周期:2026-07-27 ~ 2026-08-02" in content
    assert "EMPLOYEE" in mapping and "TEST" in mapping


def test_full_approved_supervisor_suite_can_pass(lab):
    settings, sessions = lab
    with sessions.begin() as session:
        for case in latest_cases(session, "supervisor"):
            decide_answer(
                session, latest_answer(session, case.id).id, "approve", "TEST FIXTURE ONLY"
            )
        run = create_run(session, "supervisor", [], "all", "formal", "full-supervisor-suite")
    run_once(sessions, settings)
    with sessions() as session:
        assert run_view(session, session.get(AcceptanceRun, run.id))["passed"]


def test_code_archive_is_authenticated_and_reproducible(lab):
    from app.database import AcceptanceArtifact

    settings, sessions = lab
    with sessions.begin() as session:
        run = create_run(session, "collection", [], "all", "trial", "archive-version-proof")
        artifact_id = run.manifest["code_artifact"]
    with sessions() as session:
        blob = session.get(AcceptanceArtifact, artifact_id).content
        assert hashlib.sha256(blob).hexdigest() == artifact_id
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            assert "app/acceptance/worker.py" in archive.namelist()
            assert "requirements.txt" in archive.namelist()
            assert not any(
                name.startswith("data/") or ".env" in name for name in archive.namelist()
            )
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/code/{artifact_id}").status_code == 401
        client.post("/api/login", json={"password": "test-only-long-password-123"})
        assert client.get(f"/api/code/{artifact_id}").content == blob


def test_password_rotation_invalidates_old_cookie(lab):
    settings, _ = lab
    with TestClient(create_app(settings)) as first:
        first.post("/api/login", json={"password": "test-only-long-password-123"})
        token = first.cookies.get(COOKIE)
    updated = settings.model_copy(
        update={"acceptance_admin_password": SecretStr("changed-test-password-only")}
    )
    with TestClient(create_app(updated)) as second:
        second.cookies.set(COOKIE, token)
        assert second.get("/api/overview").status_code == 401


def test_acceptance_refuses_business_database(lab):
    settings, sessions = lab
    with sessions.begin() as session:
        session.add(
            Receipt(
                delivery_key="business-data",
                company_code="ORG",
                officer_code="OFF",
                filename="x.html",
            )
        )
    with (
        pytest.raises(RuntimeError, match="WITHOUT_BUSINESS_RECEIPTS"),
        TestClient(create_app(settings)),
    ):
        pass


def test_exact_thresholds_and_format_tracks_are_not_averaged():
    rows = []
    for index in range(20):
        row = result_fixture()
        row["case_id"] = str(index)
        if index >= 16:
            row["actual"]["disposition"] = "human"
            row["score"]["correct"] = False
        rows.append(row)
    required = {"standard": [r["case_id"] for r in rows]}
    m = metrics(rows, required, True)["standard"]
    assert m["coverage"] == 0.8 and m["passed"]
    rows[15]["actual"]["disposition"] = "human"
    assert not metrics(rows, required, True)["standard"]["passed"]
    for row in rows:
        row["actual"]["disposition"] = "automatic"
        row["score"]["correct"] = True
    rows[0]["score"]["correct"] = False
    assert metrics(rows, required, True)["standard"]["precision"] == 0.95
    assert metrics(rows, required, True)["standard"]["passed"]
    historical = result_fixture(disposition="human")
    historical["snapshot"]["track"] = "historical"
    result = metrics([*rows, historical], {**required, "historical": ["one"]}, True)
    assert result["standard"]["passed"] and not result["historical"]["passed"]
