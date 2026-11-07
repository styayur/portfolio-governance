# Portfolio Governance

Cross-repository governance for **public** repositories under `styayur`.

This repository provides a reusable, fail-closed evidence gate for pull requests. It is designed for GitHub Codespaces-first operation: interactive work starts in Codespaces, while persistent automation lives in GitHub Actions, a GitHub App, and the user-owned **Styayur Portfolio** Project.

## Security model

**Coding agent ≠ independent review agent ≠ evidence gate.**

- Risk classification reads the PR diff and explains an R0–R4 level.
- Independent review treats PR text and code as untrusted data and never executes it.
- The evidence gate binds repository ID, PR number, base SHA, head SHA, workflow run, test/security results, evidence URLs and decision.
- Auto-merge is requested only for R0–R2 after a non-draft PR has a clean policy result.
- R3/R4 changes remain a manual maintainer decision. No ruleset bypass is used.

## Reusable workflow

Call `.github/workflows/reusable-portfolio-gate.yml` from each public repository with the exact central commit SHA. The caller uses `pull_request_target` so the privileged job never executes PR code. The reusable workflow checks out only this repository at the pinned SHA.

The caller template is in `templates/caller-portfolio-gate.yml`.

## Project

- [Styayur Portfolio](https://github.com/users/styayur/projects/1)
- Scope: all public owned repositories.
- `styayur/site` is excluded and its existing project items are archived.

## Evidence

Scheduled and dispatched audits write machine-readable artifacts under `evidence/` in workflow runs. Required record states are `PASS`, `FAIL`, `BLOCKED`, `NOT_APPLICABLE`, and `NOT_VERIFIED`.

Scores never override a security blocker, missing evidence, an unavailable native runner, a paid-provider authorization gap, or a failed real-world acceptance test.
