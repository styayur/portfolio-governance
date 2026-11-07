# Security Policy

## Supported version

Security fixes target the current `main` branch, the latest release, and the current GitHub Pages deployment.

## Report privately

Do not report exploitable issues in a public issue. Use GitHub private vulnerability reporting:

https://github.com/styayur/musical-spinningtop/security/advisories/new

Include the affected local/static surface, version or snapshot date, Python/browser version, reproduction steps, impact, and any proof-of-concept details needed to verify the report. Remove private browser data and local SQLite files.

## Scope

Relevant issues include cross-site scripting, unsafe URL or image-source handling, request forgery, path traversal in runtime data, unsafe rebuild inputs, dependency compromise, and accidental disclosure of local history.

The local app binds to `127.0.0.1` by default. The GitHub Pages version stores draws in the browser and does not provide accounts or server-side synchronization.
