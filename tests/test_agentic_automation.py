import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github' / 'workflows'
CATALOG = ROOT / 'automation' / 'catalog' / 'workflow-catalog.json'
REPORTS = ROOT / 'automation' / 'reports'


def frontmatter(path):
    text = path.read_text()
    assert text.startswith('---\n')
    end = text.find('\n---\n', 4)
    assert end > 0
    return yaml.safe_load(text[4:end])


def trigger(data):
    return data.get('on', data.get(True, {}))


def test_catalog_and_locks_exist():
    catalog = json.loads(CATALOG.read_text())
    assert catalog['sourceCommit']
    for item in catalog['workflows']:
        assert (ROOT / item['path']).exists(), item
        assert (ROOT / item['lockPath']).exists(), item


def test_only_independent_review_uses_safe_pull_request_target():
    targets = [p for p in WORKFLOWS.glob('*.md') if 'pull_request_target' in p.read_text()]
    assert [p.name for p in targets] == ['independent-pr-review.md']
    text = (WORKFLOWS / 'independent-pr-review.md').read_text()
    assert 'github.event.pull_request.head.sha' not in text
    assert 'actions/checkout' not in text
    catalog = json.loads(CATALOG.read_text())
    assert 'githubnext/agentics/dependabot-pr-bundler.md' in catalog['missingOrInvalidTemplates']


def test_independent_review_is_read_only_and_bounded():
    data = frontmatter(WORKFLOWS / 'independent-pr-review.md')
    assert 'pull_request_target' in trigger(data)
    assert data['checkout'] is False
    assert data['permissions']['contents'] == 'read'
    assert data['permissions']['pull-requests'] == 'read'
    assert data['safe-outputs']['submit-pull-request-review']['max'] == 1
    assert data['safe-outputs']['create-pull-request-review-comment']['max'] <= 10
    assert data['max-turns'] <= 3


def test_security_review_has_no_write_permission():
    data = frontmatter(WORKFLOWS / 'security-review.md')
    assert 'schedule' in trigger(data)
    assert 'workflow_dispatch' in trigger(data)
    assert all(str(v) != 'write' for v in data['permissions'].values())
    assert 'create-code-scanning-alert' in data['safe-outputs']


def test_dependency_remediation_is_draft_only():
    data = frontmatter(WORKFLOWS / 'dependency-remediation.md')
    output = data['safe-outputs']['create-pull-request']
    assert output['draft'] is True
    assert output['max'] <= 3
    assert 'push-to-pull-request-branch' in data['safe-outputs']


def test_ci_doctor_is_main_branch_bounded():
    data = frontmatter(WORKFLOWS / 'ci-doctor.md')
    workflow_run = trigger(data)['workflow_run']
    assert workflow_run['branches'] == ['main']
    assert 'Governance self-checks' in workflow_run['workflows']


def test_all_agentic_workflows_have_budgets():
    for path in WORKFLOWS.glob('*.md'):
        if path.name.startswith('agent-engine-smoke'):
            continue
        data = frontmatter(path)
        assert data['max-turns'] <= 6, path
        assert data['max-ai-credits'] <= 100, path
        assert data['max-daily-ai-credits'] <= 200, path


def test_configured_provider_model_has_positive_explicit_budget_pricing():
    for name in ['ci-doctor', 'dependency-remediation', 'independent-pr-review', 'issue-triage', 'security-review']:
        data = frontmatter(WORKFLOWS / f'{name}.md')
        assert data['engine']['model'] == 'deepseek-flash'
        cost = data['models']['providers']['openai']['models'][data['engine']['model']]['cost']
        assert 0 < float(cost['cache_read']) <= float(cost['input']) <= float(cost['output'])
        assert data['max-ai-credits'] > 0
        assert data['max-daily-ai-credits'] > 0


def test_authorization_self_approval_is_rejected():
    from scripts import authorization_policy
    policy = json.loads((ROOT / 'policy' / 'r4-authorization.v1.json').read_text())
    policy = {**policy, 'status': 'ACTIVE', 'policyVersion': 'v1'}
    record = {
        'authorizationId': 'x', 'ownerIdentity': 'styayur', 'issuedBy': 'styayur',
        'scope': ['policy/evidence-matrix.v1.json'], 'policyVersion': 'v1',
        'commitSha': 'a' * 40, 'issuedAt': '2026-11-08T00:00:00Z',
        'expiresAt': '2099-01-01T00:00:00Z', 'signature': 'sig', 'selfIssued': True,
    }
    result = authorization_policy.validate_authorization(policy, ['policy/evidence-matrix.v1.json'], record)
    assert result['allowed'] is False
    assert result['classification'] == authorization_policy.OWNER_AUTHORIZATION_REQUIRED


def test_authorization_requires_matching_scope_and_valid_record():
    from scripts import authorization_policy
    policy = json.loads((ROOT / 'policy' / 'r4-authorization.v1.json').read_text())
    policy = {**policy, 'status': 'ACTIVE', 'policyVersion': 'v1'}
    record = {
        'authorizationId': 'x', 'ownerIdentity': 'styayur', 'issuedBy': 'independent-owner',
        'scope': ['policy/evidence-matrix.v1.json'], 'policyVersion': 'v1',
        'commitSha': 'a' * 40, 'issuedAt': '2026-11-08T00:00:00Z',
        'expiresAt': '2099-01-01T00:00:00Z', 'signature': 'sig', 'selfIssued': False,
    }
    assert authorization_policy.validate_authorization(policy, ['policy/evidence-matrix.v1.json'], record)['allowed'] is False
    assert authorization_policy.validate_authorization(policy, ['policy/rollout.json'], record)['allowed'] is False


def test_required_reports_exist_without_false_pass():
    required = ['workflow-catalog.json','deployment-coverage.json','agent-permission-audit.json','evidence-matrix.json','autonomous-repair-results.json','r4-authorization-policy.json','negative-acceptance.json','final-automation-readiness.json']
    for name in required:
        assert (REPORTS / name).exists(), name
    readiness = json.loads((REPORTS / 'final-automation-readiness.json').read_text())
    assert readiness['status'] != 'PASS'
