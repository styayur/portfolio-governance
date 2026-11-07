#!/usr/bin/env python3
"""Classify a pull request as R0-R4 from its actual diff.

The PR is untrusted input. This script reads metadata and patches only; it never
imports, evaluates, or executes code from the pull request.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

DOC_EXT = {'.md', '.mdx', '.rst', '.txt', '.adoc'}
ASSET_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.pdf', '.woff', '.woff2'}
TEST_PATHS = ('test/', 'tests/', '__tests__/', 'spec/', '.github/workflows/test')
SECURITY_PATHS = (
    '.github/workflows/', '.github/actions/', '.github/dependabot.yml', '.github/renovate',
    'security', 'auth', 'credential', 'secret', 'token', 'permission', '.github/codeowners',
    'ruleset', 'signing', 'sign.', 'pull_request_target',
)
RELEASE_PATHS = ('release', 'packaging/', 'build/', 'scripts/build', 'publish', 'version')
PUBLIC_API_PATHS = (
    'api.py', 'openapi', 'swagger', 'schema.graphql', 'schema.json', 'src/api/',
    'src/lib.rs', 'src/main.rs', 'bindings/', 'migrations/', 'database/migration',
)
CONFIG_PATHS = ('config.', 'settings.', '.env', 'dockerfile', 'compose.yaml', 'compose.yml')
DEPENDENCY_MANIFESTS = {
    'package.json', 'pyproject.toml', 'cargo.toml', 'go.mod', 'pom.xml', 'build.gradle',
    'build.gradle.kts', 'gemfile', 'composer.json', 'requirements.txt', 'requirements-dev.txt',
}
LOCKFILES = {
    'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'cargo.lock', 'poetry.lock',
    'uv.lock', 'pipfile.lock', 'go.sum', 'composer.lock',
}
SECRET_PATH_PATTERNS = (
    r'(^|/)\.env($|\.)', r'(^|/)(id_rsa|id_ed25519)$', r'\.(pem|p12|pfx|key)$',
    r'(^|/)secrets?/', r'(^|/)credentials?/', r'(^|/)signing[^/]*$',
)


def run(args, input_text=None):
    proc = subprocess.run(args, input=input_text, text=True, capture_output=True)
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return proc.stdout


def api(path: str):
    return json.loads(run(['gh', 'api', path]))


def api_list(path: str):
    text = run(['gh', 'api', '--paginate', '--jq', '.[]', path])
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def any_path(path: str, needles) -> bool:
    value = path.casefold()
    return any(str(needle).casefold() in value for needle in needles)


def extension(path: str) -> str:
    name = Path(path).name.casefold()
    if name in {'.gitignore', '.gitattributes'}:
        return ''
    return Path(name).suffix


def is_test(path: str) -> bool:
    value = path.casefold()
    name = Path(value).name
    return any(value.startswith(prefix) or f'/{prefix}' in value for prefix in TEST_PATHS) or '.test.' in name or '.spec.' in name or name.endswith('_test.py')


def is_docs(path: str) -> bool:
    value = path.casefold()
    return extension(value) in DOC_EXT or value.startswith('docs/') or Path(value).name in {'readme', 'changelog', 'contributing', 'agents.md'}


def is_license(path: str) -> bool:
    return Path(path.casefold()).name in {'license', 'license.md', 'license.txt', 'copying', 'notice', 'notice.md'}


def parse_dependency_versions(patch: str):
    old, new = {}, {}
    for line in (patch or '').splitlines():
        if not line or line[:1] not in ('-', '+') or line.startswith(('---', '+++')):
            continue
        target = old if line.startswith('-') else new
        content = line[1:]
        patterns = [
            r'"([^"]+)"\s*:\s*"[~^>=< ]*v?(\d+)\.(\d+)\.(\d+)',
            r'^\s*([A-Za-z0-9_.-]+)\s*=\s*["\'][~^>=< ]*v?(\d+)\.(\d+)\.(\d+)',
            r'^\s*([A-Za-z0-9_.-]+)\s*==\s*v?(\d+)\.(\d+)\.(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                target[match.group(1).casefold()] = tuple(int(match.group(i)) for i in (2, 3, 4))
                break
    changes = []
    for name in sorted(set(old) & set(new)):
        before, after = old[name], new[name]
        if before != after:
            changes.append({'dependency': name, 'from': '.'.join(map(str, before)), 'to': '.'.join(map(str, after)), 'major': before[0] != after[0]})
    return changes


def classify(repo: str, pr_number: int):
    pr = api(f'repos/{repo}/pulls/{pr_number}')
    files = api_list(f'repos/{repo}/pulls/{pr_number}/files?per_page=100')
    paths = [f.get('filename', '') for f in files]
    churn = sum(int(f.get('additions', 0)) + int(f.get('deletions', 0)) for f in files)
    reasons = []
    dependency_changes = []
    for f in files:
        dependency_changes.extend(parse_dependency_versions(f.get('patch') or ''))
    majors = [d for d in dependency_changes if d['major']]

    if not paths:
        risk = 'R4'
        reasons.append('No changed files were returned; fail closed.')
    elif all(is_docs(p) or extension(p) in ASSET_EXT for p in paths) and not any(is_license(p) for p in paths):
        risk = 'R0'
        reasons.append('Only documentation or non-executable assets changed.')
    elif all(is_test(p) or is_docs(p) for p in paths):
        risk = 'R1'
        reasons.append('Changes are limited to tests or documentation.')
    else:
        risk = 'R2'
        reasons.append('Executable source or dependency changes require verification.')

    secret_paths = [p for p in paths if any(re.search(pattern, p.casefold()) for pattern in SECRET_PATH_PATTERNS)]
    workflow_paths = [p for p in paths if p.casefold().startswith('.github/workflows/') or p.casefold().startswith('.github/actions/')]
    security_paths = [p for p in paths if any_path(p, SECURITY_PATHS)]
    release_paths = [p for p in paths if any_path(p, RELEASE_PATHS)]
    api_paths = [p for p in paths if any_path(p, PUBLIC_API_PATHS)]
    config_paths = [p for p in paths if any_path(p, CONFIG_PATHS)]

    if secret_paths:
        risk = 'R4'
        reasons.append('Credential, key, signing, or secret-bearing paths changed: ' + ', '.join(secret_paths[:8]))
    if workflow_paths:
        risk = 'R4' if any('pull_request_target' in (f.get('patch') or '') for f in files if f.get('filename') in workflow_paths) else 'R3'
        reasons.append('GitHub Actions or repository policy workflow changed: ' + ', '.join(workflow_paths[:8]))
    if majors:
        risk = 'R3' if risk not in ('R4',) else risk
        reasons.append('Major dependency version change: ' + ', '.join(f"{d['dependency']} {d['from']}->{d['to']}" for d in majors[:8]))
    elif any(dependency_changes):
        risk = max(risk, 'R2', key=lambda x: {'R0':0,'R1':1,'R2':2,'R3':3,'R4':4}[x])
        reasons.append('Dependency manifest versions changed within compatible major lines.')
    lockfile_paths = [p for p in paths if Path(p).name.casefold() in LOCKFILES]
    if lockfile_paths and not dependency_changes:
        risk = max(risk, 'R2', key=lambda x: {'R0':0,'R1':1,'R2':2,'R3':3,'R4':4}[x])
        reasons.append('Lockfile changed without a reviewed manifest version change.')
    if api_paths:
        risk = 'R3' if risk != 'R4' else risk
        reasons.append('Public API, schema, or migration surface changed: ' + ', '.join(api_paths[:8]))
    if release_paths:
        risk = 'R3' if risk != 'R4' else risk
        reasons.append('Release, build, or packaging configuration changed: ' + ', '.join(release_paths[:8]))
    if config_paths:
        risk = 'R3' if risk != 'R4' else risk
        reasons.append('Runtime or security configuration changed: ' + ', '.join(config_paths[:8]))
    if len(files) > 100 or churn > 1000:
        risk = 'R4'
        reasons.append(f'Large change: {len(files)} files, {churn} changed lines.')
    elif len(files) > 50 or churn > 300:
        risk = 'R3' if risk not in ('R4',) else risk
        reasons.append(f'Review-scale change: {len(files)} files, {churn} changed lines.')

    context = {
        'repository': repo,
        'repositoryId': pr['base']['repo']['id'],
        'prNumber': pr_number,
        'title': pr.get('title'),
        'body': pr.get('body') or '',
        'author': (pr.get('user') or {}).get('login'),
        'state': pr.get('state'),
        'draft': bool(pr.get('draft')),
        'baseRef': pr['base']['ref'],
        'baseSha': pr['base']['sha'],
        'headRef': pr['head']['ref'],
        'headSha': pr['head']['sha'],
        'mergeable': pr.get('mergeable'),
        'mergeStateStatus': pr.get('mergeable_state'),
        'changedFileCount': len(files),
        'additions': sum(int(f.get('additions', 0)) for f in files),
        'deletions': sum(int(f.get('deletions', 0)) for f in files),
        'files': [
            {'filename': f.get('filename'), 'status': f.get('status'), 'additions': f.get('additions'),
             'deletions': f.get('deletions'), 'patch': f.get('patch') or ''}
            for f in files
        ],
    }
    risk_data = {
        'schemaVersion': 1,
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'repository': repo,
        'repositoryId': context['repositoryId'],
        'prNumber': pr_number,
        'baseSha': context['baseSha'],
        'headSha': context['headSha'],
        'draft': context['draft'],
        'risk': risk,
        'reasons': reasons,
        'dependencyChanges': dependency_changes,
        'counts': {'files': len(files), 'churn': churn, 'workflowFiles': len(workflow_paths), 'securitySensitiveFiles': len(security_paths)},
    }
    return context, risk_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    context, risk = classify(args.repo, args.pr)
    args.context.parent.mkdir(parents=True, exist_ok=True)
    args.context.write_text(json.dumps(context, ensure_ascii=False, indent=2) + '\n')
    args.output.write_text(json.dumps(risk, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'risk': risk['risk'], 'reasons': risk['reasons'], 'files': risk['counts']['files'], 'churn': risk['counts']['churn']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
