# Portfolio Governance

Cross-repository governance for **public** repositories under `styayur`.

This repository provides a reusable, fail-closed evidence gate for pull requests. It is designed for GitHub Codespaces-first operation: interactive work starts in Codespaces, while persistent automation lives in GitHub Actions, a GitHub App, and the user-owned **Styayur Portfolio** Project.

## Security model

**Coding agent ≠ independent review agent ≠ evidence gate.**

- Risk classification reads the PR diff and explains an R0–R4 level.
- Independent review treats PR text and code as untrusted data and never executes it.
- The evidence gate binds repository ID, PR number, base SHA, head SHA, diff digest, workflow run, trusted GitHub App check sources, native evidence, security evidence and decision.
- Required build/test/security/native evidence comes from a repository-and-risk matrix; a single successful check is never treated as complete evidence.
- New gate logic starts in shadow mode, where it records eligibility but never auto-merges.
- In enforce mode R0/R1 may auto-merge. R2 also requires the complete matrix, static review and an independent AI reviewer approval. R3/R4 are never auto-merged. Their required check remains failed until an exact-bound, authenticated maintainer review approves the current PR/head/base/diff; R4 additionally requires the `portfolio:r4-approved` label and an explicit `authorize-r4` review.
- Unavailable AI review, skipped/cancelled checks, untrusted check sources and missing workflow-run identity are `NOT_VERIFIED` or blocked, never PASS.

## Reusable workflow

Call `.github/workflows/reusable-portfolio-gate.yml` from each public repository with the exact central commit SHA. The caller uses `pull_request_target` so the privileged job never executes PR code. The reusable workflow checks out only this repository at the pinned SHA.

The caller template is in `templates/caller-portfolio-gate.yml`. Privileged callers use base-defined `pull_request_target` events and exact-input owner dispatch; they must not use `pull_request_review`, whose workflow comes from the PR merge reference. After an authenticated review is submitted, edited or dismissed, refresh the Gate through the owner dispatch with the current PR/head/base binding. The evaluator still reads the actual review records through the API; this event change does not convert a comment into code approval. See [Manual approval protocol v1](docs/manual-approval-v1.md).

## Project

- [Styayur Portfolio](https://github.com/users/styayur/projects/1)
- Scope: all public owned repositories.
- `styayur/site` is excluded and its existing project items are archived.

## Evidence

Scheduled and dispatched audits write machine-readable artifacts under `evidence/` in workflow runs. Required record states are `PASS`, `FAIL`, `BLOCKED`, `NOT_APPLICABLE`, and `NOT_VERIFIED`.

Scores never override a security blocker, missing evidence, an unavailable native runner, a paid-provider authorization gap, or a failed real-world acceptance test.
