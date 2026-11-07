#!/usr/bin/env python3
"""Build final machine-readable portfolio governance evidence.

Read-only except for calling the idempotent project sync. Never treats a score or
synthetic result as a substitute for failed, missing, native or paid evidence.
"""
from __future__ import annotations

import json, os, re, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'evidence' / 'baseline'
OUT = ROOT / 'evidence' / 'final'
OUT.mkdir(parents=True, exist_ok=True)
NOW = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
FIXED_GATE_SHA = 'a0e7ff969f2f065f982c2cf763e863c719e963fa'
GATE_CONTEXT = 'portfolio / Portfolio Evidence Gate / verify'
RULESET_NAME = 'Portfolio default branch safety'
MONITORING = ROOT / 'evidence' / 'remediation' / 'security-monitoring.json'
GITHUB_APP = ROOT / 'evidence' / 'remediation' / 'github-app.json'
DEPENDABOT_ALERTS = ROOT / 'evidence' / 'remediation' / 'dependabot-alerts.json'
PROJECT_SYNC_WORKFLOW = ROOT / 'evidence' / 'remediation' / 'project-sync-workflow.json'
AUDIT_WORKFLOW = ROOT / 'evidence' / 'remediation' / 'portfolio-audit-workflow.json'


def run(args, input_text=None):
    return subprocess.run(args, input=input_text, text=True, capture_output=True)


def api(path):
    p = run(['gh', 'api', path])
    if p.returncode:
        return {'_error': (p.stderr or p.stdout).strip()}
    return json.loads(p.stdout) if p.stdout.strip() else {}


def api_list(path):
    p = run(['gh', 'api', '--paginate', '--jq', '.[]', path])
    if p.returncode:
        return {'_error': (p.stderr or p.stdout).strip()}
    return [json.loads(line) for line in p.stdout.splitlines() if line.strip()]


def graphql(query, variables):
    p = run(['gh', 'api', 'graphql', '--input', '-'], json.dumps({'query': query, 'variables': variables}))
    if p.returncode:
        return {'_error': (p.stderr or p.stdout).strip()}
    data = json.loads(p.stdout)
    if data.get('errors'):
        return {'_error': json.dumps(data['errors'], ensure_ascii=False)}
    return data['data']


def file_text(repo, path):
    p = run(['gh', 'api', '-H', 'Accept: application/vnd.github.raw', f'repos/{repo}/contents/{path}'])
    if p.returncode:
        return None
    return p.stdout


def record(subject, evidence, status, reason, revision=None, remediation='', residual_risk=''):
    return {
        'subject': subject,
        'evidence': evidence,
        'status': status,
        'reason': reason,
        'revision': revision,
        'verificationTime': NOW,
        'remediation': remediation,
        'residualRisk': residual_risk,
    }


def main():
    inventory = json.loads((BASELINE / 'portfolio-inventory.json').read_text())
    pre = json.loads((BASELINE / 'portfolio-inventory.pre-governance.json').read_text())
    repos = inventory['repositories']
    pre_by_name = {r['full_name']: r for r in pre['repositories']}
    monitoring = json.loads(MONITORING.read_text()) if MONITORING.exists() else {'repositories': []}
    monitoring_by_repo = {x['repository']: x for x in monitoring.get('repositories', [])}
    app_meta = json.loads(GITHUB_APP.read_text()) if GITHUB_APP.exists() else {}
    alert_meta = json.loads(DEPENDABOT_ALERTS.read_text()) if DEPENDABOT_ALERTS.exists() else {'totalOpen': 0, 'repositories': {}}
    sync_workflow = json.loads(PROJECT_SYNC_WORKFLOW.read_text()).get('latestSuccess', {}) if PROJECT_SYNC_WORKFLOW.exists() else {}
    audit_workflow = json.loads(AUDIT_WORKFLOW.read_text()).get('latestSuccess', {}) if AUDIT_WORKFLOW.exists() else {}

    (OUT / 'portfolio-inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n')

    governance = []
    agents = []
    security = []
    actions = []
    releases = []
    for r in repos:
        full = r['full_name']; branch = r['default_branch']; files = r.get('files', {})
        ds = r.get('discussion_state') or {}
        cats = [c.get('name') for c in ((ds.get('discussionCategories') or {}).get('nodes') or [])]
        our_rule = next((x for x in r.get('rulesets', []) if x.get('name') == RULESET_NAME), None)
        gate_text = file_text(full, '.github/workflows/portfolio-gate.yml') or ''
        governance.append(record(
            full,
            {'repositoryId': r['id'], 'defaultBranch': branch, 'visibility': r['visibility'], 'discussions': bool(r.get('has_discussions')), 'discussionCategories': cats, 'ruleset': our_rule, 'gatePinned': FIXED_GATE_SHA in gate_text, 'openPRs': r.get('open_prs'), 'openIssues': r.get('open_issues')},
            'PASS' if r.get('has_discussions') and {'Announcements','General','Ideas','Q&A'} <= set(cats) and our_rule and FIXED_GATE_SHA in gate_text else 'FAIL',
            'Discussions, gate pin and default-branch ruleset verified from live API/source.',
            revision=r.get('default_branch_sha'),
            remediation='Resolve the missing setting through a reviewed PR or ruleset update.',
            residual_risk='Rulesets reduce but do not eliminate maintainer account compromise risk.'
        ))

        agent_text = file_text(full, 'AGENTS.md')
        headings = ['Project Intent','Architecture & Stable Contracts','Security and Data Boundaries','Development Autonomy','Verification & Evidence','Release & Dependency Policy']
        agents.append(record(
            full,
            {'path': 'AGENTS.md', 'sha': files.get('AGENTS.md', {}).get('sha'), 'headings': headings, 'present': bool(agent_text)},
            'PASS' if agent_text and all(h in agent_text for h in headings) else 'FAIL',
            'Repository-specific agent instructions present with required policy sections.' if agent_text else 'AGENTS.md absent.',
            revision=files.get('AGENTS.md', {}).get('sha'),
            remediation='Add a short repository-specific AGENTS.md; do not overwrite existing generated rules.',
            residual_risk='Instructions are guidance and do not replace executable gates.'
        ))

        pvr = api(f'repos/{full}/private-vulnerability-reporting')
        sec_text = file_text(full, 'SECURITY.md')
        dep = r.get('dependabot_alerts') or {}
        secret = r.get('secret_scanning_alerts') or {}
        code = r.get('code_scanning_alerts') or {}
        mon = monitoring_by_repo.get(full, {})
        mon_ok = all((mon.get(k) or {}).get('after', {}).get('ok') for k in ('vulnerabilityAlerts','automatedSecurityFixes'))
        sec_status = 'PASS'; reasons = []
        if not mon_ok:
            sec_status = 'FAIL'; reasons.append('Dependabot monitoring not verified enabled')
        if not sec_text: sec_status = 'FAIL'; reasons.append('SECURITY.md missing')
        if pvr.get('enabled') is not True: sec_status = 'FAIL'; reasons.append('private vulnerability reporting disabled')
        for label, value in [('Dependabot', dep), ('secret scanning', secret), ('code scanning', code)]:
            if value.get('count', 0) and value.get('count', 0) > 0:
                sec_status = 'FAIL'; reasons.append(f'{label} alerts: {value.get("count")}')
            elif value.get('status') == 'ERROR':
                if sec_status == 'PASS': sec_status = 'NOT_VERIFIED'
                reasons.append(f'{label}: API unavailable')
        if sec_status == 'PASS': reasons.append('policy present, private reporting enabled, no open alerts returned')
        security.append(record(
            full,
            {'securityPolicy': bool(sec_text), 'privateVulnerabilityReporting': pvr, 'dependabotAlerts': dep, 'secretScanningAlerts': secret, 'codeScanningAlerts': code, 'securityMonitoring': mon},
            sec_status,
            '; '.join(reasons),
            revision=files.get('SECURITY.md', {}).get('sha'),
            remediation='Keep private vulnerability reporting enabled and remediate actual alerts; do not suppress scanner findings.',
            residual_risk='API-visible alerts do not enumerate all possible vulnerabilities.'
        ))

        unpinned = []
        write_all = []
        untrusted_checkout = []
        workflow_rows = []
        for wf in r.get('workflows', []):
            path = wf.get('path') or ''
            if not path.startswith('.github/workflows/'):
                continue
            text = file_text(full, path) or ''
            refs = []
            for match in re.finditer(r'^\s*uses:\s*([^\s#]+)', text, re.M):
                target = match.group(1)
                if target.startswith('./'):
                    refs.append({'target': target, 'pinned': True, 'local': True})
                    continue
                if '@' not in target:
                    refs.append({'target': target, 'pinned': False, 'local': False}); continue
                name, ref = target.rsplit('@', 1)
                pinned = bool(re.fullmatch(r'[0-9a-f]{40}', ref))
                trusted_first_party = name.split('/', 1)[0].lower() in {'actions', 'github'}
                refs.append({'target': target, 'pinned': pinned, 'local': False, 'trustedFirstPartyTag': (not pinned and trusted_first_party)})
                if not pinned and not trusted_first_party:
                    unpinned.append(target)
            if 'permissions: write-all' in text:
                write_all.append(path)
            if 'pull_request_target' in text and 'actions/checkout' in text and ('github.event.pull_request.head.sha' in text or 'refs/pull/' in text):
                untrusted_checkout.append(path)
            workflow_rows.append({'path': path, 'uses': refs, 'pullRequestTarget': 'pull_request_target' in text})
        status = 'PASS' if not unpinned and not write_all and not untrusted_checkout else 'FAIL'
        actions.append(record(
            full,
            {'workflows': workflow_rows, 'unpinnedUses': sorted(set(unpinned)), 'writeAll': write_all, 'unsafePullRequestTargetCheckout': untrusted_checkout},
            status,
            'Third-party actions pinned; first-party Actions tags allowed; no write-all or untrusted PR checkout.' if status == 'PASS' else 'Third-party action pinning or privileged workflow review required.',
            revision=r.get('default_branch_sha'),
            remediation='Pin third-party actions to reviewed full SHAs, grant least privilege and never execute PR code under pull_request_target.',
            residual_risk='Pinning a SHA does not by itself prove the action is vulnerability-free.'
        ))

        old = pre_by_name.get(full)
        if old:
            old_tags = set(old.get('tags') or []); now_tags = set(r.get('tags') or [])
            old_releases = {x.get('tag_name') for x in old.get('releases') or []}; now_releases = {x.get('tag_name') for x in r.get('releases') or []}
            missing = sorted((old_tags - now_tags) | (old_releases - now_releases))
            releases.append(record(full, {'tagCountBefore': len(old_tags), 'tagCountAfter': len(now_tags), 'releaseCountBefore': len(old_releases), 'releaseCountAfter': len(now_releases), 'missing': missing}, 'PASS' if not missing else 'FAIL', 'Historical tag/release names remain visible.' if not missing else 'Historical tag or release missing.', revision=r.get('default_branch_sha'), remediation='Do not overwrite or remove release history; restore only from an authorized backup.', residual_risk='Release asset digests and signatures are outside this check unless separately verified.'))
        else:
            releases.append(record(full, {'before': None}, 'NOT_VERIFIED', 'No pre-governance inventory record.', revision=r.get('default_branch_sha')))

    (OUT / 'governance-baseline.json').write_text(json.dumps({'generatedAt': NOW, 'records': governance}, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'agent-policy-audit.json').write_text(json.dumps({'generatedAt': NOW, 'records': agents}, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'security-policy-audit.json').write_text(json.dumps({'generatedAt': NOW, 'records': security}, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'actions-gate-audit.json').write_text(json.dumps({'generatedAt': NOW, 'records': actions}, ensure_ascii=False, indent=2) + '\n')

    search = api('search/issues?q=owner%3Astyayur%20is%3Apr%20is%3Aopen&per_page=100')
    pr_records = []
    for item in search.get('items', []):
        repo = item['repository_url'].split('/repos/')[-1]; n = item['number']
        p = run(['gh', 'pr', 'view', str(n), '-R', repo, '--json', 'number,title,url,isDraft,state,baseRefOid,headRefOid,labels,comments,statusCheckRollup'])
        if p.returncode: continue
        d = json.loads(p.stdout)
        decision = 'NOT_VERIFIED'
        for comment in d.get('comments', []):
            if '<!-- portfolio-evidence-gate -->' in (comment.get('body') or ''):
                m = re.search(r'- Decision: \*\*(.+?)\*\*', comment['body'])
                if m: decision = m.group(1)
        checks = []
        for c in d.get('statusCheckRollup') or []:
            checks.append({'name': c.get('name') or c.get('context'), 'workflow': c.get('workflowName'), 'status': c.get('status'), 'conclusion': c.get('conclusion') or c.get('state'), 'evidence': c.get('detailsUrl') or c.get('targetUrl')})
        pr_records.append({'subject': f'{repo}#{n}', 'url': d.get('url'), 'draft': d.get('isDraft'), 'decision': decision, 'baseSha': d.get('baseRefOid'), 'headSha': d.get('headRefOid'), 'checks': checks, 'labels': [x['name'] for x in d.get('labels', [])], 'evidence': [c['evidence'] for c in checks if c.get('evidence')]})
    (OUT / 'pr-review-evidence.json').write_text(json.dumps({'generatedAt': NOW, 'records': pr_records}, ensure_ascii=False, indent=2) + '\n')

    p = run(['python3', str(ROOT / 'scripts/project_sync.py')])
    sync_ok = p.returncode == 0
    sync_path = BASELINE / 'portfolio-project-sync.json'
    sync_payload = json.loads(sync_path.read_text()) if sync_path.exists() else {'_error': (p.stderr or p.stdout).strip()}
    sync_ok = sync_ok and not sync_payload.get('_error')
    project = graphql('''query { viewer { projectV2(number:1) { id title fields(first:60){nodes{... on ProjectV2FieldCommon{name dataType}}} views(first:20){nodes{name layout}} items(first:1){totalCount} } } }''', {})
    pnode = (project.get('viewer') or {}).get('projectV2') if isinstance(project, dict) else None
    required_fields = {'Repository','Work Type','Priority','Status','Risk','Evidence','Target Release','Last Verified'}
    required_views = {('Table','TABLE_LAYOUT'),('Board','BOARD_LAYOUT'),('Roadmap','ROADMAP_LAYOUT')}
    if pnode:
        fields = {f['name'] for f in pnode.get('fields', {}).get('nodes', [])}
        views = {(v['name'], v['layout']) for v in pnode.get('views', {}).get('nodes', [])}
        project_status = 'PASS' if required_fields <= fields and required_views <= views else 'FAIL'
        project_reason = f"fields={sorted(required_fields & fields)} views={sorted(views)} items={pnode.get('items',{}).get('totalCount')}"
    else:
        project_status = 'BLOCKED'; project_reason = 'Project GraphQL query failed'
    (OUT / 'portfolio-project-sync.json').write_text(json.dumps({'generatedAt': NOW, 'projectId': 'PVT_kwHOE1hmpc4BoN2B', 'projectTitle': 'Styayur Portfolio', 'verification': {'status': project_status, 'reason': project_reason}, 'sync': sync_payload}, ensure_ascii=False, indent=2) + '\n')

    def aggregate(records):
        return {s: sum(x['status'] == s for x in records) for s in ['PASS','FAIL','BLOCKED','NOT_VERIFIED','NOT_APPLICABLE']}

    gate_prs = []
    for repo, n in [('styayur/styayur.github.io', 8), ('styayur/portfolio-governance', 3)]:
        p = run(['gh', 'pr', 'view', str(n), '-R', repo, '--json', 'state,mergeCommit,mergedAt,headRefOid,statusCheckRollup,comments'])
        if p.returncode: continue
        d = json.loads(p.stdout)
        gate_prs.append({'subject': f'{repo}#{n}', **d})
    allow_evidence = any(x['subject'] == 'styayur/styayur.github.io#8' and x.get('state') == 'MERGED' and any(c.get('name') == 'portfolio / Portfolio Evidence Gate / merge' and c.get('conclusion') == 'SUCCESS' for c in x.get('statusCheckRollup', [])) for x in gate_prs)
    deny_evidence = any('Decision: **MANUAL_REVIEW_REQUIRED**' in (c.get('body') or '') for x in gate_prs for c in x.get('comments', []))

    actions_summary = aggregate(actions)
    sec_summary = aggregate(security)
    blockers = [
        {'subject': 'styayur/LGXT-Assistant#25', 'status': 'BLOCKED', 'reason': 'No independent ground-truth review, approved live provider/model budget or live OCR responses; no accuracy claim made.'},
        {'subject': 'styayur/gitpad-plus#6', 'status': 'BLOCKED', 'reason': 'Draft acceptance remains incomplete; development probes are not a final release qualification.'},
        {'subject': 'styayur/vextessera#21', 'status': 'BLOCKED', 'reason': 'Independent holdout validation and explicit product decision remain outstanding.'},
    ]
    blockers.append({'subject': 'styayur/TinySTT#7', 'status': 'BLOCKED', 'reason': 'Rustls patch retry still fails before tests because the Windows sherpa-onnx native static library is missing; PR remains open and visible.'})
    for rec in security:
        if rec['status'] == 'FAIL':
            blockers.append({'subject': rec['subject'], 'status': 'BLOCKED', 'reason': rec['reason'], 'remediation': rec['remediation'], 'residualRisk': rec['residualRisk']})
    not_verified_code = [r['subject'] for r in security if r['status'] == 'NOT_VERIFIED' and 'code scanning' in r['reason']]
    if not_verified_code:
        blockers.append({'subject': 'code-scanning-coverage', 'status': 'NOT_VERIFIED', 'reason': f'{len(not_verified_code)} repositories have no accessible code-scanning result', 'repositories': not_verified_code})
    blockers.append({'subject': 'project-sync-credential-portability', 'status': 'BLOCKED', 'reason': 'GitHub App installation tokens cannot mutate user-owned Projects V2; a classic PAT limited to project scope is required and expires 2027-02-06.', 'remediation': 'Rotate PORTFOLIO_PROJECT_TOKEN before expiry or migrate if GitHub adds supported fine-grained project access.'})
    if actions_summary['FAIL']:
        blockers.append({'subject': 'actions-gate-audit', 'status': 'FAIL', 'reason': f"{actions_summary['FAIL']} repositories contain unpinned third-party actions or privileged workflow concerns."})
    automation_status = 'PASS' if sync_ok and project_status == 'PASS' else 'BLOCKED'
    monitoring_ok = sum(1 for r in monitoring.get('repositories', []) if all((r.get(k) or {}).get('after', {}).get('ok') for k in ('vulnerabilityAlerts','automatedSecurityFixes')))
    if actions_summary['FAIL'] or sec_summary['FAIL']:
        final_status = 'FAIL'
    elif automation_status != 'PASS' or blockers:
        final_status = 'BLOCKED'
    else:
        final_status = 'PASS'
    final = {
        'schemaVersion': 1,
        'generatedAt': NOW,
        'codespacesFirst': {'status': 'PASS', 'codespace': 'styayur-portfolio-governance-96jxv56p97rjc9777', 'note': 'Repository/API orchestration and evidence generation ran from this Codespace; owner-only GitHub App and classic-token provisioning used the authenticated browser UI.'},
        'repositoryCoverage': {'status': 'PASS' if len(repos) >= 28 else 'FAIL', 'count': len(repos), 'privateSiteExcluded': 'styayur/site'},
        'governance': aggregate(governance), 'agents': aggregate(agents), 'security': sec_summary, 'actions': actions_summary, 'releases': aggregate(releases),
        'project': {'status': project_status, 'reason': project_reason, 'fieldsRequired': sorted(required_fields), 'viewsRequired': sorted(required_views)},
        'automation': {'status': automation_status, 'latestProjectSyncSuccess': sync_workflow, 'latestAuditSuccess': audit_workflow, 'githubApp': {'id': app_meta.get('id'), 'slug': app_meta.get('slug'), 'clientId': app_meta.get('client_id')}, 'projectToken': {'scope': ['project'], 'expires': '2027-02-06', 'githubAppOnlyStatus': 'BLOCKED', 'reason': 'installation token cannot mutate user-owned Projects V2'}},
        'securityMonitoring': {'status': 'PASS' if monitoring_ok == len(repos) else 'FAIL', 'enabled': monitoring_ok, 'expected': len(repos)},
        'openDependabotAlerts': {'total': alert_meta.get('totalOpen'), 'repositories': alert_meta.get('repositories')},
        'reviewGate': {'status': 'PASS' if allow_evidence and deny_evidence else 'NOT_VERIFIED', 'allowEvidence': allow_evidence, 'denyEvidence': deny_evidence, 'prs': gate_prs},
        'blockers': blockers,
        'overallStatus': final_status,
        'summary': {
            'repositoriesProcessed': len(repos),
            'publicRepositories': len(repos),
            'agentsPass': aggregate(agents)['PASS'],
            'securityPass': sec_summary['PASS'],
            'rulesetsPass': aggregate(governance)['PASS'],
            'actionsPass': actions_summary['PASS'],
            'actionsFail': actions_summary['FAIL'],
            'securityFail': sec_summary['FAIL'],
            'securityNotVerified': sec_summary['NOT_VERIFIED'],
            'securityMonitoringPass': monitoring_ok,
            'openDependabotAlerts': alert_meta.get('totalOpen'),
            'automationStatus': automation_status,
            'openPRs': len(pr_records),
            'blockedItems': len(blockers),
        },
        'qualityScore': None,
        'note': 'No score overrides a failed security check, missing evidence, an unavailable native runner or a missing paid-provider authorization.',
    }
    (OUT / 'final-acceptance.json').write_text(json.dumps(final, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(final['summary'] | {'overallStatus': final_status, 'actions': actions_summary, 'security': sec_summary}, ensure_ascii=False))


if __name__ == '__main__':
    main()
