#!/usr/bin/env python3
"""Pure classification helpers for security-scanner evidence."""
from __future__ import annotations

import re


def classify_code_scanning(security_analysis, workflows, alerts, latest_run=None):
    latest_run = latest_run or {}
    entries = []
    if isinstance(workflows, dict):
        entries = workflows.get('workflows') or []
    code_workflows = []
    for wf in entries:
        text = f"{wf.get('name','')} {wf.get('path','')}".casefold()
        if 'codeql' in text or 'code-scanning' in text or 'code scanning' in text:
            code_workflows.append(wf)
    enabled = (((security_analysis or {}).get('code_scanning') or {}).get('status') or '').casefold() == 'enabled'
    if isinstance(alerts, list):
        if code_workflows and not latest_run:
            return {
                'status': 'NOT_VERIFIED', 'count': len(alerts),
                'reason': 'code-scanning workflow is configured but no completed run is available',
                'workflow': code_workflows[0].get('name'), 'latestRun': latest_run,
            }
        failed = latest_run.get('conclusion') in {'failure', 'cancelled', 'timed_out', 'action_required'}
        return {
            'status': 'SCAN_FAILED' if failed else ('FINDINGS' if alerts else 'NO_RESULTS'),
            'count': len(alerts),
            'reason': 'latest code-scanning workflow did not succeed' if failed else ('code-scanning alerts returned' if alerts else 'code-scanning API returned no open alerts'),
            'workflow': code_workflows[0].get('name') if code_workflows else None,
            'latestRun': latest_run,
        }
    err = str((alerts or {}).get('_error', 'unknown')) if isinstance(alerts, dict) else 'unknown'
    match = re.search(r'\(?HTTP\s+(\d+)\)?', err)
    http = int(match.group(1)) if match else None
    if http in {401, 403}:
        return {'status': 'UNAUTHORIZED', 'httpStatus': http, 'reason': 'code-scanning API is unauthorized', 'workflow': code_workflows[0].get('name') if code_workflows else None, 'latestRun': latest_run}
    if http == 404:
        if not enabled or not code_workflows:
            return {'status': 'NOT_ENABLED', 'httpStatus': 404, 'reason': 'code scanning is disabled or no code-scanning workflow exists', 'workflow': None, 'latestRun': latest_run}
        return {'status': 'NOT_VERIFIED', 'httpStatus': 404, 'reason': 'code scanning is configured but the alert endpoint is unavailable', 'workflow': code_workflows[0].get('name'), 'latestRun': latest_run}
    return {'status': 'NOT_VERIFIED', 'httpStatus': http, 'reason': err, 'workflow': code_workflows[0].get('name') if code_workflows else None, 'latestRun': latest_run}
