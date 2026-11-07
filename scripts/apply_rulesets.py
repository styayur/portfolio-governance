#!/usr/bin/env python3
"""Apply the portfolio ruleset only where the fixed caller is already on main."""
from __future__ import annotations

import base64, json, os, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / 'evidence/baseline/portfolio-inventory.json'
OUT = ROOT / 'evidence/baseline/branch-protection-audit.json'
FIXED_SHA = 'be210b2d3761a2c7aad67fb3ca0f900e08e9b8fa'
REQUIRED_CHECK = 'portfolio / Portfolio Evidence Gate / verify'
RULESET_NAME = 'Portfolio default branch safety'
RULESET = {
    'name': RULESET_NAME,
    'target': 'branch',
    'enforcement': 'active',
    'conditions': {'ref_name': {'include': ['~DEFAULT_BRANCH'], 'exclude': []}},
    'rules': [
        {'type': 'deletion'},
        {'type': 'non_fast_forward'},
        {'type': 'pull_request', 'parameters': {
            'required_approving_review_count': 0,
            'dismiss_stale_reviews_on_push': True,
            'require_code_owner_review': False,
            'require_last_push_approval': False,
            'required_review_thread_resolution': True,
            'require_extra_approval_for_unattributed_changes': False,
            'allowed_merge_methods': ['squash'],
        }},
        {'type': 'required_status_checks', 'parameters': {
            'strict_required_status_checks_policy': True,
            'do_not_enforce_on_create': False,
            'required_status_checks': [{'context': REQUIRED_CHECK, 'integration_id': 15368}],
        }},
    ],
    'bypass_actors': [],
}


def run(args, input_text=None):
    return subprocess.run(args, input=input_text, text=True, capture_output=True)


def api(path):
    p = run(['gh', 'api', path])
    if p.returncode: return {'_error': (p.stderr or p.stdout).strip()}
    return json.loads(p.stdout) if p.stdout.strip() else {}


def caller_pin(repo):
    p = run(['gh', 'api', f'repos/{repo}/contents/.github/workflows/portfolio-gate.yml'])
    if p.returncode: return None
    value = json.loads(p.stdout)
    return base64.b64decode(value['content']).decode('utf-8')


def main():
    inventory = json.loads(INVENTORY.read_text())
    records = []
    for repo in inventory['repositories']:
        full = repo['full_name']
        before = api(f'repos/{full}/rulesets')
        before_list = before if isinstance(before, list) else []
        existing = next((r for r in before_list if r.get('name') == RULESET_NAME), None)
        content = caller_pin(full)
        if existing:
            status, reason = 'PASS', 'Ruleset already exists.'
        elif not content or FIXED_SHA not in content:
            status, reason = 'BLOCKED', 'Fixed evidence-gate caller is not on the default branch yet.'
        else:
            p = run(['gh', 'api', '-X', 'POST', f'repos/{full}/rulesets', '--input', '-'], json.dumps(RULESET))
            if p.returncode:
                status, reason = 'FAIL', (p.stderr or p.stdout).strip()
            else:
                created = json.loads(p.stdout)
                existing = created
                status, reason = 'PASS', 'Ruleset created and active.'
                print(full, 'CREATED', created.get('id'), flush=True)
        after = api(f'repos/{full}/rulesets')
        after_list = after if isinstance(after, list) else []
        current = next((r for r in after_list if r.get('name') == RULESET_NAME), None)
        if current:
            detail = api(f"repos/{full}/rulesets/{current['id']}")
            verified = bool(detail.get('enforcement') == 'active' and not detail.get('bypass_actors'))
            if not verified:
                status, reason = 'FAIL', 'Ruleset exists but is inactive or has bypass actors.'
        records.append({
            'subject': full,
            'status': status,
            'reason': reason,
            'beforePresence': bool(existing or before_list and any(r.get('name') == RULESET_NAME for r in before_list)),
            'after': detail if current else None,
            'requiredCheck': REQUIRED_CHECK,
            'fixedGateSha': FIXED_SHA,
            'verifiedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'residualRisk': 'Required check must be observed on future PRs; missing/skipped/failing checks fail closed.',
        })
        if not current:
            print(full, status, reason, flush=True)
    OUT.write_text(json.dumps({'rulesetName': RULESET_NAME, 'records': records}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'pass': sum(x['status']=='PASS' for x in records), 'blocked': sum(x['status']=='BLOCKED' for x in records), 'fail': sum(x['status']=='FAIL' for x in records)}, ensure_ascii=False))


if __name__ == '__main__':
    main()