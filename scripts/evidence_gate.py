#!/usr/bin/env python3
"""Wait for exact-head checks, bind evidence and apply the merge policy."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

PENDING = {'QUEUED', 'IN_PROGRESS', 'PENDING', 'EXPECTED', 'WAITING', 'REQUESTED'}
FAILURE = {'FAILURE', 'CANCELLED', 'TIMED_OUT', 'ACTION_REQUIRED', 'STARTUP_FAILURE', 'STALE', 'ERROR'}
SKIP = {'SKIPPED', 'NEUTRAL'}
SECURITY_HINT = ('security', 'codeql', 'secret', 'audit', 'dependabot', 'trivy', 'osv', 'scan')
TEST_HINT = ('test', 'verify', 'ci', 'build', 'lint', 'regression')


def run(args):
    proc = subprocess.run(args, text=True, capture_output=True)
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return proc.stdout


def pr_view(repo, number):
    raw = run(['gh', 'pr', 'view', str(number), '-R', repo, '--json',
               'state,isDraft,mergeable,mergeStateStatus,headRefOid,baseRefOid,statusCheckRollup,url'])
    return json.loads(raw)


def normalize_checks(rollup):
    checks = []
    for item in rollup or []:
        typename = item.get('__typename')
        name = item.get('name') or item.get('context') or 'unknown'
        workflow = item.get('workflowName') or ''
        if typename == 'StatusContext':
            state = str(item.get('state') or '').upper()
            checks.append({'name': name, 'workflow': workflow, 'state': state, 'url': item.get('targetUrl'), 'typename': typename})
        else:
            status = str(item.get('status') or '').upper()
            conclusion = str(item.get('conclusion') or '').upper()
            state = conclusion if status == 'COMPLETED' else status
            checks.append({'name': name, 'workflow': workflow, 'state': state, 'url': item.get('detailsUrl'), 'typename': typename})
    return checks


def external_checks(checks):
    return [
        c for c in checks
        if not c['name'].startswith('Portfolio Evidence Gate')
        and c.get('workflow') != 'Portfolio Evidence Gate'
    ]


def evaluate_checks(checks, risk_level):
    pending = [c for c in checks if c['state'] in PENDING]
    failed = [c for c in checks if c['state'] in FAILURE]
    skipped = [c for c in checks if c['state'] in SKIP]
    successful = [c for c in checks if c['state'] == 'SUCCESS']
    security = [c for c in checks if any(word in (c['name'] + ' ' + c.get('workflow', '')).casefold() for word in SECURITY_HINT)]
    tests = [c for c in checks if any(word in (c['name'] + ' ' + c.get('workflow', '')).casefold() for word in TEST_HINT)]
    risky_skips = [
        c for c in skipped
        if any(word in (c['name'] + ' ' + c.get('workflow', '')).casefold() for word in TEST_HINT + SECURITY_HINT)
    ]
    if failed:
        test_status = 'FAIL'
    elif pending:
        test_status = 'PENDING'
    elif risk_level in {'R2', 'R3', 'R4'} and risky_skips:
        test_status = 'FAIL_SKIPPED_REQUIRED_WORK'
    elif successful:
        test_status = 'PASS'
    else:
        test_status = 'NOT_VERIFIED'
    if any(c['state'] in FAILURE for c in security):
        security_status = 'FAIL'
    elif security and all(c['state'] == 'SUCCESS' for c in security):
        security_status = 'PASS'
    else:
        security_status = 'SECRET_SCAN_ONLY'
    return {
        'testStatus': test_status,
        'securityStatus': security_status,
        'pending': pending,
        'failed': failed,
        'skipped': skipped,
        'riskySkipped': risky_skips,
        'successful': successful,
        'testChecks': tests,
        'securityChecks': security,
    }


def wait_for_checks(repo, number, head_sha, risk_level, timeout, poll):
    started = time.time()
    while True:
        pr = pr_view(repo, number)
        if pr.get('headRefOid') != head_sha:
            return pr, None, 'HEAD_CHANGED'
        checks = external_checks(normalize_checks(pr.get('statusCheckRollup')))
        status = evaluate_checks(checks, risk_level)
        has_pending = bool(status['pending'])
        if not has_pending:
            return pr, status, None
        if time.time() - started >= timeout:
            return pr, status, 'TIMEOUT'
        time.sleep(poll)


def upsert_comment(repo, number, body):
    marker = '<!-- portfolio-evidence-gate -->'
    full = marker + '\n' + body
    try:
        text = run(['gh', 'api', '--paginate', '--jq', '.[]', f'repos/{repo}/issues/{number}/comments?per_page=100'])
        comments = [json.loads(line) for line in text.splitlines() if line.strip()]
    except Exception:
        comments = []
    for comment in comments:
        if marker in (comment.get('body') or ''):
            run(['gh', 'api', '-X', 'PATCH', f'repos/{repo}/issues/comments/{comment["id"]}', '-f', f'body={full}'])
            return
    run(['gh', 'api', '-X', 'POST', f'repos/{repo}/issues/{number}/comments', '-f', f'body={full}'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--head-sha', required=True)
    parser.add_argument('--risk', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', default=os.environ.get('GITHUB_RUN_ID', ''))
    parser.add_argument('--timeout', type=int, default=int(os.environ.get('GATE_TIMEOUT_SECONDS', '2700')))
    parser.add_argument('--poll', type=int, default=int(os.environ.get('GATE_POLL_SECONDS', '15')))
    parser.add_argument('--enable-auto-merge', action='store_true')
    parser.add_argument('--comment', action='store_true')
    args = parser.parse_args()

    risk = json.loads(args.risk.read_text())
    review = json.loads(args.review.read_text())
    if risk.get('headSha') != args.head_sha or review.get('headSha') != args.head_sha:
        raise SystemExit('risk/review evidence does not match the requested head SHA')

    pr, status, wait_error = wait_for_checks(args.repo, args.pr, args.head_sha, risk['risk'], args.timeout, args.poll)
    if pr.get('headRefOid') != args.head_sha:
        decision = 'FAILED_HEAD_CHANGED'
    elif wait_error == 'TIMEOUT':
        decision = 'FAILED_CHECK_TIMEOUT'
    elif review.get('decision') == 'BLOCK':
        decision = 'FAILED_REVIEW_BLOCK'
    elif status is None:
        decision = 'FAILED_UNKNOWN_CHECK_STATE'
    elif status['testStatus'].startswith('FAIL'):
        decision = 'FAILED_CHECKS'
    elif status['testStatus'] == 'PENDING':
        decision = 'FAILED_CHECK_TIMEOUT'
    elif risk['risk'] in {'R1', 'R2', 'R3', 'R4'} and not status['successful'] and not status['skipped']:
        decision = 'FAILED_MISSING_CHECKS'
    elif pr.get('isDraft'):
        decision = 'WAITING_FOR_READY'
    elif risk['risk'] in {'R3', 'R4'} or review.get('decision') == 'MANUAL_REVIEW_REQUIRED':
        decision = 'MANUAL_REVIEW_REQUIRED'
    else:
        decision = 'AUTO_MERGE_ELIGIBLE'

    auto_merge_enabled = False
    if decision == 'AUTO_MERGE_ELIGIBLE' and args.enable_auto_merge:
        current = pr_view(args.repo, args.pr)
        if current.get('headRefOid') != args.head_sha:
            decision = 'FAILED_HEAD_CHANGED'
        elif current.get('state') == 'OPEN':
            run(['gh', 'pr', 'merge', str(args.pr), '-R', args.repo, '--squash', '--auto', '--match-head-commit', args.head_sha])
            auto_merge_enabled = True
            decision = 'AUTO_MERGE_ENABLED'

    checks = status or {}
    record = {
        'schemaVersion': 1,
        'subject': f'{args.repo}#{args.pr}',
        'repository': args.repo,
        'repositoryId': risk.get('repositoryId'),
        'prNumber': args.pr,
        'baseSha': risk.get('baseSha'),
        'headSha': args.head_sha,
        'workflowRunId': args.run_id,
        'workflowRunUrl': f'https://github.com/{args.repo}/actions/runs/{args.run_id}' if args.run_id else None,
        'tool': {'name': 'Portfolio Evidence Gate', 'version': '1.0.0'},
        'risk': risk['risk'],
        'riskReasons': risk.get('reasons'),
        'testStatus': checks.get('testStatus', 'NOT_VERIFIED'),
        'securityStatus': checks.get('securityStatus', 'NOT_VERIFIED'),
        'reviewDecision': review.get('decision'),
        'reviewBlockers': review.get('blockers', []),
        'manualReviewReasons': review.get('manualReviewReasons', []),
        'reviewWarnings': review.get('warnings', []),
        'evidence': [
            {'name': c['name'], 'workflow': c.get('workflow'), 'state': c['state'], 'url': c.get('url')}
            for c in checks.get('successful', []) + checks.get('failed', []) + checks.get('skipped', []) + checks.get('pending', [])
        ],
        'decision': decision,
        'autoMergeEnabled': auto_merge_enabled,
        'verifiedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'residualRisk': 'R3/R4 changes require an explicit maintainer merge decision; no merge was requested automatically.'
                       if decision == 'MANUAL_REVIEW_REQUIRED' else 'Evidence is scoped to this repository, PR and exact head SHA.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')

    if args.comment:
        body = (
            f'### Portfolio evidence gate\n\n'
            f'- Risk: **{record["risk"]}**\n'
            f'- Head: `{record["headSha"]}`\n'
            f'- Tests: **{record["testStatus"]}**\n'
            f'- Security: **{record["securityStatus"]}**\n'
            f'- Review: **{record["reviewDecision"]}**\n'
            f'- Decision: **{record["decision"]}**\n'
            f'- Evidence run: {record["workflowRunUrl"] or "not available"}\n'
        )
        if record['reviewBlockers']:
            body += '\nBlocking review findings:\n' + '\n'.join(f'- {x}' for x in record['reviewBlockers']) + '\n'
        if record['manualReviewReasons']:
            body += '\nManual review reasons:\n' + '\n'.join(f'- {x}' for x in record['manualReviewReasons']) + '\n'
        try:
            upsert_comment(args.repo, args.pr, body)
        except Exception as exc:
            record['commentError'] = str(exc)
            args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')

    print(json.dumps({k: record[k] for k in ('risk','testStatus','securityStatus','reviewDecision','decision','autoMergeEnabled')}, ensure_ascii=False))
    if record['decision'].startswith('FAILED'):
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
