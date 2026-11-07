# Security Policy

terics processes potentially sensitive timetable data and optional authenticated school sessions.

## Security invariants

- The project does not request or store school passwords.
- It does not bypass CAPTCHA, MFA or access controls.
- It does not read the browser Cookie database.
- Extension access uses `activeTab`, not `<all_urls>`.
- SIS requests are same-origin, read-only and user-triggered.
- HTML/XLSX parsing is local; file size is capped at 10 MiB.
- `.terics.json` rejects password/Cookie/Token/Session/CSRF fields.
- Web Google access tokens are memory-only.
- Python Google refresh tokens use the OS keyring.
- Calendar deletion requires complete data, a managed-event filter, and explicit confirmation.
- No background synchronization or monitoring is implemented.

## Reporting

Use GitHub's private security advisory flow:

<https://github.com/styayur/terics/security/advisories/new>

Do not submit real timetables, student identifiers, cookies, tokens, OAuth client secrets or authenticated page captures in a public issue.

## Scope

Security fixes target the latest release, including prereleases. The current candidate is `v0.6.0-rc.1`.

See [docs/threat-model.md](docs/threat-model.md) and [docs/privacy.md](docs/privacy.md).
