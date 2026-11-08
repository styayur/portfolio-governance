import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import ai_review_adapter, dependabot_risk_audit, evidence_gate, evidence_matrix, independent_review, pat_rotation_audit, risk_classify, security_signals

HEAD = 'b' * 40
BASE = 'a' * 40
DIFF = 'd' * 64
MATRIX = evidence_matrix.load_matrix(ROOT / 'policy/evidence-matrix.v1.json')
ENFORCE = {
    'mode': 'enforce',
    'autoMerge': {'R0': True, 'R1': True, 'R2': True, 'R3': False, 'R4': False},
    'maxAttemptsPerHead': 3,
    'r4AuthorizationLabel': 'portfolio:r4-approved',
}
SHADOW = {**ENFORCE, 'mode': 'shadow'}


def context(**overrides):
    value = {
        'repository': 'styayur/ripple',
        'repositoryId': 1,
        'prNumber': 7,
        'title': 'Add verified behavior',
        'body': 'Implements the documented behavior and records exact verification evidence for the change.',
        'baseSha': BASE,
        'headSha': HEAD,
        'diffSha256': DIFF,
        'files': [
            {'filename': 'src/app.js', 'status': 'modified', 'patch': '+export function answer() { return 42; }\n'},
            {'filename': 'tests/app.test.js', 'status': 'modified', 'patch': '+test("answer", () => expect(answer()).toBe(42));\n'},
        ],
    }
    value.update(overrides)
    return value


def risk(level='R2', **overrides):
    value = {'risk': level, 'headSha': HEAD, 'baseSha': BASE, 'repositoryId': 1, 'reasons': [], 'diffSha256': DIFF}
    value.update(overrides)
    return value


def review(**overrides):
    value = {'headSha': HEAD, 'baseSha': BASE, 'diffSha256': DIFF, 'decision': 'AUTO_MERGE_CANDIDATE', 'blockers': [], 'manualReviewReasons': []}
    value.update(overrides)
    return value


def ai(**overrides):
    value = {'status': 'VERIFIED', 'decision': 'APPROVE', 'headSha': HEAD, 'baseSha': BASE, 'diffSha256': DIFF, 'reason': ''}
    value.update(overrides)
    return value


def pr(**overrides):
    value = {'state': 'OPEN', 'isDraft': False, 'headRefOid': HEAD, 'baseRefOid': BASE, 'mergeable': 'MERGEABLE', 'mergeStateStatus': 'CLEAN', 'labels': [], 'checksTruncated': False}
    value.update(overrides)
    return value


def check(name, state, workflow='CI', app='github-actions', head=HEAD, run_id=123, typename='CheckRun'):
    return {'typename': typename, 'name': name, 'workflow': workflow, 'state': state, 'appSlug': app, 'headSha': head, 'workflowRunId': run_id, 'url': 'https://github.com/styayur/ripple/actions/runs/123'}


def r2_checks(repo='styayur/ripple'):
    values = [check('build node', 'SUCCESS'), check('unit tests', 'SUCCESS', 'CI'), check('Analyze (javascript-typescript)', 'SUCCESS', 'CodeQL')]
    if repo == 'styayur/TinySTT':
        values.append(check('Windows desktop compile', 'SUCCESS', 'CI'))
    return values


def evidence_for(level='R2', checks=None, repo='styayur/ripple'):
    return evidence_matrix.evaluate(checks if checks is not None else r2_checks(repo), MATRIX, repo, level, HEAD)


def test_dependency_major_and_patch_classification():
    patch = '''@@\n-    "react": "^18.3.1",\n+    "react": "^19.2.0",\n-    "globals": "^17.12.0",\n+    "globals": "^17.14.0",\n'''
    changes = risk_classify.parse_dependency_versions(patch)
    by_name = {item['dependency']: item for item in changes}
    assert by_name['react']['major'] is True
    assert by_name['globals']['major'] is False


def test_auth_permission_and_governance_paths_are_r4():
    for path in ('src/auth/session.py', 'src/permissions/roles.ts', 'internal/admin/elevate.ts'):
        result = risk_classify.classify_files([{'filename': path, 'patch': '+changed = true\n', 'additions': 1, 'deletions': 0}])
        assert result['risk'] == 'R4', path
    result = risk_classify.classify_files([{'filename': 'scripts/evidence_gate.py', 'patch': '+changed = true\n', 'additions': 1, 'deletions': 0}])
    assert result['risk'] == 'R4'


def test_privilege_code_signal_is_r4_even_with_neutral_path():
    result = risk_classify.classify_files([{'filename': 'src/runtime.py', 'patch': '+os.setuid(0)\n', 'additions': 1, 'deletions': 0}])
    assert result['risk'] == 'R4'
    assert result['privilegeSignals']


def test_review_happy_path_is_static_candidate():
    result = independent_review.review(context(), risk())
    assert result['decision'] == 'AUTO_MERGE_CANDIDATE'
    assert result['reviewerType'] == 'STATIC_POLICY'
    assert result['diffSha256'] == DIFF


def test_review_detects_secret_addition():
    fake_token = 'ghp_' + ('a' * 36)
    ctx = context(files=[{'filename': 'src/config.py', 'status': 'modified', 'patch': f'+TOKEN = "{fake_token}"\n'}])
    result = independent_review.review(ctx, risk(diffSha256=evidence_matrix.diff_digest(ctx['files'])))
    assert result['decision'] == 'BLOCK'


def test_lint_only_does_not_satisfy_r2_required_tests():
    evidence = evidence_for(checks=[check('lint', 'SUCCESS')])
    result = evidence_gate.decide(risk(), review(), ai(), evidence, pr(), HEAD, BASE, ENFORCE, 1)
    assert evidence['status'] != 'PASS'
    assert result['autoMergeEligible'] is False
    assert result['decision'].startswith('FAILED_EVIDENCE')


def test_missing_security_evidence_blocks_r2():
    evidence = evidence_for(checks=[check('build node', 'SUCCESS'), check('unit tests', 'SUCCESS')])
    assert evidence['status'] == 'MISSING'
    result = evidence_gate.decide(risk(), review(), ai(), evidence, pr(), HEAD, BASE, ENFORCE, 1)
    assert result['autoMergeEligible'] is False


def test_failed_security_scan_blocks_r2():
    evidence = evidence_for(checks=[check('build node', 'SUCCESS'), check('unit tests', 'SUCCESS'), check('Analyze (javascript-typescript)', 'FAILURE', 'CodeQL')])
    assert evidence['status'] == 'FAIL'
    result = evidence_gate.decide(risk(), review(), ai(), evidence, pr(), HEAD, BASE, ENFORCE, 1)
    assert result['autoMergeEligible'] is False


def test_untrusted_fake_success_is_not_evidence():
    checks = [check('build node', 'SUCCESS'), check('unit tests', 'SUCCESS', app='evil-app'), check('Analyze (javascript-typescript)', 'SUCCESS', 'CodeQL')]
    evidence = evidence_for(checks=checks)
    tests_group = next(g for g in evidence['groups'] if g['role'] == 'tests')
    assert tests_group['status'] == 'UNVERIFIED_SOURCE'
    result = evidence_gate.decide(risk(), review(), ai(), evidence, pr(), HEAD, BASE, ENFORCE, 1)
    assert result['autoMergeEligible'] is False


def test_head_change_after_review_blocks_merge():
    result = evidence_gate.decide(risk(), review(), ai(), evidence_for(), pr(headRefOid='c' * 40), HEAD, BASE, ENFORCE, 1)
    assert result['decision'] == 'FAILED_HEAD_CHANGED'
    assert result['autoMergeEligible'] is False


def test_base_change_after_review_blocks_merge():
    result = evidence_gate.decide(risk(), review(), ai(), evidence_for(), pr(baseRefOid='c' * 40), HEAD, BASE, ENFORCE, 1)
    assert result['decision'] == 'FAILED_BASE_CHANGED'
    assert result['autoMergeEligible'] is False


def test_skipped_native_workflow_blocks_native_repo():
    checks = [check('build node', 'SUCCESS'), check('unit tests', 'SUCCESS'), check('Analyze (rust)', 'SUCCESS', 'CodeQL'), check('Windows desktop compile', 'SKIPPED')]
    evidence = evidence_for('R2', checks, 'styayur/TinySTT')
    assert evidence['status'] == 'MISSING'
    result = evidence_gate.decide(risk(), review(), ai(), evidence, pr(), HEAD, BASE, ENFORCE, 1)
    assert result['autoMergeEligible'] is False


def test_cancelled_security_workflow_blocks_r2():
    checks = [check('build node', 'SUCCESS'), check('unit tests', 'SUCCESS'), check('security scan', 'CANCELLED')]
    evidence = evidence_for(checks=checks)
    assert evidence['status'] == 'CANCELLED'
    result = evidence_gate.decide(risk(), review(), ai(), evidence, pr(), HEAD, BASE, ENFORCE, 1)
    assert result['autoMergeEligible'] is False


def test_ai_review_unavailable_blocks_r2():
    evidence = evidence_for()
    unavailable = ai(status='NOT_VERIFIED', decision='NOT_VERIFIED', reason='AI_REVIEW_NOT_CONFIGURED')
    result = evidence_gate.decide(risk(), review(), unavailable, evidence, pr(), HEAD, BASE, ENFORCE, 1)
    assert result['decision'] == 'FAILED_AI_REVIEW_NOT_VERIFIED'
    assert result['autoMergeEligible'] is False


def test_r2_can_auto_merge_only_with_complete_matrix_and_ai_approval():
    result = evidence_gate.decide(risk(), review(), ai(), evidence_for(), pr(), HEAD, BASE, ENFORCE, 1)
    assert result['decision'] == 'AUTO_MERGE_ELIGIBLE'
    assert result['autoMergeEligible'] is True


def test_draft_pr_never_merges():
    result = evidence_gate.decide(risk('R1'), review(), ai(), evidence_for('R1', [check('unit tests', 'SUCCESS'), check('security scan', 'SUCCESS')]), pr(isDraft=True), HEAD, BASE, ENFORCE, 1)
    assert result['decision'] == 'WAITING_FOR_READY'
    assert result['autoMergeEligible'] is False


def test_gate_policy_change_is_r4():
    result = risk_classify.classify_files([{'filename': '.github/workflows/reusable-portfolio-gate.yml', 'patch': '+permissions: write-all\n', 'additions': 1, 'deletions': 0}])
    assert result['risk'] == 'R4'


def test_retry_budget_blocks_repeated_failing_head():
    result = evidence_gate.decide(risk(), review(), ai(), evidence_for(), pr(), HEAD, BASE, ENFORCE, 4)
    assert result['decision'] == 'FAILED_RETRY_BUDGET'
    assert result['autoMergeEligible'] is False


def test_shadow_mode_never_sets_auto_merge_eligible():
    result = evidence_gate.decide(risk('R1'), review(), ai(), evidence_for('R1', [check('unit tests', 'SUCCESS'), check('security scan', 'SUCCESS')]), pr(), HEAD, BASE, SHADOW, 1)
    assert result['decision'] == 'SHADOW_ELIGIBLE'
    assert result['autoMergeEligible'] is False
    assert result['shadowEligible'] is True


def test_r3_and_r4_remain_manual():
    r3_evidence = evidence_for('R3', [check('build node', 'SUCCESS'), check('unit tests', 'SUCCESS'), check('security scan', 'SUCCESS')])
    r3 = evidence_gate.decide(risk('R3'), review(), ai(), r3_evidence, pr(), HEAD, BASE, ENFORCE, 1)
    assert r3['decision'] == 'MANUAL_REVIEW_REQUIRED'
    assert r3['autoMergeEligible'] is False
    r4 = evidence_gate.decide(risk('R4'), review(), ai(), r3_evidence, pr(), HEAD, BASE, ENFORCE, 1)
    assert r4['decision'] == 'MANUAL_REVIEW_REQUIRED'
    assert r4['autoMergeEligible'] is False


def test_ai_adapter_missing_config_is_not_verified(monkeypatch):
    for key in ('PORTFOLIO_AI_REVIEW_ENABLED', 'PORTFOLIO_AI_REVIEW_ENDPOINT', 'PORTFOLIO_AI_REVIEW_MODEL', 'PORTFOLIO_AI_REVIEW_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    result = ai_review_adapter.run(context(), risk(), review())
    assert result['status'] == 'NOT_VERIFIED'
    assert result['decision'] == 'NOT_VERIFIED'


def test_ai_adapter_rejects_binding_mismatch():
    def transport(config, prompt):
        return {'choices': [{'message': {'content': json.dumps({'decision': 'APPROVE', 'findings': [], 'summary': 'ok', 'headSha': 'c' * 40, 'baseSha': BASE, 'diffSha256': DIFF})}}]}
    config = {'enabled': True, 'endpoint': 'https://example.invalid/v1/chat/completions', 'model': 'review-model', 'apiKey': 'x', 'timeout': 5, 'maxChars': 120000}
    result = ai_review_adapter.run(context(), risk(), review(), config=config, transport=transport)
    assert result['status'] == 'NOT_VERIFIED'
    assert result['reason'] == 'AI_REVIEW_BINDING_MISMATCH'


def test_stacked_codeql_is_only_na_when_default_codeql_succeeds():
    checks = [check('CodeQL stacked (rust)', 'SKIPPED', 'Stacked PR CodeQL'), check('Analyze (rust)', 'SUCCESS', 'CodeQL'), check('build rust', 'SUCCESS'), check('unit tests', 'SUCCESS')]
    evidence = evidence_for('R2', checks, 'styayur/terics')
    assert evidence['status'] == 'PASS'
    assert any(c.get('notApplicableReason') for c in evidence['checks'])

def test_missing_workflow_run_identity_is_not_verified():
    checks = [check('build node', 'SUCCESS'), check('unit tests', 'SUCCESS', run_id=None), check('security scan', 'SUCCESS')]
    evidence = evidence_for(checks=checks)
    tests_group = next(g for g in evidence['groups'] if g['role'] == 'tests')
    assert tests_group['status'] == 'UNVERIFIED_WORKFLOW'


def test_check_from_wrong_commit_is_stale():
    checks = [check('build node', 'SUCCESS'), check('unit tests', 'SUCCESS', head='c' * 40), check('security scan', 'SUCCESS')]
    evidence = evidence_for(checks=checks)
    tests_group = next(g for g in evidence['groups'] if g['role'] == 'tests')
    assert tests_group['status'] == 'STALE'


def test_current_rollout_is_enforce_after_negative_acceptance():
    rollout = evidence_matrix.load_rollout(ROOT / 'policy/rollout.json')
    assert rollout['mode'] == 'enforce'
    assert rollout['autoMerge'] == {'R0': True, 'R1': True, 'R2': True, 'R3': False, 'R4': False}
    assert rollout['maxAttemptsPerHead'] == 3


def test_code_scanning_states_are_distinct():
    workflows = {'workflows': [{'id': 1, 'name': 'CodeQL', 'path': '.github/workflows/codeql.yml'}]}
    assert security_signals.classify_code_scanning({'code_scanning': {'status': 'enabled'}}, workflows, [])['status'] == 'NOT_VERIFIED'
    assert security_signals.classify_code_scanning({'code_scanning': {'status': 'enabled'}}, workflows, [], {'status': 'in_progress'})['status'] == 'NOT_VERIFIED'
    assert security_signals.classify_code_scanning({'code_scanning': {'status': 'enabled'}}, workflows, [{'number': 1}])['status'] == 'FINDINGS'
    assert security_signals.classify_code_scanning({'code_scanning': {'status': 'enabled'}}, workflows, {'_error': 'HTTP 403'})['status'] == 'UNAUTHORIZED'
    assert security_signals.classify_code_scanning({'code_scanning': {'status': 'disabled'}}, {'workflows': []}, {'_error': 'HTTP 404'})['status'] == 'NOT_ENABLED'
    assert security_signals.classify_code_scanning({'code_scanning': {'status': 'enabled'}}, workflows, [], {'status': 'completed', 'conclusion': 'success'})['status'] == 'NO_RESULTS'
    assert security_signals.classify_code_scanning({'code_scanning': {'status': 'enabled'}}, workflows, [], {'status': 'completed', 'conclusion': 'startup_failure'})['status'] == 'SCAN_FAILED'
    assert security_signals.classify_code_scanning({'code_scanning': {'status': 'enabled'}}, workflows, [], {'status': 'completed', 'conclusion': 'skipped'})['status'] == 'NOT_VERIFIED'
    assert security_signals.classify_code_scanning({'code_scanning': {'status': 'enabled'}}, workflows, [{'number': 1}], {'status': 'completed', 'conclusion': 'success'})['status'] == 'FINDINGS'
    assert security_signals.classify_code_scanning({'code_scanning': {'status': 'enabled'}}, workflows, [], {'conclusion': 'failure'})['status'] == 'SCAN_FAILED'


def test_dependabot_json_line_parser_preserves_paginated_items():
    assert dependabot_risk_audit.parse_json_lines('{"number":1}\n\n{"number":2}\n') == [{'number': 1}, {'number': 2}]


def test_pat_rotation_thresholds_are_explicit():
    from datetime import date
    assert pat_rotation_audit.classify_pat('2026-12-20', date(2026, 11, 8))['status'] == 'PASS'
    assert pat_rotation_audit.classify_pat('2026-12-01', date(2026, 11, 8))['status'] == 'WARNING'
    assert pat_rotation_audit.classify_pat('2026-11-20', date(2026, 11, 8))['status'] == 'CRITICAL'
    assert pat_rotation_audit.classify_pat('2026-11-14', date(2026, 11, 8))['status'] == 'FINAL_WARNING'
    assert pat_rotation_audit.classify_pat('2026-11-08', date(2026, 11, 8))['status'] == 'EXPIRED'
    assert pat_rotation_audit.classify_pat('not-a-date', date(2026, 11, 8))['status'] == 'NOT_VERIFIED'


def test_dependabot_policy_has_known_blockers_and_never_accepts_unclassified():
    policy = json.loads((ROOT / 'policy/dependabot-dispositions.json').read_text())
    ids = {entry['id'] for entry in policy['entries']}
    assert {'tiny-stt-zip', 'tiny-stt-rustls', 'glib-upstream-tauri-gtk', 'minimatch-js-development', 'rhizomaybor-web-rendering'} <= ids
    assert policy['unclassifiedPolicy']['status'] == 'BLOCKED'
    match = dependabot_risk_audit.match_entry('styayur/TinySTT', {'number': 5, 'dependency': {'package': {'name': 'zip', 'ecosystem': 'rust'}}}, policy['entries'])
    assert match['id'] == 'tiny-stt-zip'
    assert dependabot_risk_audit.match_entry('styayur/TinySTT', {'number': 99, 'dependency': {'package': {'name': 'zip', 'ecosystem': 'rust'}}}, policy['entries']) is None
    assert dependabot_risk_audit.match_entry('styayur/TinySTT', {'number': 5, 'dependency': {'package': {'name': 'zip', 'ecosystem': 'rust'}}}, [{'match': {'repositories': ['styayur/TinySTT'], 'packages': ['zip']}}]) is None


def test_risk_issue_markdown_escaping():
    from scripts import sync_risk_issue
    assert sync_risk_issue.markdown_text('line one\nline two `code`') == "line one line two 'code'"


def test_wait_for_workflows_selects_main_events_only():
    from scripts import wait_for_workflows
    runs = [
        {'workflowName': 'Portfolio audit', 'headSha': HEAD, 'event': 'push', 'createdAt': '2026-01-01T00:00:00Z'},
        {'workflowName': 'Portfolio audit', 'headSha': HEAD, 'event': 'pull_request', 'createdAt': '2026-01-02T00:00:00Z'},
    ]
    selected = wait_for_workflows.select_latest_runs(runs, ['Portfolio audit'], HEAD, ['push'])
    assert selected['Portfolio audit']['event'] == 'push'


def test_gate_pin_policy_matches_rollout():
    rollout = json.loads((ROOT / 'policy/rollout.json').read_text())
    pin = json.loads((ROOT / 'policy/gate-pin.json').read_text())
    assert pin['sha'] == rollout['gateSha']
    assert pin['reviewedPr'] == 18


def test_artifact_path_must_be_unique(tmp_path):
    from scripts import collect_workflow_artifacts
    (tmp_path / 'one').mkdir()
    target = tmp_path / 'one' / 'report.json'
    target.write_text('{}')
    assert collect_workflow_artifacts.unique_artifact_path(tmp_path, 'report.json') == target
    (tmp_path / 'two').mkdir()
    (tmp_path / 'two' / 'report.json').write_text('{}')
    try:
        collect_workflow_artifacts.unique_artifact_path(tmp_path, 'report.json')
    except ValueError:
        pass
    else:
        raise AssertionError('ambiguous artifacts must fail closed')


def test_invalid_gate_sha_fails_load(tmp_path):
    value = json.loads((ROOT / 'policy/rollout.json').read_text())
    value['gateSha'] = 'not-a-sha'
    path = tmp_path / 'rollout.json'
    path.write_text(json.dumps(value))
    try:
        evidence_matrix.load_rollout(path)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid gateSha must fail closed')
