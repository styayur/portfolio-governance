# Security Policy

## Supported versions

Security fixes are applied to the latest published TinyTTS release. Older portable builds may not receive backports.

## Report privately

Do not open a public issue for a vulnerability. Use GitHub's private vulnerability reporting:

https://github.com/styayur/TinyTTS/security/advisories/new

Include the affected version, Windows version, reproduction steps, impact, and any proof-of-concept details needed to verify the report. Remove personal text and unrelated local data.

## Scope

Relevant areas include unsafe file handling, clipboard/hotkey behaviour, unexpected network access, updater or release integrity, memory-safety defects in TinyTTS, and incorrect handling of attacker-controlled model or configuration files.

TinyTTS is designed to be local-only. Reports showing text being transmitted, hidden network activity, or model/config files escaping their intended directories are especially important.

## Disclosure

Please allow maintainers time to reproduce and fix the issue before public disclosure. We will coordinate a release and credit reporters who want acknowledgement. This project does not promise a response-time SLA.
