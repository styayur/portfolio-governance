# Native governance lifecycle

The only governance categories are `ACTIVE` and `LOW_ACTIVITY`. The repository
owner assigns them manually. They express maintenance priority; they do not
change maintenance eligibility, security controls, CI requirements, or merge
permissions. Existing repositories default to `ACTIVE`; TinySTT is explicitly
`LOW_ACTIVITY` and receives the same maintenance policy.

Both categories use the policy in
[`policy/repository-lifecycle.json`](../policy/repository-lifecycle.json):

- Dependabot checks for ordinary updates at 09:00 Asia/Singapore on the 1st and
  15th of each month, with a limit of three ordinary version PRs per ecosystem
  configuration entry.
- Compatible patch/minor updates use native auto-merge subject to existing CI,
  Rulesets, and trust-root restrictions. A group name is not compatibility
  evidence; mixed major metadata or complex failures remain `BLOCKED`.
- Ordinary major upgrades do not auto-merge. Existing compatibility constraints
  on dependencies remain in force.
- Dependabot alerts and security updates stay enabled. Security PRs retain their
  separate GitHub queue. Product vulnerabilities remain security risks and do
  not invalidate a correctly enforced governance architecture by themselves.
- There is no LLM governance runtime or automatic repair bot.

TinySTT's former maintenance pause is removed: both its Cargo and GitHub Actions
entries use an ordinary PR limit of three. Low activity never justifies a zero
ordinary-update limit or disabled security mechanisms.

Archived is an owner-controlled GitHub repository state, not a lifecycle
category. No activity threshold, scheduled workflow, or script may archive,
unarchive, or pause maintenance on a repository. This policy introduces no
periodic lifecycle workflow or automatic classification engine.

Historical reports remain immutable snapshots. Explicitly deferred historical
post-merge verification is recorded as `DEFERRED_NOT_VERIFIED`, not as success.
Deferral does not change Required Checks for new pull requests. A known failed
check and an in-progress check keep their recorded states. This limited
closeout does not dispatch historical CI, automatically fix vulnerabilities, or
automatically archive repositories.
