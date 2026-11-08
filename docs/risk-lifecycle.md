# Risk operations and final acceptance

## Dependabot dispositions

`policy/dependabot-dispositions.json` maps live Dependabot findings for the public portfolio to an explicit disposition. The audit never dismisses alerts. Every unmatched alert is classified as `UNCLASSIFIED_BLOCKED` and causes a non-zero result after the evidence is written.

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

## Credential boundaries

- `PORTFOLIO_PROJECT_TOKEN`: user-owned GitHub Projects V2 mutation and portfolio-wide read orchestration; scoped to `project`; expires 2027-02-06 and is checked at 30/14/7 days.
- `PORTFOLIO_APP_PRIVATE_KEY` / `PORTFOLIO_APP_CLIENT_ID`: mint a short-lived installation token. Dependabot risk reads use this token with `dependabot-alerts: read`; the installation token is not used for Projects V2 mutation.
- `GITHUB_TOKEN`: issue synchronization and same-repository metadata only. It is never used to claim cross-repository evidence.

Risk evidence files are workflow artifacts, not reviewed source snapshots. The daily workflow writes them under `evidence/risk/`; the final-acceptance run uploads the exact artifact after all related exact-SHA workflows complete.

The project sync runs hourly to keep the Portfolio Project aligned with live PR, Issue and risk-register state. It uses the scoped Projects token for mutation and a short-lived App token for read-only repository data.

The risk register intentionally contains public-repository alert metadata. Private repository data is excluded by the public-repository enumeration.
