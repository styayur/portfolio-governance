#!/usr/bin/env python3
"""Build an auditable disposition for every live Dependabot alert.

The script never dismisses alerts. An unmatched alert is treated as an
unclassified blocker and causes a non-zero exit after the evidence is written.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'policy' / 'dependabot-dispositions.json'
DEFAULT_OUT = ROOT / 'evidence' / 'risk' / 'dependabot-risk-disposition.json'


def run(args):
    p = subprocess.run(args, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return p.stdout



def enabled(value, patterns) -> bool:
    return any(value == pattern or pattern == '*' for pattern in patterns)


def match_entry(repo, alert, entries):
    package = (alert.get('dependency') or {}).get('package') or {}
    package_name = package.get('name')
    ecosystem = package.get('ecosystem')
    for entry in entries:
        match = entry.get('match') or {}
        if not enabled(repo, match.get('repositories') or []):
            continue
        if not enabled(package_name, match.get('packages') or []):
            continue
        if match.get('ecosystems') and not enabled(ecosystem, match['ecosystems']):
            continue
        return entry
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    policy = json.loads(POLICY.read_text())
    entries = policy.get('entries') or []
    repos = json.loads(run(['gh', 'repo', 'list', 'styayur', '--visibility', 'public', '--limit', '200', '--json', 'nameWithOwner']))
    records = []
    errors = []
    counts = {}
    for item in sorted(repos, key=lambda x: x['nameWithOwner']):
        repo = item['nameWithOwner']
        try:
            alerts = json.loads(run(['gh', 'api', f'repos/{repo}/dependabot/alerts?state=open&per_page=100']))
        except Exception as exc:
            errors.append({'repository': repo, 'status': 'NOT_VERIFIED', 'reason': str(exc)})
            continue
        for alert in alerts:
            dep = alert.get('dependency') or {}
            package = dep.get('package') or {}
            advisory = alert.get('security_advisory') or {}
            entry = match_entry(repo, alert, entries)
            disposition = entry or {'disposition': 'UNCLASSIFIED_BLOCKED', 'priority': 'P0', 'owner': 'styayur', 'remediation': 'Add a reviewed disposition entry before any dismissal or release claim.'}
            key = disposition.get('disposition') or 'UNCLASSIFIED_BLOCKED'
            counts[key] = counts.get(key, 0) + 1
            records.append({
                'subject': f'{repo} Dependabot #{alert.get("number")}',
                'repository': repo,
                'alertNumber': alert.get('number'),
                'package': package.get('name'),
                'ecosystem': package.get('ecosystem'),
                'manifest': dep.get('manifest_path'),
                'severity': advisory.get('severity'),
                'summary': advisory.get('summary'),
                'vulnerableRange': (alert.get('security_vulnerability') or {}).get('vulnerable_version_range'),
                'patchedVersion': (alert.get('security_vulnerability') or {}).get('first_patched_version'),
                'status': key,
                'priority': disposition.get('priority') or 'P0',
                'owner': disposition.get('owner') or 'styayur',
                'dependencyChain': disposition.get('dependencyChain'),
                'impact': disposition.get('impact'),
                'mitigation': disposition.get('mitigation') or disposition.get('remediation'),
                'recheckCondition': disposition.get('recheckCondition'),
                'reviewBy': disposition.get('reviewBy'),
                'tracking': disposition.get('tracking') or [],
                'evidence': alert.get('html_url'),
                'dismissed': False,
            })
    out = {
        'schemaVersion': 1,
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'policy': str(POLICY.relative_to(ROOT)),
        'totalOpen': len(records),
        'countsByDisposition': counts,
        'records': records,
        'errors': errors,
        'unclassified': sum(1 for r in records if r['status'] == 'UNCLASSIFIED_BLOCKED'),
        'note': 'No alert was dismissed or auto-closed by this audit.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'totalOpen': out['totalOpen'], 'counts': counts, 'errors': len(errors), 'output': str(args.output)}, ensure_ascii=False))
    return 1 if errors or out['unclassified'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
