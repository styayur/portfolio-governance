# Security model and limits

The native app owns a dedicated Vault directory under its application data directory. VaultStore refuses to adopt an existing nonempty unmanaged directory. Path traversal, symlinks/reparse points and active image formats are rejected. Clear shows note/attachment/index counts, blocks dirty edits, fingerprints the current managed data and requires a separate confirmation. Remote repositories and external vaults are not deletion targets.

These checks defend against accidental misconfiguration and malicious input. They do not constitute a race-free filesystem sandbox against a local attacker mutating directory entries between checks and use. A confirmed clear durably records intent, isolates managed directories, and resumes that same clear after restart. RPC rejects new writes while a failed clear is pending. Its interruption checkpoints are tested; power-loss and hostile concurrent filesystem races still require deeper native qualification. This remains release-blocking until the required safety acceptance is complete.

The WebView loads local resources with CSP: no remote scripts/frames/objects, no arbitrary HTML execution. Links are intercepted, native RPC is versioned/allowlisted and validated; exceptions do not disclose private paths. Imported HTML is preserved read-only. No arbitrary JS plugins are accepted. Official plugin capabilities are checked in TypeScript and the native packaged-plugin route.

RPC cancellation is local cancellation of waiting, not rollback. Optimistic revision/hash checks reject stale document writes, including sidecar-only modifications. Long-document transport serializes full Markdown; the acceptance report records observed timings and their scope. Background saves remain best effort. Emulator process restart, activity recreation and background/foreground restoration have development-probe evidence; this does not establish physical-device behavior or guarantee unsaved edits survive arbitrary process death.

Document save calls allow 60 seconds for acknowledgement. A real emulator probe received a successful save response after 15.3 seconds, beyond the former generic 10-second deadline. The longer write-specific deadline keeps that valid acknowledgement in the writer queue; it does not retry an uncertain write or weaken revision checks. If the deadline still expires, reload before retrying because the native operation may already have committed.

Native image/Markdown pickers run on the UI thread, cap input sizes, and return validated data through narrow RPC methods. Windows clipboard bitmaps are decoded and re-encoded as PNG. The browser development host retains HTML file selection. A native picker cancellation is not an import failure; errors are surfaced without silently discarding the editor buffer.

Security overrides are exact: KaTeX <0.18.2 -> 0.18.2 (GHSA-238p-pmpm-9mq7); minimatch <11.0.1 -> 11.0.1 (GHSA-g3hv-75wg-m249). They are recorded in pnpm-workspace.yaml, not hidden audit exceptions. Run npm/NuGet audits and regression tests after any update. Scans do not prove absence of every vulnerability.

Android resolves the OS-provided private application base before checking vault paths. Only this trusted native base terminates ancestor traversal: links/reparse points in the managed vault and all owned descendants remain rejected. A dedicated regression test checks that the exception cannot bypass an attachment junction or adopt an unrelated base.

Permanent Android signing credentials are stored outside the repository, using Windows-account DPAPI protection and restricted dedicated directories. They are not application/vault encryption. No remote-sync token is used. E2EE and encrypted vaults are future work. See root SECURITY.md for reporting.
