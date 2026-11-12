# Manual approval protocol v1

R3 and R4 changes are never auto-merged. The required `Portfolio Evidence Gate / verify` check remains red while a manual decision is absent or rejected, and can turn green only after an authenticated maintainer decision is bound to the exact PR, head SHA, base SHA, diff digest and risk tier.

## Authenticated input

Approval is submitted as a GitHub pull-request review. The review author must have repository role `admin` or `maintain`. Bot accounts are always rejected, even when their permission endpoint reports elevated access. The review must target the current PR head commit.

Because repository owners cannot submit an `APPROVE` review on their own PR, a `COMMENTED` review with the exact command is accepted. A maintainer reviewing someone else's PR may use either `APPROVED` or `COMMENTED`.

Refresh evaluation after a review submission, edit or dismissal through the caller's owner-only first-attempt `workflow_dispatch`, supplying the current PR number, head SHA and base SHA. Privileged callers do not subscribe to `pull_request_review`: that event uses the PR merge reference. API review authentication and exact binding remain unchanged; dispatch itself grants no review or merge verdict. Before any checkout, the reusable Gate verifies that its executing callee and script SHA are the same immutable revision in the public governance repository's main history.

## Binding fields

Every command must contain all fields:

```text
pr=<pull request number>
head=<40-character lowercase SHA>
base=<40-character lowercase SHA>
diff=<64-character lowercase SHA-256 digest>
risk=<R3 or R4>
```

The values must match the current risk, static-review and exact-head evidence. A changed PR, head, base or diff invalidates earlier decisions and requires a new review.

## Commands

R3 approval:

```text
/portfolio approve-manual
pr=23
head=<sha>
base=<sha>
diff=<sha256>
risk=R3
```

Rejection:

```text
/portfolio reject-manual
pr=23
head=<sha>
base=<sha>
diff=<sha256>
risk=R3
reason=<maintainer reason>
```

R4 requires all of:

1. the `portfolio:r4-approved` label;
2. an exact-bound `approve-manual` review;
3. a separate exact-bound authorization review:

```text
/portfolio authorize-r4
pr=23
head=<sha>
base=<sha>
diff=<sha256>
risk=R4
```

The latest exact-bound rejection blocks approval until a newer complete approval set exists. A review for another head, base, diff or PR is ignored as stale or replayed.

## States

- `PENDING_MANUAL`: no complete exact-bound approval set exists. The required check fails closed.
- `APPROVED_MANUAL`: the complete exact-bound human approval set exists and all technical/security evidence passes. The required check may pass, but `autoMergeEligible` remains `false`.
- `REJECTED_MANUAL`: an authorized maintainer explicitly rejected the exact binding. The required check fails closed.

`APPROVED_MANUAL` never auto-merges R3/R4. A maintainer must perform the normal platform merge after the required check and branch protection permit it.

## Revalidation

The caller runs on PR review submission, edit and dismissal in addition to normal PR events. The gate recomputes technical evidence and re-reads reviews on every run. Repository branch protection must require branches to be up to date, so a base-branch advance forces a new head and therefore a new exact-bound approval.

## AI boundary

AI review remains advisory for R3/R4. `APPROVE`, `NEEDS_HUMAN` or unavailable AI review cannot create a human approval. An AI `BLOCK` remains a hard blocker. Only an authenticated maintainer review can produce `APPROVED_MANUAL`.
