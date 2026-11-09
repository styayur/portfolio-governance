#!/usr/bin/env python3
"""Evaluate exact-head-human manual approvals for R3/R4 pull requests."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'policy/manual-approval.v1.json'
HEX40 = re.compile(r'^[0-9a-f]{40}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
COMMAND_RE = re.compile(r'(?mi)^/portfolio\s+(approve-manual|reject-manual|authorize-r4)\s*$')
FIELD_RE = re.compile(r'(?mi)^(pr|head|base|diff|risk|reason)=(.+?)\s*$')
ALLOWED = {'approve-manual', 'reject-manual', 'authorize-r4'}


def run(args):
    proc = subprocess.run(args, text=True, capture_output=True)
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return proc.stdout


def api_json(path):
    return json.loads(run(['gh', 'api', path]))


def api_json_lines(path):
    text = run(['gh', 'api', '--paginate', '--jq', '.[]', path])
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def fetch_pr(repo, number):
    data = api_json(f'repos/{repo}/pulls/{number}')
    return {
        'number': data.get('number'),
        'state': data.get('state'),
        'headSha': (data.get('head') or {}).get('sha'),
        'baseSha': (data.get('base') or {}).get('sha'),
        'labels': [item.get('name') for item in data.get('labels') or []],
    }


def fetch_reviews(repo, number):
    return api_json_lines(f'repos/{repo}/pulls/{number}/reviews?per_page=100')


def fetch_permission(repo, login):
    data = api_json(f'repos/{repo}/collaborators/{login}/permission')
    return data.get('role_name') or data.get('permission') or 'none'


def parse_command(body):
    commands = [match.group(1).lower() for match in COMMAND_RE.finditer(body or '')]
    if len(commands) != 1:
        return None, 'review must contain exactly one manual approval command'
    fields = {}
    for match in FIELD_RE.finditer(body or ''):
        key = match.group(1).lower()
        if key in fields:
            return None, f'duplicate command field: {key}'
        fields[key] = match.group(2).strip()
    return {'command': commands[0], **fields}, ''


def binding_matches(fields, pr_number, head_sha, base_sha, diff_sha, risk_level):
    return (
        str(fields.get('pr')) == str(pr_number)
        and str(fields.get('head', '')).lower() == head_sha.lower()
        and str(fields.get('base', '')).lower() == base_sha.lower()
        and str(fields.get('diff', '')).lower() == diff_sha.lower()
        and str(fields.get('risk', '')).upper() == risk_level.upper()
    )


def evaluate(review_records, pr_meta, risk_data, config, permission_fetcher=fetch_permission, repo='styayur/example', now=None):
    head_sha = str(risk_data.get('headSha') or '').lower()
    base_sha = str(risk_data.get('baseSha') or '').lower()
    diff_sha = str(risk_data.get('diffSha256') or '').lower()
    risk_level = str(risk_data.get('risk') or '').upper()
    pr_number = int(risk_data.get('prNumber') or pr_meta.get('number') or 0)
    roles = {str(role).lower() for role in config.get('authorizedRoles') or []}
    commands = config.get('commands') or {}
    reject_bots = bool(config.get('rejectBots', True))
    actions = []
    ignored = []
    reasons = []

    if not (HEX40.fullmatch(head_sha) and HEX40.fullmatch(base_sha) and HEX64.fullmatch(diff_sha)):
        reasons.append('manual approval binding inputs are malformed')
    if risk_level not in {'R3', 'R4'}:
        reasons.append('manual approval is only applicable to R3/R4')
    if pr_meta.get('headSha') != risk_data.get('headSha') or pr_meta.get('baseSha') != risk_data.get('baseSha'):
        reasons.append('pull request head or base changed before manual approval evaluation')
    if config.get('status') != 'ACTIVE':
        return {
            'schemaVersion': 1, 'state': 'BLOCKED', 'risk': risk_level, 'prNumber': pr_number,
            'headSha': head_sha, 'baseSha': base_sha, 'diffSha256': diff_sha,
            'actions': [], 'ignored': [], 'reasons': sorted(set(reasons + ['manual approval policy is not ACTIVE'])),
            'evaluatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }

    permission_cache = {}
    for review in sorted(review_records, key=lambda value: (str(value.get('submitted_at') or ''), int(value.get('id') or 0))):
        review_id = review.get('id')
        user = review.get('user') or {}
        login = str(user.get('login') or '')
        user_type = str(user.get('type') or '')
        state = str(review.get('state') or '').upper()
        if not login:
            ignored.append({'reviewId': review_id, 'author': None, 'reason': 'review has no author identity'})
            continue
        if reject_bots and (user_type.casefold() == 'bot' or login.casefold().endswith('[bot]')):
            ignored.append({'reviewId': review_id, 'author': login, 'reason': 'bot-authored reviews are not human authorization'})
            continue
        if login not in permission_cache:
            try:
                permission_cache[login] = str(permission_fetcher(repo, login)).lower()
            except Exception as error:  # network/API denial fails closed for this review
                permission_cache[login] = f'UNAVAILABLE: {error}'
        permission = permission_cache[login]
        if permission not in roles:
            ignored.append({'reviewId': review_id, 'author': login, 'permission': permission, 'reason': 'review author is not an authorized maintainer'})
            continue
        if state == 'DISMISSED':
            ignored.append({'reviewId': review_id, 'author': login, 'permission': permission, 'reason': 'dismissed review is not an approval'})
            continue
        if str(review.get('commit_id') or '').lower() != head_sha:
            ignored.append({'reviewId': review_id, 'author': login, 'permission': permission, 'reason': 'review commit is not the current head'})
            continue
        parsed, parse_error = parse_command(review.get('body') or '')
        if not parsed:
            ignored.append({'reviewId': review_id, 'author': login, 'permission': permission, 'reason': parse_error})
            continue
        if parsed['command'] not in ALLOWED:
            ignored.append({'reviewId': review_id, 'author': login, 'permission': permission, 'reason': 'unsupported manual command'})
            continue
        if parsed['command'] == 'approve-manual' and state not in {'APPROVED', 'COMMENTED'}:
            ignored.append({'reviewId': review_id, 'author': login, 'permission': permission, 'reason': 'approval command requires an APPROVED or COMMENTED review'})
            continue
        if not binding_matches(parsed, pr_number, head_sha, base_sha, diff_sha, risk_level):
            ignored.append({'reviewId': review_id, 'author': login, 'permission': permission, 'reason': 'command binding is stale, forged, or for another PR/head/base/diff'})
            continue
        if parsed['command'] == 'reject-manual' and not str(parsed.get('reason') or '').strip():
            ignored.append({'reviewId': review_id, 'author': login, 'permission': permission, 'reason': 'rejection command requires a reason'})
            continue
        actions.append({
            'reviewId': review_id,
            'author': login,
            'permission': permission,
            'command': parsed['command'],
            'submittedAt': review.get('submitted_at'),
            'state': state,
            'reason': parsed.get('reason'),
        })

    rejections = [a for a in actions if a['command'] == 'reject-manual']
    if rejections:
        last_reject = rejections[-1]
        effective = [a for a in actions if str(a.get('submittedAt') or '') >= str(last_reject.get('submittedAt') or '') and a is not last_reject]
    else:
        last_reject = None
        effective = actions
    approvals = [a for a in effective if a['command'] == 'approve-manual']
    authorizations = [a for a in effective if a['command'] == 'authorize-r4']
    state = 'PENDING_MANUAL'

    if risk_level == 'R4':
        label = config.get('r4', {}).get('authorizationLabel') or 'portfolio:r4-approved'
        if label not in (pr_meta.get('labels') or []):
            reasons.append(f'R4 authorization label is absent: {label}')
        if not approvals:
            reasons.append('no current exact-bound approve-manual review from an authorized maintainer')
        if not authorizations:
            reasons.append('no current exact-bound authorize-r4 review from an authorized maintainer')
        if approvals and authorizations and label in (pr_meta.get('labels') or []):
            state = 'APPROVED_MANUAL'
    elif risk_level == 'R3':
        if not approvals:
            reasons.append('no current exact-bound approve-manual review from an authorized maintainer')
        else:
            state = 'APPROVED_MANUAL'

    if last_reject:
        if not effective:
            state = 'REJECTED_MANUAL'
            reasons = [f"authorized maintainer {last_reject['author']} rejected this exact binding: {last_reject.get('reason')}"]
        elif state == 'PENDING_MANUAL':
            reasons.append('a newer matching approval/authorization is incomplete after the latest rejection')

    if state == 'APPROVED_MANUAL':
        reasons = []

    return {
        'schemaVersion': 1,
        'state': state,
        'risk': risk_level,
        'prNumber': pr_number,
        'headSha': head_sha,
        'baseSha': base_sha,
        'diffSha256': diff_sha,
        'actions': actions,
        'ignored': ignored,
        'reasons': sorted(set(reason for reason in reasons if reason)),
        'authorizedRoles': sorted(roles),
        'commands': commands,
        'evaluatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--risk', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    risk_data = json.loads(args.risk.read_text(encoding='utf-8'))
    config = json.loads(args.config.read_text(encoding='utf-8'))
    try:
        pr_meta = fetch_pr(args.repo, args.pr)
        reviews = fetch_reviews(args.repo, args.pr)
        result = evaluate(reviews, pr_meta, risk_data, config, repo=args.repo)
    except Exception as error:
        result = {
            'schemaVersion': 1, 'state': 'BLOCKED', 'risk': risk_data.get('risk'),
            'prNumber': args.pr, 'headSha': risk_data.get('headSha'), 'baseSha': risk_data.get('baseSha'),
            'diffSha256': risk_data.get('diffSha256'), 'actions': [], 'ignored': [],
            'reasons': [f'manual approval evaluation unavailable: {type(error).__name__}: {error}'],
            'evaluatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'state': result['state'], 'reasons': result.get('reasons', [])}, ensure_ascii=False))
    return 0 if result['state'] in {'PENDING_MANUAL', 'APPROVED_MANUAL', 'REJECTED_MANUAL'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
