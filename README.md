# Portfolio Governance

Cross-repository notes for public repositories under `styayur`.

Ordinary merge control is native GitHub CI, rulesets, Dependabot, and auto-merge. This repository does not provide a required Evidence Gate or a model review.

## Current controls

- Each repository keeps its own CI and required status checks.
- `native-automerge.yml` may enable GitHub auto-merge for the owner and for Dependabot patch or minor updates. It does not bypass rulesets.
- Workflow, CODEOWNERS, and Dependabot configuration changes are not auto-merged.
- CodeQL stays in `self-governance.yml`.
- Repository categories are `ACTIVE` and `LOW_ACTIVITY`; both use the same
  [native governance lifecycle policy](docs/native-governance-lifecycle.md).

## Retired

The reusable Evidence Gate and its AI review job are not executable workflows. The historical workflow is kept at `evidence/retired/reusable-portfolio-gate.yml`. Do not call it from other repositories.

## Project

- [Styayur Portfolio](https://github.com/users/styayur/projects/1)
- Scope: all public owned repositories.
- `styayur/site` is excluded and its existing project items are archived.

## Evidence

Scheduled and dispatched audits write machine-readable artifacts under `evidence/` in workflow runs. Required record states are `PASS`, `FAIL`, `BLOCKED`, `NOT_APPLICABLE`, and `NOT_VERIFIED`.

Scores never override a security blocker, missing evidence, an unavailable native runner, a paid-provider authorization gap, or a failed real-world acceptance test.
