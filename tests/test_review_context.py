import base64
import hashlib
import pytest

from scripts.review_context import enrich_context
from scripts.independent_review import inspect_workflows, review
from scripts.ai_review_adapter import run
from scripts.evidence_matrix import matches_role


def fixture():
    context = {'repository': 'styayur/example', 'repositoryId': 1, 'prNumber': 2,
               'headSha': 'a' * 40, 'baseSha': 'b' * 40, 'body': 'A complete controlled fixture change.',
               'files': [{'filename': 'src/example.py', 'status': 'added', 'additions': 1, 'deletions': 0, 'patch': ''}]}
    risk = {'risk': 'R3', 'headSha': context['headSha'], 'baseSha': context['baseSha'], 'diffSha256': 'c' * 64}
    return context, risk


def blob(content, *, corrupt=False):
    data = content.encode()
    oid = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    return {'type': 'file', 'encoding': 'base64', 'size': len(data), 'sha': 'f' * 40 if corrupt else oid,
            'content': base64.b64encode(data).decode()}


def collect(context, risk, content, *, corrupt=False, stale=False, private=False):
    def reader(path):
        if path == 'repos/styayur/example':
            return {'full_name': 'styayur/example', 'id': 1, 'private': private}
        assert path.endswith('?ref=' + context['headSha'])
        return blob(content, corrupt=corrupt)
    def pr_reader(repo, number):
        return {'headRefOid': 'd' * 40 if stale else context['headSha'], 'baseRefOid': context['baseSha'], 'checks': []}
    return enrich_context(context, risk, reader=reader, pr_reader=pr_reader,
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
        enrich_context(context, risk, reader=lambda path: called.append(path))
    assert not called


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


def test_agent_review_success_is_not_native_test_evidence():
    spec = {'kind': 'role', 'role': 'tests'}
    check = {'name': 'regression tests', 'workflow': 'Independent correctness and regression review'}
    assert not matches_role(check, spec, {'tests': ['regression|test']})
    check['workflow'] = 'Native project CI'
    assert matches_role(check, spec, {'tests': ['regression|test']})
