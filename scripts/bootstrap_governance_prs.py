#!/usr/bin/env python3
"""Create one idempotent governance-baseline PR per public repository."""
from __future__ import annotations

import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import render_agents

CENTRAL_SHA = 'd34be191d8578b891a1db2c54308d154520389e6'
WORK = Path.home() / 'portfolio-work' / 'repos'
BRANCH = 'codex/portfolio-governance-baseline'
INVENTORY = ROOT / 'evidence/baseline/portfolio-inventory.json'

SECURITY_DOCS = {
'styayur': '''# Security Policy

## Scope

This repository contains the public profile, portfolio metadata and governance documentation for the `styayur` account. It has no hosted service or account system of its own.

## Supported version

Security fixes target the current `main` branch and the latest reviewed portfolio automation. Historical audit evidence is retained as-is.

## Report privately

Use GitHub private vulnerability reporting:

https://github.com/styayur/styayur/security/advisories/new

Do not post tokens, captured sessions, private repository content, personal files, or account data publicly. Include the affected file/commit, impact, and a synthetic reproduction.

## Data boundary

Public audit output must contain public repositories only. Never add credentials, private `styayur/site` content, real user sessions or production secrets to this repository.

No response-time SLA or dedicated security email is promised.
''',
'styayur.github.io': '''# Security Policy

## Scope

This repository is a minimal GitHub Pages redirect and URL-compatibility entry for `styayur.co.uk`. It is not the production website source and has no accounts, analytics backend or application data store.

## Supported version

Only the currently deployed `main` branch is supported. Historical redirects remain for compatibility.

## Report privately

For redirect injection, host allowlist bypass, script injection or deployment supply-chain issues, use:

https://github.com/styayur/styayur.github.io/security/advisories/new

For non-sensitive broken redirects, open an issue with the complete URL and expected destination. Do not include private query values, credentials or personal data in public reports.

## Boundary

The destination origin is fixed. URL parameters must not select an arbitrary host. No security-response SLA or dedicated security email is promised.
''',
'publishing-workbench': '''# Security Policy

## Supported versions

Security fixes target the current `main` branch and the latest published prerelease line. v0.2.x is an alpha/preview line, not a stable-support promise.

## Report privately

Use GitHub private vulnerability reporting:

https://github.com/styayur/publishing-workbench/security/advisories/new

Do not include API tokens, application passwords, CMS content, private repository data, local databases, unpublished drafts, or full machine paths in a public issue.

## Security-sensitive areas

Relevant reports include credential handling, local SQLite/journal recovery, path traversal, import/export file access, Tauri IPC boundaries, remote CMS/Git adapter authorization, accidental force-push, asset upload, URL validation, and recovery logic that could duplicate or overwrite remote content.

## Operating boundary

The application is local-first. Remote writes occur only against explicitly configured adapters and require user action. Browser preview does not prove a remote publish succeeded. A timeout or missing receipt can mean the remote write occurred; use reconciliation rather than assuming rollback.

No automatic rollback, exactly-once guarantee across arbitrary remote APIs, stable support SLA, or security email is claimed.
''',
'ripple': '''# Security Policy

## Supported versions

Security fixes target the current `main` branch and the latest published Ripple release.

## Report privately

Use GitHub private vulnerability reporting:

https://github.com/styayur/ripple/security/advisories/new

Do not attach real vault notes, frontmatter, tags, Canvas files, paths, screenshots containing private content, or other users' plugin settings.

## Security-sensitive areas

Relevant reports include unexpected network activity, remote code loading, bundle compromise, unsafe Obsidian API use, body-index overreach, graph/renderer crashes that corrupt workspace state, and accidental writes to user notes or other plugins' settings.

## Data boundary

Ripple is designed to operate locally with no accounts, telemetry, advertising, remote models or CDN assets. Body indexing is opt-in and bounded. Obsidian's own update and network behavior is outside this project's boundary.

No security-response SLA or dedicated security email is promised.
''',
}

REPAIRS = {
'calligra': [('https://github.com/styayur/calligraphy-studio/security/advisories/new', 'https://github.com/styayur/calligra/security/advisories/new')],
'whinset': [('The latest public prerelease is expected to be `v2.0.0-rc.1` until final v2 certification.', 'The latest public prerelease is `v2.0.0-rc.2`; final v2 certification remains pending. Historical RC.1 assets remain immutable.')],
}


def run(args, cwd=None):
    p = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(f"{' '.join(args)}\n{(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def write_lf(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace('\r\n', '\n').rstrip() + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only')
    parser.add_argument('--open-prs', action='store_true')
    args = parser.parse_args()
    inventory = json.loads(INVENTORY.read_text())
    template = (ROOT / 'templates/caller-portfolio-gate.yml').read_text().replace('PINNED_CENTRAL_SHA', CENTRAL_SHA)
    selected = set(args.only.split(',')) if args.only else None
    results = []
    for repo in inventory['repositories']:
        full = repo['full_name']; name = repo['name']
        if full == 'styayur/site' or full == 'styayur/portfolio-governance':
            continue
        if selected and name not in selected:
            continue
        path = WORK / name
        if not (path / '.git').exists():
            results.append({'repository': full, 'status': 'SKIPPED', 'reason': 'clone missing'})
            continue
        try:
            run(['git', 'fetch', 'origin', 'main', '--quiet'], cwd=path)
            run(['git', 'checkout', '-B', 'main', 'origin/main'], cwd=path)
            run(['git', 'reset', '--hard', 'origin/main'], cwd=path)
            if run(['git', 'status', '--porcelain'], cwd=path):
                raise RuntimeError('working tree is not clean')
            remote_branch = run(['git', 'ls-remote', '--heads', 'origin', BRANCH], cwd=path)
            if remote_branch:
                results.append({'repository': full, 'status': 'SKIPPED', 'reason': 'baseline branch already exists'})
                continue
            run(['git', 'checkout', '-B', BRANCH], cwd=path)
            changed = []
            agents = path / 'AGENTS.md'
            if not agents.exists():
                write_lf(agents, render_agents.render(repo, path)); changed.append('AGENTS.md')
            gate = path / '.github/workflows/portfolio-gate.yml'
            if not gate.exists():
                write_lf(gate, template); changed.append('.github/workflows/portfolio-gate.yml')
            security = path / 'SECURITY.md'
            if not security.exists():
                if name not in SECURITY_DOCS:
                    raise RuntimeError(f'no security policy template for {name}')
                write_lf(security, SECURITY_DOCS[name]); changed.append('SECURITY.md')
            elif name in REPAIRS:
                text = security.read_text(encoding='utf-8')
                original = text
                for old, new in REPAIRS[name]:
                    text = text.replace(old, new)
                if text != original:
                    write_lf(security, text); changed.append('SECURITY.md')
            if not changed:
                results.append({'repository': full, 'status': 'SKIPPED', 'reason': 'already current'})
                continue
            run(['git', 'add', *changed], cwd=path)
            run(['git', 'diff', '--cached', '--check'], cwd=path)
            run(['git', 'commit', '-m', 'docs: install portfolio governance baseline'], cwd=path)
            run(['git', 'push', '-u', 'origin', BRANCH], cwd=path)
            record = {'repository': full, 'status': 'PUSHED', 'branch': BRANCH, 'changed': changed}
            if args.open_prs:
                body = ('Adds the public-repository governance baseline: repository-specific AGENTS.md, a reusable evidence-gate caller pinned to the reviewed portfolio-governance commit, and security-policy/link corrections where needed.\n\n'
                        'No release, tag, asset or signing identity is changed. Platform-specific tests remain on native runners. This workflow-related change is R3 and is not intended for automatic merge under the current policy.\n\n'
                        'Tracked centrally in styayur/portfolio-governance.')
                url = run(['gh', 'pr', 'create', '--repo', full, '--base', 'main', '--head', BRANCH,
                           '--title', 'docs: install portfolio governance baseline', '--body', body], cwd=path)
                record['pullRequest'] = url
                try:
                    run(['gh', 'pr', 'edit', url, '--add-label', 'type:maintenance'], cwd=path)
                except Exception:
                    pass
            results.append(record)
            print(full, record['status'], changed, record.get('pullRequest', ''), flush=True)
        except Exception as exc:
            results.append({'repository': full, 'status': 'BLOCKED', 'reason': str(exc)})
            print(full, 'BLOCKED', str(exc), flush=True)
    out = ROOT / 'evidence/baseline/governance-bootstrap-prs.json'
    existing = []
    if out.exists():
        try: existing = json.loads(out.read_text()).get('records', [])
        except Exception: existing = []
    by_repo = {item['repository']: item for item in existing}
    for item in results: by_repo[item['repository']] = item
    out.write_text(json.dumps({'centralSha': CENTRAL_SHA, 'records': sorted(by_repo.values(), key=lambda x: x['repository'])}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'records': len(results), 'pushed': sum(r['status']=='PUSHED' for r in results), 'blocked': sum(r['status']=='BLOCKED' for r in results)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
