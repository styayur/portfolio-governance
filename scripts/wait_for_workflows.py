#!/usr/bin/env python3
"""Wait until all named workflows have a successful run for one exact main SHA."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


def run(args):
    p = subprocess.run(args, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return p.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--workflows', required=True)
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--poll', type=int, default=15)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    wanted = [x.strip() for x in args.workflows.split(',') if x.strip()]
    started = time.time()
    while True:
        raw_runs = run(['gh', 'api', '--paginate', '--jq', '.workflow_runs[] | {databaseId: .id, workflowName: .name, headSha: .head_sha, status: .status, conclusion: .conclusion, createdAt: .created_at, url: .html_url, event: .event}', f'repos/{args.repo}/actions/runs?head_sha={args.sha}&per_page=100'])
        runs = [json.loads(line) for line in raw_runs.splitlines() if line.strip()]
        by_workflow = {}
        for item in runs:
            if item.get('headSha') != args.sha or item.get('workflowName') not in wanted:
                continue
            if item['workflowName'] not in by_workflow or item.get('createdAt', '') > by_workflow[item['workflowName']].get('createdAt', ''):
                by_workflow[item['workflowName']] = item
        failures = {name: item for name, item in by_workflow.items() if item.get('status') == 'completed' and item.get('conclusion') != 'success'}
        missing = [name for name in wanted if name not in by_workflow]
        pending = [name for name, item in by_workflow.items() if item.get('status') != 'completed']
        if failures:
            result = {'status': 'FAIL', 'reason': 'one or more required workflows failed', 'sha': args.sha, 'required': wanted, 'runs': by_workflow}
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(result, ensure_ascii=False)); return 2
        if not missing and not pending:
            result = {'status': 'PASS', 'reason': 'all required workflows completed successfully for exact SHA', 'sha': args.sha, 'required': wanted, 'runs': by_workflow}
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(result, ensure_ascii=False)); return 0
        if time.time() - started >= args.timeout:
            result = {'status': 'BLOCKED', 'reason': 'timeout waiting for required workflows', 'sha': args.sha, 'required': wanted, 'missing': missing, 'pending': pending, 'runs': by_workflow}
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(result, ensure_ascii=False)); return 3
        time.sleep(args.poll)


if __name__ == '__main__':
    raise SystemExit(main())
