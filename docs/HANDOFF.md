# Project Handoff

> Every push must update this file. Read AGENTS.md, README.md and this file first on every computer.

## Current snapshot

| Field | Value |
|---|---|
| Updated | 2026-09-18, Asia/Singapore · Codex |
| Repository / branch | f094spec2-netizen/talent_evaluate / main |
| Phase | Browser business-acceptance workbench implemented; user approval pending |
| Hosting | Loopback browser version running on development machine; Railway NOT provisioned |
| User decision | No Railway account yet; complete the operable version first |
| Privacy | Public repo/CI synthetic only; derived cases, mappings, credentials and runs private |

## Delivered in this change

- FastAPI acceptance service and responsive Chinese UI: nine-agent catalog, case selection, trial/formal execution, side-by-side evidence/expected/actual/diffs, approve/return, new answer versions, result adjudication, run comparison, audit trail and private exports.
- Real adapters for collection and supervisor **intake slice only**. Seven future agents remain non-executable; contracts/specifications are in the catalog and dedicated document. Full supervisor DAG is not implemented.
- Single admin login, scrypt verification, HttpOnly/SameSite cookies (Secure in production), CSRF/origin checks, bounded requests, rate-limited failed login, password-rotation invalidation, CSP and text-only evidence rendering.
- Immutable case/answer revisions and run snapshots, per-track scoring, required-case denominators, no automatic gold approval, no all-defer/subset/error false pass, manual adjudication cannot erase critical failures.
- Existing database queue reused with isolated job kinds, fenced execution and visible exhausted jobs. Fresh temporary intake database/object directory for each supervisor scenario; no business DB pollution.
- Source commit/hash, Python/dependency versions, rules/scorer/dataset/answer versions and downloadable content-addressed code ZIP. Earliest development baselines predate ZIP capture and remain hash-only.
- 36 public synthetic cases: 12 standard collection + 12 anomalies + 12 supervisor. Another 12 historical HTML cases prepared and imported into the originating machine's PRIVATE case store (not in Git). Latest total is 48; old revisions remain retained.
- Source-family partition enforcement, independent synthetic source namespaces, deterministic Office ZIP bytes and private structural deidentification helper.
- Real historical baseline exposed four period-recognition failures. Parser now handles labelled legacy statistics/coverage periods while retaining non-ISO/conflict escalation and evidence locators.
- One draft completeness oracle was corrected after directly counting nonblank source lines; old case/failed run retained. This was an oracle correction, not proof of agent improvement. All latest business answers remain unapproved.
- Railway API/worker config files prepared; acceptance production settings do not require Telegram credentials. NO cloud resources, paid services or live integration were created.
- CI keeps original engineering tests and adds public synthetic regression with a non-sensitive summary artifact.

Key modules: app/acceptance/{api,service,scoring,adapters,worker,fixtures,private_cases,cli,contracts}.py and static/.
Other changes: database models, queue kind filtering, settings, collection/period rules, package-data, CI, deployment configs.
Migrations: 0001 -> 438e64fe6510 -> a3abf32246ec.

## Validation and current evidence

- Local Python 3.12: **97 passed, 2 skipped** (PostgreSQL-only tests run in CI). Original 39 engineering tests retained.
- Public business regression: **36/36 match draft gold**, isolated regression database; NOT formal business acceptance.
- Latest private + public trial: **48/48 match draft gold**, zero critical differences, evidence checks satisfied. This is a small rule-engine baseline, NOT verified generalization or user-approved capability.
- Baseline stages retained: four real legacy-format failures before parser fix; development rerun; held-out run revealing one incorrect draft line-count expectation; revised case; full trial. Do not delete those records to manufacture a green history.
- Playwright browser rehearsal in separate QA DB: login, select case, trial, inspect sources, approve QA-only gold, formal single-case rerun; incomplete suite correctly remains not passed. Desktop 1600 px and mobile 390 px inspected; no horizontal overflow at mobile width.
- Ruff, schema drift check and pip check pass. Two upstream Starlette/httpx deprecation warnings remain.
- No actual user gold approval or final browser sign-off yet. No live Telegram/S3 verification. Railway configurations have not been deployed.
- Remote CI for this implementation must be checked after push; do not infer it from local results.

## Exact startup and private state

Windows developer command after installing pinned dependencies:

    .venv/Scripts/python.exe -m app.acceptance.cli serve

This migrates, seeds public drafts and serves http://127.0.0.1:8765 with an embedded local queue worker.
Login credentials: ignored data/private/acceptance/local-access.json.
Database: ignored data/private/acceptance/workbench.db.
Private source manifest, derived cases and mappings: same private directory; **do not commit or publish**.
Raw source reports remain untouched outside the repo.
Browser QA: serve --qa --port 8766, isolated data/private/acceptance-qa/.
Public regression: public-regression --file output/public-acceptance-baseline.json, isolated data/private/public-regression/.

These loopback services are not installed as auto-start Windows services. A reboot requires a developer restart; the user need not install software or run commands.
Other computers receive only public cases from Git. Transfer private DB/exports and maps through an approved private channel if needed; never use repo/CI attachments.

## Version and storage details

- Collection rules: intake-2026-09-18.2.
- Acceptance contract: acceptance-2026-09-18.1; scorer: exact-evidence-2.
- Public case revision 3 namespaces synthetic sources; historical current revision 2 preserves doctype and corrects the draft line-count case.
- Answers are draft unless the actual administrator decides otherwise. QA approvals must not migrate to business acceptance.
- First-stage case bytes and code ZIPs are stored in private SQL tables. Evaluation S3 credentials/bucket are reserved for later large attachments; current business fixtures do not validate live S3.
- Full approval is per whole required suite and each format track. UI success does not automatically deploy or enable another agent.
- No LLM adapter: future model integration must require three same-set repeat runs, model/prompt versions and independent human rubric. Do not treat the current single deterministic run as an LLM acceptance.
- Source hash changes while queued cause a visible version failure; restart API/worker after changing code and create a new run. Do not keep old in-memory code serving a newly edited tree.
- SQLite is local single-worker only. Cloud requires PostgreSQL and separate API/worker. Individual adapter calls must finish within the lease; long LLM work needs heartbeat/timeout additions.

## Next actions

1. Let the user open the local workbench, inspect gold and complete their own select/run/check/approve/rerun operation. Do not approve on their behalf.
2. Review the 12 private historical cases and the explicit supplemental metadata assumptions before approving.
3. When the user has a Railway account, provision an isolated evaluation environment, database and bucket; configure admin password privately and deploy the two checked-in service configurations. Do not touch business production.
4. Import only privately reviewed derived cases; do not import raw reports/mappings into the web app. Verify HTTPS cookies, authorization, worker recovery and version alignment before giving a cloud URL.
5. Add identity archiving next only after its source-grouped cases and gold are reviewed. Maintain evidence/claims boundaries, not automatic personnel grades.
6. Expand previously unseen holdout families before any LLM release; the exercised set is now a regression set.

## References

- [Acceptance runbook](development/acceptance-lab.md)
- [Future agent contracts](development/future-agent-acceptance.md)
- [Original intake runbook](development/intake-mvp.md)
- [Railway plan](deployment/railway.md)
- [Evaluation governance](governance/evaluation-method.md)
- [Security/privacy](governance/security-and-privacy.md)
- [Repository workflow](governance/repository-workflow.md)

The handoff workflow detects missing updates after pushes; branch protection remains a separate setting.
