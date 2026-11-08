#!/usr/bin/env python3
"""Verify final acceptance status and blockers are internally consistent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate_acceptance(value: dict) -> dict:
    status = value.get('overallStatus')
    blockers = value.get('blockers') or []
    if status not in {'PASS', 'BLOCKED', 'FAIL'}:
        raise ValueError(f'unknown overallStatus: {status!r}')
    if status == 'PASS' and blockers:
        raise ValueError('PASS cannot coexist with blockers')
    if status != 'PASS' and not blockers:
        raise ValueError(f'{status} requires at least one blocker')
    return {'status': 'PASS', 'overallStatus': status, 'blockers': len(blockers)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', type=Path, required=True)
    args = parser.parse_args()
    result = validate_acceptance(json.loads(args.path.read_text()))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
