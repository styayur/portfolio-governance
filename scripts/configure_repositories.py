#!/usr/bin/env python3
"""Idempotently configure public repositories without changing private site."""
from __future__ import annotations

import json, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / 'evidence/baseline/portfolio-inventory.json'
OUT = ROOT / 'evidence/baseline/settings-mutations.json'


def run(args):
    p = subprocess.run(args, text=True, capture_output=True)
    return p


def api(path, method='GET', fields=None):
    args = ['gh', 'api', '-X', method, path]
    for key, value in (fields or {}).items():
        args += ['-f', f'{key}={value}']
    p = run(args)
    if p.returncode:
        return {'_error': (p.stderr or p.stdout).strip()}
    return json.loads(p.stdout) if p.stdout.strip() else {}


def graphql(query, variables):
    body = json.dumps({'query': query, 'variables': variables})
    p = subprocess.run(['gh', 'api', 'graphql', '--input', '-'], input=body, text=True, capture_output=True)
    if p.returncode:
        return {'_error': (p.stderr or p.stdout).strip()}
    data = json.loads(p.stdout)
    if data.get('errors'):
        return {'_error': json.dumps(data['errors'], ensure_ascii=False)}
    return data['data']


def main():
    inventory = json.loads(INVENTORY.read_text())
    labels_policy = json.loads((ROOT / 'policy/labels.json').read_text())['labels']
    records = []
    for repo in inventory['repositories']:
        full = repo['full_name']
        if full == 'styayur/site':
            continue
        before = api(f'repos/{full}')
        patch = api(f'repos/{full}', 'PATCH', {
            'has_discussions': 'true',
            'allow_auto_merge': 'true',
            'allow_squash_merge': 'true',
        })
        labels = api(f'repos/{full}/labels?per_page=100')
        existing = {item['name'].casefold(): item for item in labels} if isinstance(labels, list) else {}
        created, preserved = [], []
        for label in labels_policy:
            if label['name'].casefold() in existing:
                preserved.append(label['name'])
                continue
            result = api(f'repos/{full}/labels', 'POST', {
                'name': label['name'], 'color': label['color'], 'description': label['description']
            })
            if result.get('_error'):
                records_error = result['_error']
            else:
                created.append(label['name'])
        categories = graphql(
            'query($owner:String!,$name:String!){repository(owner:$owner,name:$name){hasDiscussionsEnabled discussionCategories(first:50){nodes{name slug emoji}} discussions(first:1){totalCount}}}',
            {'owner': 'styayur', 'name': repo['name']},
        )
        after = api(f'repos/{full}')
        records.append({
            'subject': full,
            'before': {'has_discussions': before.get('has_discussions'), 'allow_auto_merge': before.get('allow_auto_merge'), 'allow_squash_merge': before.get('allow_squash_merge')},
            'after': {'has_discussions': after.get('has_discussions'), 'allow_auto_merge': after.get('allow_auto_merge'), 'allow_squash_merge': after.get('allow_squash_merge')},
            'labelsCreated': created,
            'labelsPreserved': preserved,
            'discussions': categories,
            'status': 'PASS' if after.get('has_discussions') is True and after.get('allow_auto_merge') is True else 'FAIL',
            'verifiedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        })
        print(full, records[-1]['status'], 'labels+', len(created), 'categories', [n.get('name') for n in ((categories.get('repository') or {}).get('discussionCategories') or {}).get('nodes', [])], flush=True)
    OUT.write_text(json.dumps({'records': records}, ensure_ascii=False, indent=2) + '\n')
    print('wrote', OUT)


if __name__ == '__main__':
    main()
