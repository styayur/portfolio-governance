# Security Policy

## Supported versions

Security fixes target the current `main` branch of this governance repository. Reusable workflows should be called by full commit SHA so a mutable branch cannot silently change review logic.

No response-time SLA or security email is invented or promised here.

## Report privately

Use GitHub private vulnerability reporting:

https://github.com/styayur/portfolio-governance/security/advisories/new

Include the affected workflow and commit SHA, repository and PR context, impact, and a synthetic reproduction. Do not include tokens, private repository content, production secrets, student data, captured sessions, or personal files.

## Security boundaries

- The privileged review path must not checkout or execute pull-request code.
- Third-party Actions should be pinned to full commit SHAs and granted minimal permissions.
- Evidence artifacts must not contain credentials, raw private data, or unrestricted production logs.
- A GitHub App used for persistent cross-repository automation should receive only the permissions required by its workflow and must not receive unrelated production credentials.

## Known limitation

A passing automated gate does not prove correctness of a product, security of a third-party service, legal license compatibility, or real-device behavior. Those require the appropriate evidence and human or authorized external verification.
