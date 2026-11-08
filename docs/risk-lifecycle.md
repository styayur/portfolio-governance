# Risk operations and final acceptance

## Dependabot dispositions

`policy/dependabot-dispositions.json` maps live Dependabot findings to an explicit disposition. The audit never dismisses alerts. Every unmatched alert is classified as `UNCLASSIFIED_BLOCKED` and causes a non-zero result after the evidence is written.

The daily risk workflow writes:

- `evidence/risk/dependabot-risk-disposition.json`
- `evidence/risk/pat-rotation.json`

It also upserts a single live risk-register issue so the Portfolio Project can mirror it through its normal issue synchronization.

## Project token rotation

`PORTFOLIO_PROJECT_TOKEN_EXPIRES_AT` is checked at 30, 14 and 7 days. The current configured expiry is 2027-02-06. A critical or expired token fails the workflow; it is never converted to PASS.

## Final acceptance timing

`final-acceptance.yml` waits for successful exact-SHA runs of:

- Governance self-checks
- Portfolio audit
- Portfolio project sync
- Portfolio risk operations

Only then does it build the final evidence snapshot and upload the artifact. A missing, pending or failed workflow prevents snapshot generation.

## Code scanning states

The portfolio audit distinguishes:

- `UNAUTHORIZED`
- `NOT_ENABLED`
- `NO_RESULTS`
- `FINDINGS`
- `SCAN_FAILED`
- `NOT_VERIFIED`

These states are not collapsed into a generic scanner error.
