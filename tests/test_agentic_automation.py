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
    retired = [
        'independent-pr-review.md',
        'independent-pr-review.lock.yml',
        'security-review.md',
        'security-review.lock.yml',
        'dependency-remediation.md',
        'dependency-remediation.lock.yml',
        'ci-doctor.md',
        'ci-doctor.lock.yml',
        'issue-triage.md',
        'issue-triage.lock.yml',
    ]
    for name in retired:
        assert not (WORKFLOWS / name).exists(), name
    assert not any('pull_request_target' in path.read_text() for path in WORKFLOWS.glob('*.md'))
    catalog = json.loads(CATALOG.read_text())
    assert 'githubnext/agentics/dependabot-pr-bundler.md' in catalog['missingOrInvalidTemplates']


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
