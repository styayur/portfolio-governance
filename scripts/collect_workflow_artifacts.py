#!/usr/bin/env python3
"""Download exact-SHA workflow artifacts needed by final acceptance.

The collector fails closed if a required workflow run or artifact is missing.
It never substitutes a committed snapshot for a workflow artifact.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ARTIFACTS = {
    'Portfolio risk operations': ('portfolio-risk-operations-{run_id}', 'evidence/risk', ('dependabot-risk-disposition.json', 'pat-rotation.json')),
    'Portfolio audit': ('portfolio-audit-{run_id}', 'evidence/baseline', ('portfolio-inventory.json',)),
    'Portfolio project sync': ('portfolio-project-sync-{run_id}', 'evidence/baseline', ('portfolio-project-sync.json',)),
}


def run(args):
    return subprocess.run(args, text=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--completion', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('evidence/final/workflow-artifacts.json'))
    args = parser.parse_args()
    completion = json.loads(args.completion.read_text())
    if completion.get('status') != 'PASS':
        raise SystemExit(f"required workflows are not complete: {completion.get('status')}")
    runs = completion.get('runs') or {}
    records = []
    failures = []
    for workflow, (name_template, destination, required_files) in ARTIFACTS.items():
        info = runs.get(workflow)
        if not info:
            failures.append(f'{workflow}: run missing')
            continue
        run_id = info.get('databaseId')
        if not run_id:
            failures.append(f'{workflow}: run id missing')
            continue
        dest = Path(destination)
        name = name_template.format(run_id=run_id)
        scratch = Path(tempfile.mkdtemp(prefix=f'portfolio-artifact-{workflow.replace(" ", "-")}-'))
        try:
            proc = run(['gh', 'run', 'download', str(run_id), '--repo', args.repo, '--name', name, '--dir', str(scratch)])
            if proc.returncode:
                failures.append(f'{workflow}: artifact {name} unavailable: {(proc.stderr or proc.stdout).strip()}')
                continue
            missing = []
            for item in required_files:
                matches = list(scratch.rglob(item))
                if not matches:
                    missing.append(item)
                    continue
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(matches[0], dest / item)
            if missing:
                failures.append(f'{workflow}: artifact {name} missing {missing}')
                continue
            records.append({'workflow': workflow, 'runId': run_id, 'artifact': name, 'destination': str(dest), 'files': list(required_files)})
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    result = {
        'schemaVersion': 1,
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'status': 'PASS' if not failures else 'NOT_VERIFIED',
        'sha': completion.get('sha'),
        'records': records,
        'failures': failures,
        'note': 'Artifacts are downloaded from the exact successful workflow runs; no committed snapshot is used as a substitute.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'sha': result['sha'], 'downloaded': len(records), 'failures': failures}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == '__main__':
    raise SystemExit(main())
