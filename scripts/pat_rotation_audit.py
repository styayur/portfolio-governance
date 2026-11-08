#!/usr/bin/env python3
"""Check the Portfolio Project PAT rotation window."""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'evidence' / 'risk' / 'pat-rotation.json'


def classify_pat(expires: str, today: date, thresholds=None) -> dict:
    thresholds = thresholds or {'warningDays': 30, 'criticalDays': 14, 'finalWarningDays': 7}
    if not expires:
        return {'status': 'NOT_VERIFIED', 'daysRemaining': None, 'reason': 'PAT expiry is not configured'}
    try:
        expiry = date.fromisoformat(expires)
        days = (expiry - today).days
        if days <= 0:
            return {'status': 'EXPIRED', 'daysRemaining': days, 'reason': 'PAT has expired or expires today'}
        if days <= thresholds['finalWarningDays']:
            return {'status': 'FINAL_WARNING', 'daysRemaining': days, 'reason': 'PAT expires within 7 days; rotate immediately'}
        if days <= thresholds['criticalDays']:
            return {'status': 'CRITICAL', 'daysRemaining': days, 'reason': 'PAT expires within 14 days'}
        if days <= thresholds['warningDays']:
            return {'status': 'WARNING', 'daysRemaining': days, 'reason': 'PAT expires within 30 days'}
        return {'status': 'PASS', 'daysRemaining': days, 'reason': 'PAT is outside the 30-day rotation window'}
    except ValueError:
        return {'status': 'NOT_VERIFIED', 'daysRemaining': None, 'reason': 'PAT expiry is not a valid ISO date'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expires', default=os.environ.get('PORTFOLIO_PROJECT_TOKEN_EXPIRES_AT', ''))
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    today = datetime.now(timezone.utc).date()
    thresholds = {'warningDays': 30, 'criticalDays': 14, 'finalWarningDays': 7}
    result_status = classify_pat(args.expires, today)
    result = {
        'schemaVersion': 1,
        'checkedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'expires': args.expires or None,
        'daysRemaining': result_status['daysRemaining'],
        'thresholds': thresholds,
        'rotationDue': bool(result_status['daysRemaining'] is not None and result_status['daysRemaining'] <= thresholds['warningDays']),
        'status': result_status['status'],
        'reason': result_status['reason'],
        'remediation': 'Rotate PORTFOLIO_PROJECT_TOKEN before the 7-day threshold and redeploy the project-sync workflow.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result_status['status'] in {'FINAL_WARNING', 'CRITICAL', 'EXPIRED', 'NOT_VERIFIED'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
