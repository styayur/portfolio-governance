# Evidence Gate v0.2

## Guarantees

- Exact base SHA, head SHA and diff digest are bound across risk, static review and AI review evidence.
- Required evidence is resolved from `policy/evidence-matrix.v1.json` by repository profile and risk tier.
- Checks must come from the trusted GitHub Actions App and carry a workflow-run identity. Status contexts without a verifiable workflow run never satisfy required evidence.
- Build, tests, security and native-platform evidence are distinct groups. Lint alone cannot satisfy tests.
- Missing, stale, skipped, cancelled, untrusted, workflow-unknown and pending evidence are reported distinctly.
- An independent AI review adapter is optional. Missing configuration, network failure, malformed output or a SHA/diff mismatch produces `NOT_VERIFIED`, never approval.
- `policy/rollout.json` starts in `shadow` mode. Shadow decisions never set `autoMergeEligible=true`. After the negative suite passes, the rollout switches to `enforce`.
- `maxAttemptsPerHead` stops repeated gate retries for the same exact head.

## Rollout

1. `shadow`: all gate logic runs, but the merge job is disabled.
2. Negative tests prove unsafe and incomplete evidence cannot set auto-merge.
3. `enforce`: R0/R1 auto-merge returns. R2 returns only when the matrix, static review and AI approval all pass. R3/R4 remain manual.

## AI review configuration

The adapter is OpenAI-compatible and uses repository variables:

- `PORTFOLIO_AI_REVIEW_ENABLED=true`
- `PORTFOLIO_AI_REVIEW_ENDPOINT`
- `PORTFOLIO_AI_REVIEW_MODEL`

and the optional secret `PORTFOLIO_AI_REVIEW_API_KEY`.

If any item is missing, the adapter records `AI_REVIEW_NOT_CONFIGURED` and the gate does not claim AI review passed.


## Manual approval v1

R3/R4 do not emit a successful required check merely because technical evidence passes. A `PENDING_MANUAL` decision exits non-zero and leaves the required check red. An authenticated maintainer submits an exact-bound review command containing the PR number, head SHA, base SHA, diff digest and risk tier. `APPROVED_MANUAL` can make the required check pass but never sets `autoMergeEligible`; `REJECTED_MANUAL` remains a hard failure.

AI review is advisory for manual tiers: `NEEDS_HUMAN` or unavailable AI evidence transitions to the manual state machine instead of preempting it. AI `BLOCK` remains a hard blocker. Retry budgets apply only to automatic-merge tiers. R4 further requires the authorization label and a separate `authorize-r4` review. See [Manual approval protocol v1](manual-approval-v1.md).
