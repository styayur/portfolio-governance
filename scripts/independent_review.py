#!/usr/bin/env python3
"""Independent diff review and auto-merge policy evaluation.

This reviewer is separate from the coding agent. It treats the pull request as
untrusted text and never executes code, workflow steps, or instructions from it.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

try:
    from evidence_matrix import diff_digest
except ModuleNotFoundError:  # package import from tests
    from scripts.evidence_matrix import diff_digest

SECRET_PATTERNS = [
    ('private-key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
    ('github-token', re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b')),
    ('openai-style-key', re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b')),
    ('aws-access-key', re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ('slack-token', re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{10,}\b')),
]
UNPINNED_ACTION = re.compile(r'^\+\s*uses:\s*([^\s@]+)@(v?\d+(?:\.\d+)*|main|master|latest)\s*(?:#.*)?$', re.M)
CODE_EXT = {'.py', '.js', '.jsx', '.ts', '.tsx', '.rs', '.go', '.java', '.kt', '.cs', '.c', '.cc', '.cpp', '.h', '.hpp', '.ps1', '.psm1', '.sh', '.rb', '.php', '.swift', '.dart', '.lua'}
TEST_HINT = re.compile(r'(^|/)(tests?|__tests__|spec)/|\.(test|spec)\.|(^|/)test_[^/]+$')
ACTION_RUN_URL = re.compile(r'https://github\.com/[^/\s]+/[^/\s]+/actions/runs/\d+')
CLAIM_WORDS = re.compile(r'\b(pass|passed|verified|accurate|accuracy)\b', re.I)


def is_test(path: str) -> bool:
    return bool(TEST_HINT.search(path or ''))


def added_lines(files):
    values = []
    for f in files:
        for line in (f.get('reviewPatch') or f.get('patch') or '').splitlines():
            if line.startswith('+') and not line.startswith('+++'):
                values.append((f.get('filename'), line[1:]))
    return values


def inspect_workflows(files):
    blockers = []
    warnings = []
    for f in files:
        path = (f.get('filename') or '').casefold()
        if not path.startswith('.github/workflows/'):
            continue
        patch = f.get('reviewPatch') or f.get('patch') or ''
        added = '\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
        if 'permissions: write-all' in added:
            blockers.append(f'{f.get("filename")}: grants write-all permissions')
        if 'pull_request_target' in added:
            # A SHA supplied to a pinned reusable evaluator is data, not checkout.
            # Retain a block for an actual checkout whose ref is the PR head.
            head_ref = re.search(r'(?m)^\s*ref:\s*.*(?:github\.event\.pull_request\.head\.(?:sha|ref)|refs/pull/)', added)
            if re.search(r'uses:\s*["\']?actions/checkout@', patch) and head_ref:
                blockers.append(f'{f.get("filename")}: pull_request_target appears to check out untrusted head content')
            if 'secrets: inherit' in added:
                warnings.append(f'{f.get("filename")}: pull_request_target inherits all secrets')
        unpinned = sorted(set(m.group(1) for m in UNPINNED_ACTION.finditer(added)))
        if unpinned:
            warnings.append(f'{f.get("filename")}: unpinned external actions: {", ".join(unpinned[:8])}')
    return blockers, warnings


def review(context: dict, risk: dict):
    blockers = []
    warnings = []
    manual = []
    body = context.get('body') or ''
    files = context.get('files') or []
    risk_level = risk.get('risk', 'R4')
    if context.get('reviewInputComplete') is False:
        manual.append('Complete immutable review input could not be collected; source coverage is not verified.')

    if len(body.strip()) < 20:
        blockers.append('PR description is missing or too short to establish intent and verification scope.')

    for filename, line in added_lines(files):
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                blockers.append(f'{filename}: possible {name} added in the diff')

    workflow_blockers, workflow_warnings = inspect_workflows(files)
    blockers.extend(workflow_blockers)
    warnings.extend(workflow_warnings)

    license_files = [f.get('filename') for f in files if Path(f.get('filename') or '').name.casefold() in {'license', 'license.md', 'license.txt', 'copying', 'notice', 'notice.md'}]
    if license_files:
        manual.append('License or NOTICE files changed: a human must confirm terms, provenance, and compatibility.')

    if risk_level in {'R3', 'R4'}:
        manual.append(f'{risk_level} changes are outside the automatic-merge policy.')

    source_files = [f.get('filename') for f in files if Path(f.get('filename') or '').suffix.casefold() in CODE_EXT]
    tests_changed = [p for p in (f.get('filename') for f in files) if is_test(p or '')]
    if source_files and not tests_changed:
        warnings.append('Executable source changed without a test-file change; existing CI may still cover it, but this is not independently established.')
    if len(source_files) >= 20 and not any('bench' in (p or '').casefold() or 'perf' in (p or '').casefold() for p in (f.get('filename') for f in files)):
        warnings.append('Large source change has no benchmark/performance artifact in the diff.')
    if CLAIM_WORDS.search(body) and not ACTION_RUN_URL.search(body) and risk_level in {'R2', 'R3', 'R4'}:
        warnings.append('PR description makes a pass/accuracy claim without an exact GitHub Actions run reference.')

    if blockers:
        decision = 'BLOCK'
    elif manual:
        decision = 'MANUAL_REVIEW_REQUIRED'
    else:
        decision = 'AUTO_MERGE_CANDIDATE'

    return {
        'schemaVersion': 2,
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'repository': context.get('repository'),
        'repositoryId': context.get('repositoryId'),
        'prNumber': context.get('prNumber'),
        'baseSha': context.get('baseSha'),
        'headSha': context.get('headSha'),
        'risk': risk_level,
        'reviewerType': 'STATIC_POLICY',
        'diffSha256': risk.get('diffSha256') or diff_digest(files),
        'aiReviewRequired': risk_level in {'R2', 'R3', 'R4'},
        'decision': decision,
        'blockers': sorted(set(blockers)),
        'manualReviewReasons': sorted(set(manual)),
        'warnings': sorted(set(warnings)),
        'checks': {
            'requirementDiffMatch': 'NOT_AUTOMATED' if len(body.strip()) >= 20 else 'FAIL',
            'stableInterface': 'MANUAL_REVIEW' if risk_level in {'R3', 'R4'} else 'NO_PUBLIC_API_SIGNAL',
            'securityPrivacy': 'FAIL' if any('possible ' in x for x in blockers) or workflow_blockers else 'PASS_WITH_LIMITATIONS',
            'tests': 'PRESENT' if tests_changed else ('MISSING_TEST_DIFF' if source_files else 'NOT_APPLICABLE'),
            'evidenceFreshness': 'WARN' if any('exact GitHub Actions' in x for x in warnings) else 'NO_STALE_CLAIM_SIGNAL',
            'license': 'MANUAL_REVIEW' if license_files else 'NO_LICENSE_CHANGE',
            'performance': 'WARN' if any('benchmark' in x for x in warnings) else 'NO_REGRESSION_SIGNAL',
        },
        'trustBoundary': 'PR text and diff were inspected as untrusted data; no PR code or embedded instruction was executed.',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--risk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    context = json.loads(args.context.read_text())
    risk = json.loads(args.risk.read_text())
    if context.get('headSha') != risk.get('headSha'):
        raise SystemExit('context/risk head SHA mismatch')
    result = review(context, risk)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'risk': result['risk'], 'decision': result['decision'], 'blockers': result['blockers'], 'manualReviewReasons': result['manualReviewReasons'], 'warnings': result['warnings']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
