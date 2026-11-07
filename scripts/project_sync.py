#!/usr/bin/env python3
"""Mirror live public issues and PRs into the Styayur Portfolio project."""
from __future__ import annotations

import json, os, subprocess, time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = os.environ.get('PORTFOLIO_PROJECT_ID', 'PVT_kwHOE1hmpc4BoN2B')
OUT = ROOT / 'evidence/baseline/portfolio-project-sync.json'


def gql(query, variables):
    p = subprocess.run(['gh', 'api', 'graphql', '--input', '-'], input=json.dumps({'query': query, 'variables': variables}), text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip())
    data = json.loads(p.stdout)
    if data.get('errors'):
        raise RuntimeError(json.dumps(data['errors'], ensure_ascii=False))
    return data['data']


def project_snapshot():
    return gql('''query($id:ID!){ node(id:$id){ ... on ProjectV2 {
      id title fields(first:60){nodes{ ... on ProjectV2FieldCommon{id name dataType}
        ... on ProjectV2SingleSelectField{id name options{id name}} }}
      items(first:100){nodes{id type content{ __typename
        ... on Issue{id number title state url repository{nameWithOwner} labels(first:20){nodes{name}} milestone{title}}
        ... on PullRequest{id number title state isDraft url repository{nameWithOwner} labels(first:20){nodes{name}} milestone{title}}
        ... on DraftIssue{id title}
      } fieldValues(first:30){nodes{ ... on ProjectV2ItemFieldSingleSelectValue{name field{... on ProjectV2SingleSelectField{name}}}
        ... on ProjectV2ItemFieldTextValue{text field{... on ProjectV2FieldCommon{name}}}
        ... on ProjectV2ItemFieldDateValue{date field{... on ProjectV2FieldCommon{name}}} }} }}
    } } }''', {'id': PROJECT_ID})['node']


def search_open():
    q = 'owner:styayur is:open'
    p = subprocess.run(['gh', 'api', '-X', 'GET', 'search/issues', '-f', f'q={q}', '-f', 'per_page=100'], text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return json.loads(p.stdout).get('items', [])


def update_field(item_id, field, option=None, text=None, day=None):
    inp = {'projectId': PROJECT_ID, 'itemId': item_id, 'fieldId': field['id']}
    if option:
        inp['value'] = {'singleSelectOptionId': option}
    elif day:
        inp['value'] = {'date': day}
    else:
        inp['value'] = {'text': text or ''}
    gql('''mutation($input:UpdateProjectV2ItemFieldValueInput!){updateProjectV2ItemFieldValue(input:$input){projectV2Item{id}}}''', {'input': inp})


def label_names(content):
    return {node['name'] for node in ((content.get('labels') or {}).get('nodes') or [])}


def pick_option(fields, field_name, value):
    for field in fields.values():
        if field['name'] == field_name:
            for option in field.get('options', []):
                if option['name'] == value:
                    return option['id']
    return None


def describe(content):
    labels = label_names(content)
    text = ((content.get('title') or '') + ' ' + ' '.join(labels)).casefold()
    if any(x in labels for x in ('type:security', 'type:bug', 'type:feature', 'type:maintenance')):
        work_type = next(x.split(':', 1)[1].title() for x in labels if x.startswith('type:'))
    elif 'security' in text or 'cve' in text or 'vulnerab' in text:
        work_type = 'Security'
    elif any(x in text for x in ('dependabot', 'bump', 'chore', 'deps', 'maintenance')):
        work_type = 'Maintenance'
    elif any(x in text for x in ('fix', 'bug', 'incorrect', 'failure', 'broken')):
        work_type = 'Bug'
    else:
        work_type = 'Feature'
    priority = next((x.split(':', 1)[1] for x in labels if x.startswith('priority:')), 'P2')
    if content.get('state') in ('CLOSED', 'MERGED'):
        status = 'Done'
    elif 'state:blocked' in labels or 'state:needs-evidence' in labels:
        status = 'Blocked'
    elif content.get('__typename') == 'PullRequest':
        status = 'Verification'
    else:
        status = 'Backlog'
    risk = 'R2' if content.get('__typename') == 'PullRequest' else None
    return {'status': status, 'type': work_type, 'priority': priority, 'risk': risk, 'evidence': content.get('url'), 'target': (content.get('milestone') or {}).get('title') or None}


def main():
    snapshot = project_snapshot()
    fields = {f['name']: f for f in snapshot['fields']['nodes']}
    existing = {}
    for item in snapshot['items']['nodes']:
        content = item.get('content') or {}
        if content.get('url'):
            existing[content['url']] = item
    public = {r['full_name'] for r in json.loads((ROOT / 'evidence/baseline/portfolio-inventory.json').read_text())['repositories']}
    added = []
    for issue in search_open():
        url = issue.get('html_url')
        if not url or url in existing:
            continue
        repo = issue.get('repository_url', '').split('/repos/')[-1]
        if repo not in public:
            continue
        node_id = issue.get('node_id')
        if not node_id:
            continue
        result = gql('''mutation($input:AddProjectV2ItemByIdInput!){addProjectV2ItemById(input:$input){item{id}}}''', {'input': {'projectId': PROJECT_ID, 'contentId': node_id}})
        added.append({'url': url, 'itemId': result['addProjectV2ItemById']['item']['id']})
    snapshot = project_snapshot()
    fields = {f['name']: f for f in snapshot['fields']['nodes']}
    status_option = {o['name']: o['id'] for o in fields['Status'].get('options', [])}
    verified = date.today().isoformat()
    records = []
    for item in snapshot['items']['nodes']:
        content = item.get('content') or {}
        if content.get('__typename') not in {'Issue', 'PullRequest'} or not content.get('url'):
            continue
        values = describe(content)
        record = {'subject': content['url'], 'itemId': item['id'], 'repository': (content.get('repository') or {}).get('nameWithOwner'), 'status': 'PASS'}
        try:
            if values['status'] in status_option:
                update_field(item['id'], fields['Status'], option=status_option[values['status']])
            if 'Work Type' in fields:
                option = pick_option(fields, 'Work Type', values['type'])
                if option: update_field(item['id'], fields['Work Type'], option=option)
            if 'Priority' in fields:
                option = pick_option(fields, 'Priority', values['priority'])
                if option: update_field(item['id'], fields['Priority'], option=option)
            if values['risk'] and 'Risk' in fields:
                option = pick_option(fields, 'Risk', values['risk'])
                if option: update_field(item['id'], fields['Risk'], option=option)
            if 'Evidence' in fields:
                update_field(item['id'], fields['Evidence'], text=values['evidence'] or '')
            if values['target'] and 'Target Release' in fields:
                update_field(item['id'], fields['Target Release'], text=values['target'])
            if 'Last Verified' in fields:
                update_field(item['id'], fields['Last Verified'], day=verified)
        except Exception as exc:
            record['status'] = 'BLOCKED'
            record['reason'] = str(exc)
        records.append(record)
    OUT.write_text(json.dumps({'projectId': PROJECT_ID, 'projectTitle': snapshot.get('title'), 'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'added': added, 'records': records}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'project': snapshot.get('title'), 'added': len(added), 'synced': len(records), 'blocked': sum(r['status']=='BLOCKED' for r in records)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
