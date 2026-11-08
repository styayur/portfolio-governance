#!/usr/bin/env python3
"""Create or update one deterministic risk-register issue for Project sync."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

TITLE = 'Portfolio risk register: open Dependabot findings'


def run(args):
    p = subprocess.run(args, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return p.stdout


def markdown_text(value, limit=1200) -> str:
    text = str(value or 'not recorded').replace('\r', ' ').replace('\n', ' ').replace('`', "'")
    return text[:limit]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--repo', default='styayur/portfolio-governance')
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    records = report.get('records') or []
    critical = [r for r in records if str(r.get('priority', '')).upper() in {'P0', 'P1'}]
    coverage = report.get('coverage') or {}
    total_open = 'NOT_VERIFIED' if report.get('totalOpen') is None else report.get('totalOpen')
    unclassified = 'NOT_VERIFIED' if report.get('unclassified') is None else report.get('unclassified')
    lines = [f'<!-- portfolio-risk-register -->', f'# {TITLE}', '', f"Generated: `{report.get('generatedAt')}`", f"Open alerts: **{total_open}**", f"Unclassified blockers: **{unclassified}**", f"Coverage: **{coverage.get('status', 'NOT_VERIFIED')}** (scanned={coverage.get('repositoriesScanned', 'NOT_VERIFIED')}, errors={coverage.get('repositoriesErrored', 'NOT_VERIFIED')})", '', '## Disposition summary', '', '```json', json.dumps(report.get('countsByDisposition', {}), ensure_ascii=False, indent=2), '```', '']
    if report.get('errors'):
        lines += ['## Coverage errors', ''] + [f"- {markdown_text(item.get('repository'), 200)}: {markdown_text(item.get('reason'), 800)}" for item in report.get('errors', [])[:20]] + ['']
    lines += ['## Highest-priority findings', '']
    for r in critical[:40]:
        lines += [f"### {markdown_text(r.get('subject'), 300)}", f"- Package: `{markdown_text(r.get('package'), 200)}` ({markdown_text(r.get('ecosystem'), 100)})", f"- Disposition: **{markdown_text(r.get('status'), 80)}**", f"- Priority: **{markdown_text(r.get('priority'), 20)}**", f"- Dependency chain: {markdown_text(r.get('dependencyChain'))}", f"- Impact: {markdown_text(r.get('impact'))}", f"- Mitigation: {markdown_text(r.get('mitigation'))}", f"- Recheck: {markdown_text(r.get('recheckCondition'))}", f"- Evidence: {markdown_text(r.get('evidence'), 500)}", '']
    lines += ['## Boundary', '', 'This issue is a live, auditable projection of Dependabot findings. It does not dismiss, suppress, or auto-close alerts.']
    body = '\n'.join(lines) + '\n'
    found = json.loads(run(['gh', 'issue', 'list', '--repo', args.repo, '--state', 'all', '--search', f'in:title "{TITLE}"', '--limit', '5', '--json', 'number,title,state']))
    matching = next((x for x in found if x.get('title') == TITLE), None)
    labels = ['type:security', 'state:blocked', 'priority:P0']
    existing_labels = {item['name'] for item in json.loads(run(['gh', 'label', 'list', '--repo', args.repo, '--limit', '100', '--json', 'name']))}
    for label in labels:
        if label not in existing_labels:
            run(['gh', 'label', 'create', label, '--repo', args.repo, '--color', 'ededed', '--description', 'Portfolio governance label'])
    if matching:
        if matching.get('state', '').upper() == 'CLOSED':
            run(['gh', 'issue', 'reopen', str(matching['number']), '--repo', args.repo])
        run(['gh', 'issue', 'edit', str(matching['number']), '--repo', args.repo, '--body', body, '--add-label', ','.join(labels)])
        print(json.dumps({'status': 'UPDATED', 'issue': matching['number'], 'repo': args.repo}))
    else:
        out = run(['gh', 'issue', 'create', '--repo', args.repo, '--title', TITLE, '--body', body, '--label', ','.join(labels)]).strip()
        print(json.dumps({'status': 'CREATED', 'issue': out, 'repo': args.repo}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
