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

try:
    from evidence_matrix import diff_digest
except ModuleNotFoundError:  # package import from tests
    from scripts.evidence_matrix import diff_digest

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
GOVERNANCE_POLICY_PATHS = (
    '.github/workflows/reusable-portfolio-gate.yml', 'templates/caller-portfolio-gate.yml',
    'scripts/evidence_gate.py', 'scripts/evidence_matrix.py', 'scripts/risk_classify.py',
    'scripts/independent_review.py', 'scripts/ai_review_adapter.py', 'policy/risk-policy.json',
    'policy/evidence-matrix.v1.json', 'policy/rollout.json',
)
AUTH_PERMISSION_SEGMENTS = re.compile(
    r'(^|/)(auth|authentication|authorization|authn|authz|oauth|oidc|saml|jwt|session|sessions|permissions?|rbac|acl|iam|identity|credentials?|secrets?|tokens?|crypto|cryptography|signing|privilege|access_control|admin)(/|[._-]|$)', re.I
)
AUTH_PERMISSION_NAME_PREFIXES = (
    'auth', 'permission', 'credential', 'secret', 'session', 'jwt', 'oauth', 'oidc',
    'rbac', 'acl', 'privilege', 'sudo', 'admin', 'accesscontrol', 'access_control', 'access-control',
)
PRIVILEGE_CONTENT = re.compile(
    r'(\bset(?:e)?uid\b|\bset(?:e)?gid\b|\bsudo\b|\brunas\b|SeDebugPrivilege|SeImpersonatePrivilege|ImpersonateLoggedOnUser|CreateProcessAsUser|\bchmod\s+[0-7]{3,4}\b|\bchown\b|\bgrant\b.*\b(?:admin|owner|root)\b)', re.I
)
RISK_ORDER = {'R0': 0, 'R1': 1, 'R2': 2, 'R3': 3, 'R4': 4}


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


def is_security_sensitive(path: str) -> bool:
    if is_docs(path) or is_license(path):
        return False
    value = path.casefold().replace('\\', '/')
    stem = Path(value).stem
    return bool(AUTH_PERMISSION_SEGMENTS.search(value) or any(stem.startswith(prefix) or stem.endswith(prefix) for prefix in AUTH_PERMISSION_NAME_PREFIXES))


def is_governance_policy(path: str) -> bool:
    value = path.casefold().replace('\\', '/')
    return any(value == item or value.endswith('/' + item) for item in GOVERNANCE_POLICY_PATHS)


def _added_lines(files):
    result = []
    for f in files:
        path = f.get('filename') or ''
        for line in (f.get('patch') or '').splitlines():
            if line.startswith('+') and not line.startswith('+++'):
                result.append((path, line[1:]))
    return result


def classify_files(files):
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

    def raise_to(level):
        nonlocal risk
        if RISK_ORDER[level] > RISK_ORDER[risk]:
            risk = level

    secret_paths = [p for p in paths if any(re.search(pattern, p.casefold()) for pattern in SECRET_PATH_PATTERNS)]
    workflow_paths = [p for p in paths if p.casefold().startswith('.github/workflows/') or p.casefold().startswith('.github/actions/')]
    security_paths = [p for p in paths if is_security_sensitive(p)]
    governance_paths = [p for p in paths if is_governance_policy(p)]
    release_paths = [p for p in paths if any_path(p, RELEASE_PATHS)]
    api_paths = [p for p in paths if any_path(p, PUBLIC_API_PATHS)]
    config_paths = [p for p in paths if any_path(p, CONFIG_PATHS)]
    privilege_lines = [(path, line) for path, line in _added_lines(files) if PRIVILEGE_CONTENT.search(line)]

    if secret_paths:
        raise_to('R4')
        reasons.append('Credential, key, signing, or secret-bearing paths changed: ' + ', '.join(secret_paths[:8]))
    if governance_paths:
        raise_to('R4')
        reasons.append('Evidence Gate policy, review logic, or trusted-caller contract changed: ' + ', '.join(governance_paths[:8]))
    if security_paths:
        raise_to('R4')
        reasons.append('Authentication, authorization, privilege, or permission-sensitive code changed: ' + ', '.join(security_paths[:8]))
    if privilege_lines:
        raise_to('R4')
        reasons.append('Privilege-escalation or credential-handling code pattern added: ' + ', '.join(sorted({p for p, _ in privilege_lines})[:8]))
    if workflow_paths:
        raise_to('R4' if any('pull_request_target' in (f.get('patch') or '') for f in files if f.get('filename') in workflow_paths) else 'R3')
        reasons.append('GitHub Actions or repository policy workflow changed: ' + ', '.join(workflow_paths[:8]))
    if majors:
        raise_to('R3')
        reasons.append('Major dependency version change: ' + ', '.join(f"{d['dependency']} {d['from']}->{d['to']}" for d in majors[:8]))
    elif any(dependency_changes):
        raise_to('R2')
        reasons.append('Dependency manifest versions changed within compatible major lines.')
    lockfile_paths = [p for p in paths if Path(p).name.casefold() in LOCKFILES]
    if lockfile_paths and not dependency_changes:
        raise_to('R2')
        reasons.append('Lockfile changed without a reviewed manifest version change.')
    if api_paths:
        raise_to('R3')
        reasons.append('Public API, schema, or migration surface changed: ' + ', '.join(api_paths[:8]))
    if release_paths:
        raise_to('R3')
        reasons.append('Release, build, or packaging configuration changed: ' + ', '.join(release_paths[:8]))
    if config_paths:
        raise_to('R3')
        reasons.append('Runtime or security configuration changed: ' + ', '.join(config_paths[:8]))
    if len(files) > 100 or churn > 1000:
        raise_to('R4')
        reasons.append(f'Large change: {len(files)} files, {churn} changed lines.')
    elif len(files) > 50 or churn > 300:
        raise_to('R3')
        reasons.append(f'Review-scale change: {len(files)} files, {churn} changed lines.')

    return {
        'risk': risk,
        'reasons': reasons,
        'dependencyChanges': dependency_changes,
        'secretPaths': secret_paths,
        'securitySensitivePaths': security_paths,
        'governancePolicyPaths': governance_paths,
        'privilegeSignals': [line for _, line in privilege_lines],
        'counts': {'files': len(files), 'churn': churn, 'workflowFiles': len(workflow_paths), 'securitySensitiveFiles': len(security_paths)},
    }


def classify(repo: str, pr_number: int):
    pr = api(f'repos/{repo}/pulls/{pr_number}')
    files = api_list(f'repos/{repo}/pulls/{pr_number}/files?per_page=100')
    expected_count = pr.get('changed_files')
    if type(expected_count) is not int or not 0 < expected_count <= 3000 or len(files) != expected_count:
        raise ValueError('PR file coverage is incomplete or exceeds the GitHub 3000-file limit')
    result = classify_files(files)
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
        'expectedChangedFileCount': expected_count,
        'additions': sum(int(f.get('additions', 0)) for f in files),
        'deletions': sum(int(f.get('deletions', 0)) for f in files),
        'files': [
            {'filename': f.get('filename'), 'status': f.get('status'), 'additions': f.get('additions'),
             'deletions': f.get('deletions'), 'patch': f.get('patch') or '',
             'previous_filename': f.get('previous_filename')}
            for f in files
        ],
    }
    context['diffSha256'] = diff_digest(context['files'])
    risk_data = {
        'schemaVersion': 2,
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'repository': repo,
        'repositoryId': context['repositoryId'],
        'prNumber': pr_number,
        'baseSha': context['baseSha'],
        'headSha': context['headSha'],
        'diffSha256': context['diffSha256'],
        'draft': context['draft'],
        'risk': result['risk'],
        'reasons': result['reasons'],
        'dependencyChanges': result['dependencyChanges'],
        'signals': {
            'secretPaths': result['secretPaths'],
            'securitySensitivePaths': result['securitySensitivePaths'],
            'governancePolicyPaths': result['governancePolicyPaths'],
            'privilegeLines': result['privilegeSignals'],
        },
        'counts': result['counts'],
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
    try:
        from review_context import enrich_context
    except ModuleNotFoundError:
        from scripts.review_context import enrich_context
    context = enrich_context(context, risk)
    args.context.parent.mkdir(parents=True, exist_ok=True)
    args.context.write_text(json.dumps(context, ensure_ascii=False, indent=2) + '\n')
    args.output.write_text(json.dumps(risk, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'risk': risk['risk'], 'reasons': risk['reasons'], 'files': risk['counts']['files'], 'churn': risk['counts']['churn']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
