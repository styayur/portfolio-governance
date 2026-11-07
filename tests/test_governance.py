import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import evidence_gate, independent_review, risk_classify


def context(**overrides):
    value = {
        'repository': 'styayur/example',
        'repositoryId': 1,
        'prNumber': 7,
        'title': 'Add verified behavior',
        'body': 'Implements the documented behavior and records exact verification evidence for the change.',
        'baseSha': 'a' * 40,
        'headSha': 'b' * 40,
        'files': [
            {'filename': 'src/app.py', 'patch': '+def answer():\n+    return 42\n'},
            {'filename': 'tests/test_app.py', 'patch': '+def test_answer():\n+    assert answer() == 42\n'},
        ],
    }
    value.update(overrides)
    return value


def risk(level='R2', **overrides):
    value = {'risk': level, 'headSha': 'b' * 40, 'baseSha': 'a' * 40, 'repositoryId': 1, 'reasons': []}
    value.update(overrides)
    return value


def check(name, state, workflow='CI'):
    return {'name': name, 'state': state, 'workflow': workflow, 'url': 'https://example.invalid/run'}


def test_dependency_major_and_patch_classification():
    patch = '''@@\n-    "react": "^18.3.1",\n+    "react": "^19.2.0",\n-    "globals": "^17.12.0",\n+    "globals": "^17.14.0",\n'''
    changes = risk_classify.parse_dependency_versions(patch)
    by_name = {item['dependency']: item for item in changes}
    assert by_name['react']['major'] is True
    assert by_name['globals']['major'] is False


def test_docs_and_test_paths_are_recognised():
    assert risk_classify.is_docs('docs/readme.md')
    assert risk_classify.is_docs('README.md')
    assert risk_classify.is_test('tests/test_api.py')
    assert not risk_classify.is_docs('src/main.rs')


def test_review_happy_path_is_auto_merge_candidate():
    result = independent_review.review(context(), risk())
    assert result['decision'] == 'AUTO_MERGE_CANDIDATE'
    assert not result['blockers']
    assert result['checks']['tests'] == 'PRESENT'


def test_review_detects_secret_addition():
    ctx = context(files=[{'filename': 'src/config.py', 'patch': '+TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"\n'}])
    result = independent_review.review(ctx, risk())
    assert result['decision'] == 'BLOCK'
    assert any('github-token' in item for item in result['blockers'])


def test_review_blocks_untrusted_pull_request_target_checkout():
    patch = '+on: pull_request_target\n+      ref: ${{ github.event.pull_request.head.sha }}\n'
    ctx = context(files=[{'filename': '.github/workflows/review.yml', 'patch': patch}])
    result = independent_review.review(ctx, risk('R4'))
    assert result['decision'] == 'BLOCK'
    assert any('untrusted head content' in item for item in result['blockers'])


def test_review_license_change_requires_manual_decision():
    ctx = context(files=[{'filename': 'LICENSE', 'patch': '-old\n+new\n'}])
    result = independent_review.review(ctx, risk('R2'))
    assert result['decision'] == 'MANUAL_REVIEW_REQUIRED'
    assert result['checks']['license'] == 'MANUAL_REVIEW'


def test_gate_feedback_excludes_its_own_jobs():
    checks = [
        check('Portfolio Evidence Gate / verify', 'IN_PROGRESS', 'Portfolio Evidence Gate'),
        check('python', 'SUCCESS', 'Verify'),
    ]
    external = evidence_gate.external_checks(checks)
    assert [item['name'] for item in external] == ['python']


def test_gate_fails_risky_skipped_test_for_r2():
    status = evidence_gate.evaluate_checks([check('python', 'SKIPPED', 'Verify')], 'R2')
    assert status['testStatus'] == 'FAIL_SKIPPED_REQUIRED_WORK'


def test_gate_passes_successful_checks():
    status = evidence_gate.evaluate_checks([check('python', 'SUCCESS', 'Verify'), check('CodeQL', 'SUCCESS', 'CodeQL')], 'R2')
    assert status['testStatus'] == 'PASS'
    assert status['securityStatus'] == 'PASS'


def test_gate_pending_checks_are_not_success():
    status = evidence_gate.evaluate_checks([check('python', 'IN_PROGRESS', 'Verify')], 'R1')
    assert status['testStatus'] == 'PENDING'


def test_stacked_codeql_skip_is_not_applicable_when_default_codeql_succeeds():
    status = evidence_gate.evaluate_checks([
        check('CodeQL stacked (rust)', 'SKIPPED', 'Stacked PR CodeQL'),
        check('CodeQL', 'SUCCESS', 'CodeQL'),
    ], 'R3')
    assert status['testStatus'] == 'PASS'
    assert [item['name'] for item in status['notApplicableSkipped']] == ['CodeQL stacked (rust)']


def test_stacked_codeql_skip_without_default_codeql_remains_fail_closed():
    status = evidence_gate.evaluate_checks([
        check('CodeQL stacked (rust)', 'SKIPPED', 'Stacked PR CodeQL'),
        check('python', 'SUCCESS', 'Verify'),
    ], 'R3')
    assert status['testStatus'] == 'FAIL_SKIPPED_REQUIRED_WORK'
    assert status['notApplicableSkipped'] == []
