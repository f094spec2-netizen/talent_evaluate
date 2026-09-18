# Repository Working Rules

These rules apply to every Codex, Claude, human contributor, and other coding agent working in this repository.

## Mandatory startup sequence

Before changing files:

1. Read `README.md`.
2. Read `docs/HANDOFF.md` completely.
3. Check the current branch, working tree, and recent commits.
4. Preserve unrelated or uncommitted work.
5. Confirm that no real personnel data, reports, credentials, or secrets are being added.

## Mandatory handoff rule

Every push to the remote repository must include an update to `docs/HANDOFF.md` in the pushed commit range.

Before pushing, update at least:

- update time and authoring agent;
- branch and current work status;
- work completed in this push;
- files or modules materially changed;
- validation performed and its result;
- unresolved issues or blockers;
- exact recommended next actions;
- any setup, migration, variable, or operational change another computer must know.

Do not put API keys, tokens, passwords, private URLs, employee names, talent assessments, or raw internal data in the handoff.

The handoff is a current-state document, not an append-only diary. Keep it concise and replace stale status. Important permanent decisions belong in the relevant architecture or governance document and should be linked from the handoff.

## Push checklist

Before every push:

1. Pull or fetch the latest remote state and resolve divergence safely.
2. Run checks appropriate to the files changed.
3. Update `docs/HANDOFF.md` after the checks.
4. Review `git diff --cached` for secrets and sensitive personnel data.
5. Confirm the push contains `docs/HANDOFF.md`.
6. Push only when the working state is internally consistent.

GitHub Actions enforces the presence of a handoff update in each push. Do not bypass or disable the check to avoid documenting the work.

## Repository safety

This repository is public. Use only anonymized examples. Never commit source reports, spreadsheets, documents, employee names, assessment results, or credentials. Follow `.gitignore` and `docs/governance/security-and-privacy.md`.
