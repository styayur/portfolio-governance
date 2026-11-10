#!/usr/bin/env python3
"""Bind PR evidence to exact SHAs and apply the v0.2 merge policy."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

try:
    from evidence_matrix import evaluate as evaluate_matrix
    from evidence_matrix import load_matrix, load_rollout
except ModuleNotFoundError:  # package import from tests
    from scripts.evidence_matrix import evaluate as evaluate_matrix
    from scripts.evidence_matrix import load_matrix, load_rollout

FAILURE = {'FAILURE', 'CANCELLED', 'TIMED_OUT', 'ACTION_REQUIRED', 'STARTUP_FAILURE', 'STALE', 'ERROR'}
PENDING = {'QUEUED', 'IN_PROGRESS', 'PENDING', 'EXPECTED', 'WAITING', 'REQUESTED'}
GATE_WORKFLOW = 'Portfolio Evidence Gate'


def run(args, input_text=None):
    proc = subprocess.run(args, input=input_text, text=True, capture_output=True)
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return proc.stdout


def graphql(query, variables):
    raw = run(['gh', 'api', 'graphql', '--input', '-'], json.dumps({'query': query, 'variables': variables}))
    data = json.loads(raw)
    if data.get('errors'):
        raise RuntimeError(json.dumps(data['errors'], ensure_ascii=False))
    return data['data']


PR_QUERY = '''query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      number title state isDraft mergeable mergeStateStatus headRefOid baseRefOid url
      labels(first:50){nodes{name}}
      statusCheckRollup{contexts(first:100){
        pageInfo{hasNextPage}
        nodes{
          __typename
          ... on CheckRun{name status conclusion detailsUrl startedAt completedAt
            checkSuite{commit{oid} app{id slug name} workflowRun{databaseId workflow{name}}}}
          ... on StatusContext{context state targetUrl createdAt creator{login}}
        }
      }}
    }
  }
}'''


def fetch_pr(repo: str, number: int) -> dict:
    owner, name = repo.split('/', 1)
    data = graphql(PR_QUERY, {'owner': owner, 'name': name, 'number': number})['repository']['pullRequest']
    contexts = ((data.get('statusCheckRollup') or {}).get('contexts') or {})
    nodes = contexts.get('nodes') or []
    checks = []
    for node in nodes:
        typename = node.get('__typename')
        if typename == 'CheckRun':
            suite = node.get('checkSuite') or {}
            app = suite.get('app') or {}
            run_info = suite.get('workflowRun') or {}
            workflow = (run_info.get('workflow') or {}).get('name') or ''
            checks.append({
                'typename': 'CheckRun', 'name': node.get('name'), 'workflow': workflow,
                'status': node.get('status'), 'conclusion': node.get('conclusion'),
                'detailsUrl': node.get('detailsUrl'), 'headSha': (suite.get('commit') or {}).get('oid'),
                'appSlug': app.get('slug'), 'appName': app.get('name'), 'appNodeId': app.get('id'),
                'workflowRunId': run_info.get('databaseId'),
            })
        elif typename == 'StatusContext':
            checks.append({
                'typename': 'StatusContext', 'name': node.get('context'), 'state': node.get('state'),
                'targetUrl': node.get('targetUrl'), 'creator': (node.get('creator') or {}).get('login'),
                'headSha': None, 'workflowRunId': None,
            })
    return {
        'number': data.get('number'), 'title': data.get('title'), 'state': data.get('state'),
        'isDraft': bool(data.get('isDraft')), 'mergeable': data.get('mergeable'),
        'mergeStateStatus': data.get('mergeStateStatus'), 'headRefOid': data.get('headRefOid'),
        'baseRefOid': data.get('baseRefOid'), 'url': data.get('url'),
        'labels': [x.get('name') for x in ((data.get('labels') or {}).get('nodes') or [])],
        'checks': checks, 'checksTruncated': bool(contexts.get('pageInfo', {}).get('hasNextPage')),
    }


def external_checks(checks):
    return [c for c in checks if (c.get('workflow') or '') != GATE_WORKFLOW and not str(c.get('name') or '').startswith(GATE_WORKFLOW)]


def evaluate_checks(checks, risk_level, repo='styayur/portfolio-governance', matrix=None, expected_head=''):
    matrix = matrix or load_matrix(Path(__file__).resolve().parents[1] / 'policy/evidence-matrix.v1.json')
    return evaluate_matrix(checks, matrix, repo, risk_level, expected_head)


def wait_for_checks(repo: str, number: int, head_sha: str, base_sha: str, matrix: dict, risk_level: str, timeout: int, poll: int):
    started = time.time()
    while True:
        pr = fetch_pr(repo, number)
        if pr['headRefOid'] != head_sha:
            return pr, None, 'HEAD_CHANGED'
        if pr['baseRefOid'] != base_sha:
            return pr, None, 'BASE_CHANGED'
        status = evaluate_matrix(external_checks(pr['checks']), matrix, repo, risk_level, head_sha)
        if not any(g['status'] == 'PENDING' for g in status['groups']):
            return pr, status, None
        if time.time() - started >= timeout:
            return pr, status, 'TIMEOUT'
        time.sleep(poll)


def gate_attempt_count(repo: str, head_sha: str, current_run_id: str) -> int:
    try:
        raw = run(['gh', 'run', 'list', '--repo', repo, '--workflow', 'portfolio-gate.yml', '--commit', head_sha, '--limit', '100', '--json', 'databaseId,status,conclusion'])
        runs = json.loads(raw)
    except Exception:
        return 1
    prior = [r for r in runs if str(r.get('databaseId')) != str(current_run_id) and r.get('status') == 'completed']
    return len(prior) + 1


def retry_budget_exceeded(attempt_count: int, max_attempts: int) -> bool:
    return int(attempt_count) > int(max_attempts)


def specialist_status(evidence: dict) -> dict:
    native_groups = [g for g in evidence.get('groups', []) if g.get('kind') == 'native']
    if not native_groups:
        return {'status': 'NOT_APPLICABLE', 'reason': 'repository profile has no native platform requirement'}
    if all(g['status'] in {'PASS', 'NOT_APPLICABLE'} for g in native_groups):
        return {'status': 'PASS', 'reason': 'all required native-platform checks passed'}
    return {'status': 'NOT_VERIFIED', 'reason': 'native-platform required evidence is incomplete'}


def manual_binding_matches(manual, risk_level, expected_head, expected_base, diff_sha, pr_number):
    return (
        str(manual.get('prNumber') or '') == str(pr_number or '')
        and str(manual.get('risk') or '').upper() == str(risk_level or '').upper()
        and str(manual.get('headSha') or '').lower() == str(expected_head or '').lower()
        and str(manual.get('baseSha') or '').lower() == str(expected_base or '').lower()
        and str(manual.get('diffSha256') or '').lower() == str(diff_sha or '').lower()
    )


def decide(risk, review, ai_review, evidence, pr, expected_head, expected_base, rollout, attempt_count, manual_approval=None):
    manual_approval = manual_approval or {}
    manual = list(review.get('manualReviewReasons') or [])
    auto = rollout.get('autoMerge') or {}
    matrix_required = evidence.get('requirements') or {}
    diff_sha = risk.get('diffSha256')
    manual_tier = risk.get('risk') in {'R3', 'R4'}
    specialist = specialist_status(evidence) if matrix_required.get('specialistAdapterRequired') else {'status': 'NOT_APPLICABLE', 'reason': 'not required'}
    r4_authorized = (rollout.get('r4AuthorizationLabel') in (pr.get('labels') or [])) if matrix_required.get('explicitAuthorizationRequired') else None
    r4_value = 'PRESENT' if r4_authorized else ('ABSENT' if r4_authorized is False else 'NOT_REQUIRED')

    if pr.get('headRefOid') != expected_head:
        return {'decision': 'FAILED_HEAD_CHANGED', 'autoMergeEligible': False, 'blockedReasons': ['current PR head SHA differs from the reviewed head']}
    if pr.get('baseRefOid') != expected_base:
        return {'decision': 'FAILED_BASE_CHANGED', 'autoMergeEligible': False, 'blockedReasons': ['current PR base SHA differs from the reviewed base']}
    if risk.get('headSha') != expected_head or review.get('headSha') != expected_head:
        return {'decision': 'FAILED_STALE_REVIEW', 'autoMergeEligible': False, 'blockedReasons': ['risk or static review is not bound to the current head SHA']}
    if risk.get('baseSha') != expected_base or review.get('baseSha') != expected_base:
        return {'decision': 'FAILED_STALE_REVIEW', 'autoMergeEligible': False, 'blockedReasons': ['risk or static review is not bound to the current base SHA']}
    if risk.get('diffSha256') and review.get('diffSha256') and risk.get('diffSha256') != review.get('diffSha256'):
        return {'decision': 'FAILED_STALE_REVIEW', 'autoMergeEligible': False, 'blockedReasons': ['static review diff digest does not match risk evidence']}
    if pr.get('state') != 'OPEN':
        return {'decision': 'FAILED_PR_STATE', 'autoMergeEligible': False, 'blockedReasons': ['pull request is not open']}
    if pr.get('isDraft'):
        return {'decision': 'WAITING_FOR_READY', 'autoMergeEligible': False, 'blockedReasons': ['draft pull requests are never auto-merged']}
    if review.get('decision') == 'BLOCK':
        return {'decision': 'FAILED_REVIEW_BLOCK', 'autoMergeEligible': False, 'blockedReasons': list(review.get('blockers') or ['static review blocked the change'])}
    if pr.get('checksTruncated'):
        return {'decision': 'FAILED_CHECK_ROLLUP_TRUNCATED', 'autoMergeEligible': False, 'blockedReasons': ['GitHub returned more than 100 status checks; fail closed']}
    if review.get('decision') == 'MANUAL_REVIEW_REQUIRED':
        manual.append('static policy review requires a maintainer decision')

    ai_verified = ai_review.get('status') == 'VERIFIED'
    ai_bound = (
        ai_verified
        and ai_review.get('headSha') == expected_head
        and ai_review.get('baseSha') == expected_base
        and ai_review.get('diffSha256') == diff_sha
    )
    ai_approved = ai_bound and ai_review.get('decision') == 'APPROVE'
    ai_blocked = ai_bound and ai_review.get('decision') == 'BLOCK'

    if manual_tier:
        evidence_reasons = [g.get('reason', '') for g in evidence.get('groups', []) if g.get('status') != 'PASS']
        if evidence.get('status') != 'PASS':
            return {
                'decision': f'FAILED_EVIDENCE_{evidence.get("status", "NOT_VERIFIED")}',
                'autoMergeEligible': False,
                'blockedReasons': evidence_reasons or ['required evidence is incomplete'],
                'manualReviewReasons': sorted(set(manual)),
                'manualApproval': manual_approval,
                'specialistAdapter': specialist,
                'r4Authorization': r4_value,
            }
        if matrix_required.get('specialistAdapterRequired') and specialist['status'] not in {'PASS', 'NOT_APPLICABLE'}:
            return {
                'decision': 'FAILED_SPECIALIST_EVIDENCE',
                'autoMergeEligible': False,
                'blockedReasons': [specialist.get('reason') or 'specialist adapter evidence is incomplete'],
                'manualReviewReasons': sorted(set(manual)),
                'manualApproval': manual_approval,
                'specialistAdapter': specialist,
                'r4Authorization': r4_value,
            }
        if ai_blocked:
            return {
                'decision': 'FAILED_AI_REVIEW_BLOCK',
                'autoMergeEligible': False,
                'blockedReasons': [ai_review.get('reason') or 'independent AI review blocked the change'],
                'manualReviewReasons': sorted(set(manual)),
                'manualApproval': manual_approval,
                'specialistAdapter': specialist,
                'r4Authorization': r4_value,
            }
        if not ai_approved:
            manual.append(ai_review.get('reason') or 'AI review did not approve; an authenticated exact-bound maintainer decision is required')
        if matrix_required.get('explicitAuthorizationRequired') and not r4_authorized:
            manual.append('R4 explicit authorization label is absent')
        if pr.get('mergeable') == 'CONFLICTING' or pr.get('mergeStateStatus') in {'DIRTY', 'BEHIND', 'DRAFT'}:
            return {
                'decision': 'BLOCKED_MERGE_STATE',
                'autoMergeEligible': False,
                'blockedReasons': ['GitHub reports a conflicting, dirty, behind or draft merge state'],
                'manualReviewReasons': sorted(set(manual)),
                'manualApproval': manual_approval,
                'specialistAdapter': specialist,
                'r4Authorization': r4_value,
            }

        state = str(manual_approval.get('state') or 'PENDING_MANUAL')
        bound = manual_binding_matches(manual_approval, risk.get('risk'), expected_head, expected_base, diff_sha, pr.get('number'))
        if not bound:
            state = 'PENDING_MANUAL'
            manual.append('manual approval is missing or is not bound to the exact PR head, base and diff')
        if state == 'REJECTED_MANUAL':
            return {
                'decision': 'REJECTED_MANUAL',
                'autoMergeEligible': False,
                'blockedReasons': list(manual_approval.get('reasons') or ['an authorized maintainer rejected this exact binding']),
                'manualReviewReasons': sorted(set(manual)),
                'manualApproval': manual_approval,
                'specialistAdapter': specialist,
                'r4Authorization': r4_value,
            }
        if matrix_required.get('explicitAuthorizationRequired') and not r4_authorized:
            state = 'PENDING_MANUAL'
            manual.append('R4 requires the portfolio:r4-approved maintainer label plus the exact-bound authorize-r4 review')
        if state == 'APPROVED_MANUAL':
            return {
                'decision': 'APPROVED_MANUAL',
                'autoMergeEligible': False,
                'blockedReasons': [],
                'manualReviewReasons': sorted(set(manual)),
                'manualApproval': manual_approval,
                'specialistAdapter': specialist,
                'r4Authorization': r4_value,
            }
        return {
            'decision': 'PENDING_MANUAL',
            'autoMergeEligible': False,
            'blockedReasons': list(manual_approval.get('reasons') or manual or ['manual maintainer approval is pending']),
            'manualReviewReasons': sorted(set(manual)),
            'manualApproval': manual_approval,
            'specialistAdapter': specialist,
            'r4Authorization': r4_value,
        }

    shadow_reasons = []
    if evidence.get('status') != 'PASS':
        shadow_reasons.extend([g.get('reason', '') for g in evidence.get('groups', []) if g.get('status') != 'PASS'] or ['required evidence is incomplete'])
    if matrix_required.get('aiReviewRequired') and not ai_approved:
        shadow_reasons.append(ai_review.get('reason') or 'independent AI review is unavailable or did not approve')
    if matrix_required.get('aiReviewRequired') and ai_verified and not ai_bound:
        shadow_reasons.append('AI review evidence is not bound to the exact head, base and diff')
    if matrix_required.get('specialistAdapterRequired') and specialist['status'] not in {'PASS', 'NOT_APPLICABLE'}:
        shadow_reasons.append('specialist adapter evidence is incomplete')
    if matrix_required.get('explicitAuthorizationRequired') and not r4_authorized:
        shadow_reasons.append('R4 explicit authorization label is absent')
    if pr.get('mergeable') == 'CONFLICTING' or pr.get('mergeStateStatus') in {'DIRTY', 'BEHIND', 'DRAFT'}:
        shadow_reasons.append('GitHub reports a conflicting, dirty, behind or draft merge state')
    retry_exceeded = retry_budget_exceeded(attempt_count, rollout.get('maxAttemptsPerHead', 3))
    if retry_exceeded:
        shadow_reasons.append('maximum gate attempts for this exact head exceeded')

    would_auto = not manual and not shadow_reasons and risk.get('risk') in {'R0', 'R1', 'R2'} and auto.get(risk.get('risk'), False)
    if would_auto and risk.get('risk') == 'R2' and not matrix_required.get('aiReviewRequired'):
        would_auto = False
        shadow_reasons.append('R2 requires an AI review and complete matrix')
    if rollout.get('mode') == 'shadow':
        return {
            'decision': 'SHADOW_ELIGIBLE' if would_auto else 'SHADOW_BLOCKED',
            'autoMergeEligible': False,
            'shadowEligible': would_auto,
            'blockedReasons': shadow_reasons,
            'manualReviewReasons': manual,
            'specialistAdapter': specialist,
            'r4Authorization': r4_value,
        }

    if evidence.get('status') != 'PASS':
        return {'decision': f'FAILED_EVIDENCE_{evidence.get("status", "NOT_VERIFIED")}', 'autoMergeEligible': False, 'blockedReasons': shadow_reasons[:1] or ['required evidence is incomplete']}
    if matrix_required.get('aiReviewRequired') and not ai_approved:
        return {'decision': 'FAILED_AI_REVIEW_NOT_VERIFIED', 'autoMergeEligible': False, 'blockedReasons': [ai_review.get('reason') or 'independent AI review is unavailable or did not approve']}
    if matrix_required.get('aiReviewRequired') and not ai_bound:
        return {'decision': 'FAILED_STALE_REVIEW', 'autoMergeEligible': False, 'blockedReasons': ['AI review evidence is not bound to the exact head, base and diff']}
    if retry_exceeded:
        return {'decision': 'FAILED_RETRY_BUDGET', 'autoMergeEligible': False, 'blockedReasons': ['maximum gate attempts for this exact head exceeded']}
    if manual:
        return {
            'decision': 'MANUAL_REVIEW_REQUIRED',
            'autoMergeEligible': False,
            'blockedReasons': shadow_reasons,
            'manualReviewReasons': sorted(set(manual)),
            'specialistAdapter': specialist,
            'r4Authorization': r4_value,
        }
    if not would_auto:
        return {
            'decision': 'BLOCKED_POLICY',
            'autoMergeEligible': False,
            'blockedReasons': shadow_reasons or ['policy does not permit automatic merge for this result'],
            'manualReviewReasons': manual,
            'specialistAdapter': specialist,
            'r4Authorization': 'NOT_REQUIRED',
        }
    return {
        'decision': 'AUTO_MERGE_ELIGIBLE',
        'autoMergeEligible': True,
        'blockedReasons': [],
        'manualReviewReasons': [],
        'specialistAdapter': specialist,
        'r4Authorization': 'NOT_REQUIRED',
    }

def successful_decision(decision: str) -> bool:
    """A required check may be green only for an auto-merge result or approved manual decision."""
    return decision in {'AUTO_MERGE_ELIGIBLE', 'APPROVED_MANUAL'}


def _render_comment(record):
    manual_state = (record.get('manualApproval') or {}).get('state') or 'NOT_APPLICABLE'
    lines = ['### Portfolio evidence gate', '', f"- Mode: **{record.get('mode')}**", f"- Risk: **{record.get('risk')}**", f"- Head: `{record.get('headSha')}`", f"- Base: `{record.get('baseSha')}`", f"- Diff: `{record.get('diffSha256')}`", f"- Evidence Matrix: **{record.get('evidenceStatus')}**", f"- Security: **{record.get('securityStatus')}**", f"- Static review: **{record.get('reviewDecision')}**", f"- AI review: **{record.get('aiReviewStatus')} / {record.get('aiReviewDecision')}**", f"- Manual review: **{manual_state}**", f"- Decision: **{record.get('decision')}**", f"- Auto-merge eligible: **{str(record.get('autoMergeEligible')).lower()}**", f"- Evidence run: {record.get('workflowRunUrl') or 'not available'}", '']
    for group in record.get('requiredEvidence', []):
        lines.append(f"- {group.get('role')}: **{group.get('status')}** — {group.get('reason')}")
    if record.get('blockedReasons'):
        lines += ['', 'Blocking reasons:'] + [f'- {x}' for x in record['blockedReasons'] if x]
    if record.get('manualReviewReasons'):
        lines += ['', 'Manual review reasons:'] + [f'- {x}' for x in record['manualReviewReasons'] if x]
    if record.get('risk') in {'R3', 'R4'}:
        binding = [
            '/portfolio approve-manual',
            f"pr={record.get('prNumber')}",
            f"head={record.get('headSha')}",
            f"base={record.get('baseSha')}",
            f"diff={record.get('diffSha256')}",
            f"risk={record.get('risk')}",
        ]
        lines += ['', 'Submit the command below as a pull-request review. A `COMMENTED` review is accepted on self-authored PRs.', '', '```text', *binding, '```']
        if record.get('risk') == 'R4':
            r4 = [*binding]
            r4[0] = '/portfolio authorize-r4'
            lines += ['', 'R4 also requires the `portfolio:r4-approved` label and this separate authorization review:', '', '```text', *r4, '```']
    return '\n'.join(lines) + '\n'


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
    parser.add_argument('--base-sha', required=True)
    parser.add_argument('--risk', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--ai-review', type=Path)
    parser.add_argument('--manual-approval', type=Path)
    parser.add_argument('--matrix', type=Path, default=Path('policy/evidence-matrix.v1.json'))
    parser.add_argument('--rollout', type=Path, default=Path('policy/rollout.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', default=os.environ.get('GITHUB_RUN_ID', ''))
    parser.add_argument('--timeout', type=int, default=int(os.environ.get('GATE_TIMEOUT_SECONDS', '2700')))
    parser.add_argument('--poll', type=int, default=int(os.environ.get('GATE_POLL_SECONDS', '15')))
    parser.add_argument('--max-attempts', type=int, default=3)
    parser.add_argument('--enable-auto-merge', action='store_true')
    parser.add_argument('--comment', action='store_true')
    args = parser.parse_args()

    matrix = load_matrix(args.matrix)
    rollout = load_rollout(args.rollout)
    risk = json.loads(args.risk.read_text())
    review = json.loads(args.review.read_text())
    ai_review = json.loads(args.ai_review.read_text()) if args.ai_review and args.ai_review.exists() else {'status': 'NOT_VERIFIED', 'decision': 'NOT_VERIFIED', 'reason': 'AI review artifact missing'}
    manual_approval = json.loads(args.manual_approval.read_text()) if args.manual_approval and args.manual_approval.exists() else {}
    if risk.get('headSha') != args.head_sha or risk.get('baseSha') != args.base_sha or review.get('headSha') != args.head_sha or review.get('baseSha') != args.base_sha:
        raise SystemExit('risk/review evidence does not match requested base/head SHA')

    pr, evidence, wait_error = wait_for_checks(args.repo, args.pr, args.head_sha, args.base_sha, matrix, risk['risk'], args.timeout, args.poll)
    attempt_count = gate_attempt_count(args.repo, args.head_sha, args.run_id)
    if wait_error == 'HEAD_CHANGED':
        decision = {'decision': 'FAILED_HEAD_CHANGED', 'autoMergeEligible': False, 'blockedReasons': ['current PR head changed during evidence collection']}
    elif wait_error == 'BASE_CHANGED':
        decision = {'decision': 'FAILED_BASE_CHANGED', 'autoMergeEligible': False, 'blockedReasons': ['current PR base changed during evidence collection']}
    elif wait_error == 'TIMEOUT':
        decision = {'decision': 'FAILED_CHECK_TIMEOUT', 'autoMergeEligible': False, 'blockedReasons': ['required checks did not complete before timeout']}
    elif evidence is None:
        decision = {'decision': 'FAILED_UNKNOWN_CHECK_STATE', 'autoMergeEligible': False, 'blockedReasons': ['no check evidence was produced']}
    else:
        decision = decide(risk, review, ai_review, evidence, pr, args.head_sha, args.base_sha, rollout, attempt_count, manual_approval)

    checks = evidence or {}
    auto_merge_eligible = bool(args.enable_auto_merge and decision.get('autoMergeEligible'))
    record = {
        'schemaVersion': 2,
        'mode': rollout.get('mode'),
        'subject': f'{args.repo}#{args.pr}',
        'repository': args.repo,
        'repositoryId': risk.get('repositoryId'),
        'prNumber': args.pr,
        'baseSha': risk.get('baseSha'),
        'headSha': args.head_sha,
        'diffSha256': risk.get('diffSha256'),
        'workflowRunId': args.run_id,
        'workflowRunUrl': f'https://github.com/{args.repo}/actions/runs/{args.run_id}' if args.run_id else None,
        'tool': {'name': 'Portfolio Evidence Gate', 'version': '2.1.0'},
        'risk': risk.get('risk'),
        'riskReasons': risk.get('reasons'),
        'mergeStatus': {'mergeable': pr.get('mergeable'), 'mergeStateStatus': pr.get('mergeStateStatus')},
        'attemptCount': attempt_count,
        'maxAttemptsPerHead': args.max_attempts,
        'evidenceStatus': checks.get('status', 'NOT_VERIFIED'),
        'requiredEvidence': checks.get('groups', []),
        'notApplicableEvidence': checks.get('notApplicableGroups', []),
        'sourceValidation': checks.get('sourceValidation', {}),
        'checks': checks.get('checks', []),
        'securityStatus': next((g['status'] for g in checks.get('groups', []) if g.get('role') == 'security'), 'NOT_VERIFIED'),
        'reviewDecision': review.get('decision'),
        'reviewBlockers': review.get('blockers', []),
        'manualReviewReasons': decision.get('manualReviewReasons', review.get('manualReviewReasons', [])),
        'manualApproval': decision.get('manualApproval', manual_approval),
        'aiReviewStatus': ai_review.get('status'),
        'aiReviewDecision': ai_review.get('decision'),
        'aiReviewReason': ai_review.get('reason'),
        'specialistAdapter': decision.get('specialistAdapter'),
        'r4Authorization': decision.get('r4Authorization'),
        'decision': decision.get('decision'),
        'autoMergeEligible': auto_merge_eligible,
        'shadowEligible': decision.get('shadowEligible'),
        'blockedReasons': decision.get('blockedReasons', []),
        'verifiedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'residualRisk': 'Gate decisions are limited to the exact base/head/diff and trusted GitHub Actions check sources in this record.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    if args.comment:
        try:
            upsert_comment(args.repo, args.pr, _render_comment(record))
        except Exception as exc:
            record['commentError'] = str(exc)
            args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: record[k] for k in ('mode','risk','evidenceStatus','securityStatus','reviewDecision','aiReviewStatus','decision','autoMergeEligible','shadowEligible')}, ensure_ascii=False))
    return 0 if successful_decision(record['decision']) else 2


if __name__ == '__main__':
    raise SystemExit(main())
