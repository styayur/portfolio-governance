import base64
import hashlib
import pytest

from scripts.review_context import enrich_context
from scripts.independent_review import inspect_workflows, review
from scripts.ai_review_adapter import run
from scripts.evidence_matrix import matches_role
from scripts.evidence_matrix import effective_requirements, load_matrix
from pathlib import Path


def fixture():
    context = {'repository': 'styayur/example', 'repositoryId': 1, 'prNumber': 2,
               'changedFileCount': 1, 'expectedChangedFileCount': 1,
               'headSha': 'a' * 40, 'baseSha': 'b' * 40, 'body': 'A complete controlled fixture change.',
               'files': [{'filename': 'src/example.py', 'status': 'added', 'additions': 1, 'deletions': 0, 'patch': ''}]}
    risk = {'risk': 'R3', 'headSha': context['headSha'], 'baseSha': context['baseSha'], 'diffSha256': 'c' * 64}
    return context, risk


def blob(content, *, corrupt=False):
    data = content.encode()
    oid = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    return {'type': 'file', 'encoding': 'base64', 'size': len(data), 'sha': 'f' * 40 if corrupt else oid,
            'content': base64.b64encode(data).decode()}


def collect(context, risk, content, *, corrupt=False, stale=False, private=False, mode='100644', old_content=''):
    source = {context['headSha']: blob(content), context['baseSha']: blob(old_content)}
    tree_oids = {context['headSha']: 'd' * 40, context['baseSha']: 'e' * 40}
    def reader(path):
        if path == 'repos/styayur/example':
            return {'full_name': 'styayur/example', 'id': 1, 'private': private}
        for sha, tree_sha in tree_oids.items():
            if path.endswith('/git/commits/' + sha):
                return {'sha': sha, 'tree': {'sha': tree_sha}}
            if path.endswith('/git/trees/' + tree_sha + '?recursive=1'):
                return {'sha': tree_sha, 'truncated': False, 'tree': [{'path': context['files'][0]['filename'], 'sha': source[sha]['sha'], 'type': 'blob', 'mode': mode, 'size': source[sha]['size']}]}
            if path.endswith('/git/blobs/' + source[sha]['sha']):
                assert mode in {'100644', '100755'}, 'a symlink must never be followed'
                return {**source[sha], 'sha': 'f' * 40} if corrupt else source[sha]
        raise AssertionError('unexpected API path: ' + path)
    def pr_reader(repo, number):
        return {'headRefOid': 'd' * 40 if stale else context['headSha'], 'baseRefOid': context['baseSha'], 'checks': []}
    return enrich_context(context, risk, expected_repository=context['repository'], reader=reader, pr_reader=pr_reader,
                          evaluator=lambda *args, **kwargs: {'status': 'MISSING'},
                          authorizer=lambda *args: {'state': 'PENDING_MANUAL'})


def test_omitted_large_patch_is_recovered_from_immutable_verified_blob():
    context, risk = fixture()
    result = collect(context, risk, "print('complete source')")
    assert result['reviewInputComplete'] is True
    item = result['files'][0]
    assert item['patch'] == ''  # The established diff-binding contract is unchanged.
    assert "+print('complete source')" in item['reviewPatch']
    assert item['reviewSource']['headSha'] == context['headSha']
    assert item['reviewSource']['headEndsWithNewline'] is False
    assert result['observedEvidenceMatrix']['status'] == 'MISSING'
    assert result['evidenceCollection']['executesPrCode'] is False


def test_corrupt_blob_cannot_reach_the_model_or_approve():
    context, risk = fixture()
    enriched = collect(context, risk, 'not trusted\n', corrupt=True)
    assert enriched['reviewInputComplete'] is False
    called = []
    static = {'headSha': context['headSha'], 'baseSha': context['baseSha'], 'diffSha256': risk['diffSha256']}
    result = run(enriched, risk, static, {'enabled': True}, lambda *args: called.append(args))
    assert result['status'] == result['decision'] == 'NOT_VERIFIED'
    assert not called


def test_recovered_source_is_still_checked_for_credentials():
    context, risk = fixture()
    enriched = collect(context, risk, "value = '" + 'ghp_' + 'x' * 32 + "'\n")
    result = review(enriched, risk)
    assert result['decision'] == 'BLOCK'
    assert any('possible github-token' in item for item in result['blockers'])


def test_stale_binding_and_private_repository_fail_closed():
    context, risk = fixture()
    with pytest.raises(ValueError, match='binding changed'):
        collect(context, risk, 'source\n', stale=True)
    with pytest.raises(ValueError, match='public repository'):
        collect(context, risk, 'source\n', private=True)
    context['repository'] = 'styayur/site'
    called = []
    with pytest.raises(ValueError, match='outside public'):
        enrich_context(context, risk, expected_repository=context['repository'], reader=lambda path: called.append(path))
    assert not called


def test_symlink_or_gitlink_cannot_be_treated_as_the_target_file():
    context, risk = fixture()
    for mode in ['120000', '160000']:
        result = collect(context, risk, 'safe-looking symlink target\n', mode=mode)
        assert result['reviewInputComplete'] is False
        assert 'reviewSource' not in result['files'][0]


@pytest.mark.parametrize('expected', [None, 2, 3001, True])
def test_missing_or_truncated_pr_file_inventory_fails_before_source_reads(expected):
    context, risk = fixture()
    context['expectedChangedFileCount'] = expected
    called = []
    with pytest.raises(ValueError, match='file coverage'):
        enrich_context(context, risk, expected_repository=context['repository'], reader=lambda path: called.append(path))
    assert not called


@pytest.mark.parametrize('old,new', [('x\n', 'x'), ('x\r\n', 'x\n'), ('x\u2028y\n', 'x\ny\n'), ('', '\n')])
def test_reconstructed_review_preserves_line_endings_and_unicode(old, new):
    context, risk = fixture()
    context['files'][0]['status'] = 'modified'
    result = collect(context, risk, new, old_content=old)
    item = result['files'][0]
    assert result['reviewInputComplete'] is True
    assert item['reviewPatch']
    assert item['reviewBaseContent'].encode() == old.encode()
    assert item['reviewHeadContent'].encode() == new.encode()
    assert item['reviewSource']['baseBlob'] != item['reviewSource']['headBlob']


def test_passing_sha_as_evaluator_data_is_not_a_checkout():
    workflow = '''on: pull_request_target
jobs:
  portfolio:
    uses: styayur/portfolio-governance/.github/workflows/reusable-portfolio-gate.yml@''' + 'a' * 40 + '''
    with:
      head_sha: ${{ github.event.pull_request.head.sha }}
'''
    files = [{'filename': '.github/workflows/portfolio-gate.yml', 'patch': '\n'.join('+' + x for x in workflow.splitlines())}]
    assert inspect_workflows(files)[0] == []
    files[0]['patch'] = '''+on: pull_request_target
+jobs:
+  bad:
+    steps:
+      - uses: actions/checkout@''' + 'a' * 40 + '''
+        with:
+          ref: ${{ github.event.pull_request.head.sha }}'''
    assert any('untrusted head' in x for x in inspect_workflows(files)[0])


def test_added_checkout_is_blocked_even_when_the_privileged_trigger_is_unchanged():
    context, risk = fixture()
    context['files'][0].update(filename='.github/workflows/check.yml', status='modified', additions=1, deletions=0,
                                patch='+          ref: ${{ github.event.pull_request.head.sha }}')
    source = 'on: pull_request_target\njobs:\n  test:\n    steps:\n      - uses: actions/checkout@' + 'a' * 40 + '\n        with:\n          ref: ${{ github.event.pull_request.head.sha }}\n'
    enriched = collect(context, risk, source, old_content=source.replace('          ref: ${{ github.event.pull_request.head.sha }}\n', ''))
    assert enriched['reviewInputComplete']
    assert enriched['files'][0]['reviewHeadContent'] == source
    assert inspect_workflows(enriched['files'])[0]


def test_context_cannot_select_another_repository_than_the_protected_caller():
    context, risk = fixture()
    called = []
    with pytest.raises(ValueError, match='protected caller repository'):
        enrich_context(context, risk, expected_repository='styayur/portfolio-governance', reader=lambda path: called.append(path))
    assert not called


@pytest.mark.parametrize('ref', ['${{ github.head_ref }}', '${{ env.REQUESTED }}', '${{ steps.resolve.outputs.ref }}', '${{ github.event.pull_request.head["sha"] }}'])
def test_inline_and_indirect_privileged_checkout_refs_are_blocked(ref):
    import yaml
    workflow = {'on': ['pull_request_target'], 'env': {'REQUESTED': '${{ github.event.pull_request.head.sha }}'},
                'jobs': {'verify': {'steps': [{'uses': 'actions/checkout@' + 'a' * 40, 'with': {'ref': ref}}]}}}
    # Flow style is intentional: security checks must inspect YAML semantics.
    source = yaml.safe_dump(workflow, default_flow_style=True)
    assert inspect_workflows([{'filename': '.github/workflows/test.yml', 'reviewHeadContent': source}])[0]


@pytest.mark.parametrize('ref', ['${{ github.sha }}', '${{ github.event.pull_request.base.sha }}'])
def test_explicit_trusted_base_checkout_remains_allowed(ref):
    import yaml
    workflow = {'on': 'pull_request_target', 'jobs': {'verify': {'steps': [{'uses': 'actions/checkout@' + 'a' * 40, 'with': {'ref': ref}}]}}}
    assert not inspect_workflows([{'filename': '.github/workflows/test.yml', 'reviewHeadContent': yaml.safe_dump(workflow)}])[0]


def test_yaml_object_tags_are_rejected_without_executing_source(monkeypatch):
    import os
    calls = []
    monkeypatch.setattr(os, 'system', lambda *args: calls.append(args))
    source = '!!python/object/apply:os.system ["untrusted command"]'
    assert inspect_workflows([{'filename': '.github/workflows/test.yml', 'reviewHeadContent': source}])[0]
    assert not calls


def test_known_native_contract_rejects_unlisted_workflow_or_job_names():
    matrix = load_matrix(Path(__file__).resolve().parents[1] / 'policy/evidence-matrix.v1.json')
    requirements = effective_requirements(matrix, 'styayur/portfolio-governance', 'R3')
    spec = next(item for item in requirements['required'] if item['role'] == 'tests')
    assert matches_role({'name': 'test', 'workflow': 'Governance self-checks'}, spec, matrix['rolePatterns'])
    assert not matches_role({'name': 'test', 'workflow': 'Unlisted regression tests'}, spec, matrix['rolePatterns'])
    assert not matches_role({'name': 'fake unit tests', 'workflow': 'Governance self-checks'}, spec, matrix['rolePatterns'])


@pytest.mark.parametrize('repository,ref,blocked', [('attacker/public-repo', None, True), ('attacker/public-repo', 'a' * 40, True), (None, 'a' * 40, True), ('${{ github.repository }}', 'a' * 40, True), (None, None, False), ('${{ github.repository }}', None, False)])
def test_immutable_sha_does_not_establish_privileged_checkout_trust(repository, ref, blocked):
    import yaml
    options = {}
    if repository is not None:
        options['repository'] = repository
    if ref is not None:
        options['ref'] = ref
    workflow = {'on': 'pull_request_target', 'jobs': {'verify': {'steps': [{'uses': 'actions/checkout@' + 'a' * 40, 'with': options}]}}}
    errors, _ = inspect_workflows([{'filename': '.github/workflows/test.yml', 'reviewHeadContent': yaml.safe_dump(workflow, default_flow_style=True)}])
    assert bool(errors) is blocked


@pytest.mark.parametrize('missing_role', ['build', 'tests', 'security'])
def test_root_native_aliases_cannot_substitute_for_other_roles(missing_role):
    from scripts.evidence_matrix import evaluate
    matrix = load_matrix(Path(__file__).resolve().parents[1] / 'policy/evidence-matrix.v1.json')
    aliases = matrix['repositories']['styayur/portfolio-governance']['checkAliases']
    checks = [{'name': alias['name'], 'workflow': alias['workflow'], 'appSlug': 'github-actions',
               'headSha': 'a' * 40, 'workflowRunId': 1, 'state': 'SUCCESS'}
              for alias in aliases if missing_role not in alias['roles']]
    result = evaluate(checks, matrix, 'styayur/portfolio-governance', 'R3', 'a' * 40)
    group = next(g for g in result['groups'] if g['role'] == missing_role)
    assert group['status'] == 'MISSING'
    assert result['status'] != 'PASS'


def test_missing_configured_role_alias_cannot_fall_back_to_a_broad_job_regex():
    import copy
    matrix = copy.deepcopy(load_matrix(Path(__file__).resolve().parents[1] / 'policy/evidence-matrix.v1.json'))
    aliases = matrix['repositories']['styayur/portfolio-governance']['checkAliases']
    for alias in aliases:
        alias['roles'] = [role for role in alias['roles'] if role != 'tests']
    requirements = effective_requirements(matrix, 'styayur/portfolio-governance', 'R3')
    spec = next(item for item in requirements['required'] if item['role'] == 'tests')
    assert spec['checkAliases'] == []
    assert not matches_role({'name': 'test', 'workflow': 'Governance self-checks'}, spec, matrix['rolePatterns'])


def test_native_platform_without_an_explicit_alias_is_missing_under_a_contract():
    matrix = load_matrix(Path(__file__).resolve().parents[1] / 'policy/evidence-matrix.v1.json')
    requirements = effective_requirements(matrix, 'styayur/glyphibe', 'R3')
    spec = next(item for item in requirements['required'] if item['role'] == 'native:windows')
    assert spec['checkAliases'] == []
    assert not matches_role({'name': 'unlisted Windows test', 'workflow': 'CI'}, spec, matrix['rolePatterns'])


@pytest.mark.parametrize('trigger', ['pull_request_target', 'pull_request'])
def test_job_level_write_all_is_blocked(trigger):
    import yaml
    workflow = {'on': trigger, 'jobs': {'unsafe': {'permissions': 'write-all', 'steps': []}}}
    assert inspect_workflows([{'filename': '.github/workflows/test.yml', 'reviewHeadContent': yaml.safe_dump(workflow)}])[0]


@pytest.mark.parametrize('command', ['git checkout "$REQUESTED"', 'git switch branch', 'git -C repo reset --hard $SHA'])
def test_privileged_shell_checkout_cannot_bypass_checkout_action_validation(command):
    import yaml
    workflow = {'on': 'pull_request_target', 'jobs': {'unsafe': {'steps': [{'run': command}]}}}
    assert inspect_workflows([{'filename': '.github/workflows/test.yml', 'reviewHeadContent': yaml.safe_dump(workflow)}])[0]


@pytest.mark.parametrize('mode', ['120000', '160000'])
def test_complete_nonworkflow_rest_patch_does_not_bypass_mode_validation(mode):
    context, risk = fixture()
    context['files'][0].update(patch='@@ -0,0 +1 @@\n+source\n', additions=1, deletions=0)
    result = collect(context, risk, 'source\n', mode=mode)
    assert result['reviewInputComplete'] is False


def test_complete_nonworkflow_rest_patch_still_supplies_full_blob_identity_and_mode():
    context, risk = fixture()
    context['files'][0].update(patch='@@ -0,0 +1 @@\n+source\n', additions=1, deletions=0)
    result = collect(context, risk, 'source\n', mode='100755')
    item = result['files'][0]
    assert result['reviewInputComplete'] is True
    assert item['reviewHeadContent'] == 'source\n'
    assert item['reviewSource']['headMode'] == '100755'
    assert item['reviewSource']['headBlob'] == blob('source\n')['sha']


def test_explicit_empty_contract_does_not_reenable_legacy_role_matching():
    import copy
    matrix = copy.deepcopy(load_matrix(Path(__file__).resolve().parents[1] / 'policy/evidence-matrix.v1.json'))
    matrix['repositories']['styayur/portfolio-governance']['checkAliases'] = []
    requirements = effective_requirements(matrix, 'styayur/portfolio-governance', 'R3')
    for spec in requirements['required']:
        assert spec['strictAliases'] is True
        assert not matches_role({'name': 'build test security', 'workflow': 'CI'}, spec, matrix['rolePatterns'])


def test_agent_review_success_is_not_native_test_evidence():
    spec = {'kind': 'role', 'role': 'tests'}
    check = {'name': 'regression tests', 'workflow': 'Independent correctness and regression review'}
    assert not matches_role(check, spec, {'tests': ['regression|test']})
    check['workflow'] = 'Native project CI'
    assert matches_role(check, spec, {'tests': ['regression|test']})
