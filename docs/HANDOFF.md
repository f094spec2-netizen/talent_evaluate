# Project Handoff

> Every push must update this file. Read it before starting work on any computer or with any coding agent.

## Current snapshot

| Field | Value |
|---|---|
| Last updated | 2026-09-18, Asia/Singapore |
| Updated by | Codex |
| Repository | `f094spec2-netizen/talent_evaluate` |
| Primary branch | `main` |
| Current phase | Architecture and governance baseline |
| Runtime status | No application runtime has been implemented yet |
| Data policy | Public repository; anonymized architecture and examples only |

## Project objective

Build an agent-based system for the efficiency center that reuses natural project records and submitted files to create a traceable fact ledger, weekly/monthly outputs, capability-boundary evidence, and potential signals. Telegram is the user entry point, Railway is the planned runtime platform, and humans retain final authority over talent grading and sensitive decisions.

## Completed and stored

- Overall system architecture and planned Python technology stack.
- Supervisor Agent responsibilities and eight specialist Agent contracts.
- Batch state machine and green/yellow/red review routing.
- Rolling fact-ledger data model and evidence model.
- Talent-evaluation method and governance boundaries.
- File naming, date/week verification, format, version, and duplicate rules.
- Railway all-in-one deployment topology.
- Security, privacy, access, backup, and LLM data-minimization rules.
- MVP phases and suggested acceptance metrics.
- An anonymized interactive HTML architecture visualization.
- Repository-wide handoff workflow for Codex and Claude.

## Material changed in this handoff

- Added `AGENTS.md` as the authoritative cross-agent working rule.
- Added `CLAUDE.md` as Claude's entry point to the shared rules.
- Added this living `docs/HANDOFF.md` document.
- Added a GitHub Actions check requiring every push to update this file.
- Added a pull-request checklist and documented the repository workflow.

## Key architecture decisions

1. Telegram is an entry channel only; agents run in a Railway backend.
2. Railway services are `tg-api`, `agent-worker`, PostgreSQL, a private bucket, and short-lived cron enqueue jobs.
3. The first queue implementation uses PostgreSQL `agent_jobs`; Redis is deferred until measured demand justifies it.
4. One codebase and one Docker image use different start commands for each service.
5. Deterministic code handles validation, hashes, versions, dates, weeks, and state transitions.
6. Large models handle constrained extraction and evidence-backed analysis through a central LLM Gateway.
7. Agents return structured candidates and cannot directly modify official talent records.
8. Final talent grades, sensitive negative conclusions, and major disputes remain human decisions.
9. The initial MVP does not automatically assign final talent grades.

Permanent details are in:

- `docs/architecture/system-architecture.md`
- `docs/architecture/agent-orchestration.md`
- `docs/architecture/data-model.md`
- `docs/governance/evaluation-method.md`
- `docs/deployment/railway.md`

## Validation completed

- Verified all required architecture and governance files exist.
- Compiled the inline JavaScript in the visualization without syntax errors.
- Scanned committed content for the known real-person names from the source materials; none are present.
- Confirmed the first architecture commit was pushed to `origin/main`.
- Confirmed the handoff enforcement workflow completed successfully for commit `4d7ddea`.

## Known constraints and risks

- The GitHub repository is public. No real personnel data or original reports may be committed.
- The implementation code, database migrations, Telegram bot, Railway services, and automated tests do not yet exist.
- Exact Railway and model costs must be measured during the pilot.
- Project-management systems used by each company have not yet been inventoried.
- The final capability taxonomy, review thresholds, and retention periods still require business approval.

## Recommended next actions

1. Confirm the 2–3 pilot companies, business owner, and efficiency-center project owner.
2. Inventory the project-management software and export/API capability used by each pilot company.
3. Create the Python application skeleton, Docker image, migrations, and local development environment.
4. Implement Telegram authentication and the file-ingestion pipeline first.
5. Build the fact-ledger schema and deterministic date/week/version checks.
6. Prepare anonymized golden test cases before adding LLM extraction.

## Clean-machine startup

```powershell
git clone https://github.com/f094spec2-netizen/talent_evaluate.git
Set-Location talent_evaluate
Get-Content .\AGENTS.md -Raw
Get-Content .\docs\HANDOFF.md -Raw
git status --short --branch
git log --oneline -5
```

No application installation command is available yet because the runtime has not been scaffolded. Add exact setup, test, migration, and launch commands here when implementation begins.

## Handoff completion checklist

- [x] Current state is understandable without access to the previous chat.
- [x] Permanent architecture documents are linked.
- [x] Completed checks and remaining risks are stated.
- [x] Next actions are concrete.
- [x] No secrets or personnel data are included.
- [x] GitHub Actions handoff check confirmed after push.
