<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Security reports

The native palette never elevates privileges or bypasses UIPI. It validates the
captured window identity, integrity and foreground before UTF-16 input dispatch;
Windows cannot guarantee atomic foreground ownership/target acceptance. Copy
explicitly replaces clipboard formats; Insert never changes them and no silent
clipboard paste is implemented. No telemetry, account or global text capture is
added. See [input and configuration boundaries](docs/palette.md).

Treat local config/catalog changes as input: schemas, sizes, scalar lists and
language/source references are validated. Corrupt config is preserved; unknown
future schemas are not overwritten. Studio remains a loopback-only service with
Host/Origin checks, not an authenticated public server. It may be launched only
explicitly from the palette. Versioned dependency notices and `cargo audit`
checks include build tools; a known-vulnerable build dependency is not dismissed
merely because the executable is offline. Native model ABI compatibility and
upstream binary security still need separate review.

Language mapping adds strict typed requests and validated embedded source/rule
registries; input/context and candidate/output limits are separate. It performs
no runtime rule download, shell invocation or implicit scheme fallback. The
optional eSpeak mapping adapter passes literal arguments, appends stdin LF,
bounds both output pipes and terminates/reaps after 8 seconds. ESPEAK_NG/PATH
overrides are trusted local program choices; their runtime version is unverified.
Host/Origin, body bounds and CSP also cover the mapping API. Text and sources are
rendered as text, never injected HTML. Mapping output is not proof of phonology
or synthesis compatibility; only eligible English IPA is sent to the speech
editor. Native mapping workers do not send global input; Palette only fills the
composition, and Insert retains its existing explicit target guards.

Send vulnerability reports privately to [yurstya@gmail.com](mailto:yurstya@gmail.com), the maintainer's published contact. GitHub private vulnerability reporting is not currently enabled for this repository. Do not publish exploit details, personal paths, secrets, voice recordings or unpublished content in a public issue.

Include the affected version/commit, platform, backend, minimal reproduction and expected impact. Share only the data needed to reproduce the issue. Response is best effort; no response-time guarantee or mature security-support period is promised for this MVP.

The HTTP UI is a loopback-only local service with Host/Origin checks, not a public multi-user service. Native model/runtime files are trusted inputs and can crash inference when damaged or mismatched. Use matching published assets, verify their checksums and keep native DLLs together. Stop halts playback, not an in-flight native inference. See the [current limitations](README.md#known-limits-and-next-work).
