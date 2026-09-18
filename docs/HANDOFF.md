# Project Handoff

> Every push must update this file. Read it before starting on any computer or with any coding agent.

## Current snapshot

| Field | Value |
|---|---|
| Last updated | 2026-09-18, Asia/Singapore |
| Updated by | Codex |
| Repository / branch | f094spec2-netizen/talent_evaluate / main |
| Current phase | Phase 1: executable collection Agent and intake supervisor |
| Runtime status | Local anonymous demo verified; production services not provisioned |
| Data policy | Public repository; anonymized examples only |

## Objective and boundaries

Reuse natural project records to create traceable weekly/monthly reporting and talent-assessment evidence. Telegram is the entry point; Railway is the planned host. Facts establish demonstrated capability, while potential remains an uncertain longitudinal signal. Humans retain final talent-grading authority.

This executable slice ends at NORMALIZED source intake. Extracted text is explicitly unverified_source, not verified personal contribution. There are no LLM calls or automatic grades.

## Completed and material changes in this push

- Python 3.12 package, pinned dependencies, environment example, non-root Docker image, development PostgreSQL Compose service.
- FastAPI Telegram webhook: shared-secret verification, account-to-company/officer binding, private-chat restriction, bounded request size, durable deduplicated updates.
- Collection Agent: HTML/HTM, UTF-8 CSV/JSON, XLSX/XLSM and DOCX extraction, with source locators and bounded extraction. Macros/scripts/external links are not executed. Formula text is flagged rather than calculated.
- Conservative filename/body date and ISO-week checks, explicit versions, receipt-versus-processing states, same-version conflicts and cross-period content-reuse flags.
- Supervisor intake slice: normalize a source, retain versions, route unresolved issues to review, write audit events and enqueue a receipt notification.
- PostgreSQL queue: unique jobs, row locks, expiring leases, stale-worker fencing, retry/backoff and terminal-failure state. SQLite supports single-worker local development.
- Local/S3 content-addressed storage, atomic local writes and hash verification on read.
- Telegram /help, /status, download client and completion notifications. No live Bot has been configured.
- Alembic revision 0001: receipts, source files, source records, batches, jobs and audit events.
- Local CLI ingest/status/jobs commands and an anonymous weekly HTML example.
- Tests and CI with PostgreSQL 16 and Docker build.
- README, deployment and upload documents distinguish implemented features from the full target architecture.

Key code: app/api/main.py, app/agents/collection.py, app/supervisor.py, app/queue.py, app/worker.py, app/parsers.py, app/periods.py, app/storage.py, app/telegram.py, app/database.py.

## Validation completed

- Local Python 3.12: **37 passed, 2 skipped**. The skips are PostgreSQL concurrency tests, enabled in CI.
- Ruff passed; Alembic upgrade and schema drift check passed; pip check passed.
- Anonymous CLI demo normalized the sample, extracted 12 fragments, reconciled 2026-W35 with 2026-08-24 to 2026-08-30.
- S3 and Telegram clients tested through stubs/mocked transports, not real services.
- GitHub Actions verified implementation commit f7aa88a: **39 tests passed**, including PostgreSQL concurrency. Migration drift checks and the non-root Docker image build passed. [Backend run](https://github.com/f094spec2-netizen/talent_evaluate/actions/runs/35308705045) and [handoff check](https://github.com/f094spec2-netizen/talent_evaluate/actions/runs/35308705046) succeeded.
- This final documentation update records the validated implementation and the next handoff point; it does not change runtime behavior.
- Two upstream deprecation warnings from the Starlette TestClient/httpx compatibility path remain; tests pass.

## Clean-machine startup

Read AGENTS.md, README.md and this file; fetch remote state and inspect the working tree before editing.

Windows PowerShell, from the repository root:

    py -3.12 -m venv .venv
    .venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-dev.txt
    .venv/Scripts/python.exe -m alembic upgrade head
    .venv/Scripts/python.exe -m pytest -q
    .venv/Scripts/python.exe -m uvicorn app.api.main:create_app --factory --host 127.0.0.1 --port 8000

Run .venv/Scripts/python.exe -m app.worker in a second terminal. On macOS/Linux use python3.12 for venv creation and .venv/bin/python thereafter. Demo commands, configuration and limits are in [the intake runbook](development/intake-mvp.md).

Without .env, local development uses SQLite and storage under ignored data/private/. Webhook stays disabled until configured. Production requires PostgreSQL, shared S3, Bot token, webhook secret and account assignments. Never commit their values.

## Known constraints and risks

- ISO Monday–Sunday weeks are the pilot convention; legacy reporting calendars need confirmation. A filename-only date remains pending unless an explicit body period resolves it.
- Body-period recognition covers labelled headers among the first 40 extracted fragments plus top-level JSON period fields. Arbitrary legacy formatting is not fully understood.
- Missing identity prefix, version or period never silently becomes a confirmed source.
- Current review resolution is correcting/re-uploading the file. No one-click confirmation endpoint yet.
- A batch is one company/officer/type/period. New versions retain old ones; older late arrivals do not lower the current version.
- Notifications are at-least-once and may duplicate after a crash, but do not duplicate source versions.
- Not implemented: PDF, legacy XLS, images/OCR, full supervisor DAG, expected-submission inventory, personnel/project master data, semantic deduplication, verified facts, report generation and talent analysis.
- No cloud deployment, live Telegram delivery or real S3 integration has occurred. Project-software inventory and business ownership need confirmation before pilot onboarding.

## Recommended next actions

1. Build identity master data and identity-archiving Agent with dated assignments and explicit alias conflicts.
2. Add Telegram one-click review for ambiguous periods/identity and an audit-backed resolution service.
3. Add project identity/deduplication and incremental work-event ledger using anonymous golden cases.
4. Add constrained LLM Gateway when extraction/evidence tasks and validation sets are ready.
5. When operator-owned Railway/Bot settings are available, deploy staging, test live delivery and onboard 2–3 pilot companies.

## References

- [Runtime runbook](development/intake-mvp.md)
- [System architecture](architecture/system-architecture.md)
- [Agent orchestration](architecture/agent-orchestration.md)
- [Data model](architecture/data-model.md)
- [Evaluation governance](governance/evaluation-method.md)
- [Upload standard](governance/file-upload-standard.md)
- [Railway plan](deployment/railway.md)

The handoff CI check detects missing updates after a push. It does not itself reject Git pushes; branch protection is a separate repository setting.
