# Security

Report vulnerabilities privately using the repository's GitHub private vulnerability reporting when enabled. If unavailable, open an issue requesting a private contact without publishing exploit details, keys or private browsing content. The supported line for this alpha is `0.2.0-alpha.1` in Chromium.

## Trust boundaries

- Provider keys and custom headers are stored locally without encryption and are available only to trusted extension pages and the service worker.
- Content scripts receive public language/display/gesture settings without provider definitions or secrets.
- The service worker validates extension identity, top-frame origin, message type and bounded payloads.
- The translation port streams plain-text results only.
- Storage access is restricted to trusted extension contexts.
- Native bookmark permission is optional and requested only through an explicit user action.

## Translation

Built-in translation is on demand. Do not import untrusted configuration without reviewing destinations, headers, actions and rules. Page segments and bounded page context are sent only to configured providers after the user requests translation. HTTPS is required except loopback HTTP. Requests omit browser credentials and reject redirects; response size is bounded.

Translation output and provider/model markup are rendered as text. A model can return incorrect or malicious-looking text, but it is not executed as HTML.

## Collections

Collection data is local until explicitly exported. JSON and Markdown exports omit provider credentials and custom headers. Text Fragments and source URLs are validated as HTTP(S). Imports are bounded and validated.

No account, cloud sync, telemetry, remote code or page-history service is included.

## Bookmarks

Ogleans never deletes or overwrites existing browser bookmarks. Native export creates a configured folder when needed and records bookmark IDs without replacing the richer Ogleans collection. HTML bookmark export is available without bookmark permission.

## Vulnerability handling

Do not submit API keys, personal browsing content, private page exports or paid-service fixtures. Run:

```sh
pnpm audit --audit-level high
pnpm check
```

Provider services and third-party dependencies retain their own security and maintenance responsibilities.
