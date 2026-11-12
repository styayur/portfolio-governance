import copy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/reusable-portfolio-gate.yml').read_text())
SHA = 'a' * 40


def fixture():
    env = {'CENTRAL_SHA': SHA, 'EXPECTED_HEAD': 'b' * 40, 'EXPECTED_BASE': 'c' * 40,
           'PR_NUMBER': '39', 'GITHUB_EVENT_NAME': 'pull_request_target',
           'GITHUB_ACTOR_ID': '1', 'GITHUB_RUN_ATTEMPT': '1',
           'GITHUB_REPOSITORY': 'styayur/example', 'GITHUB_RUN_ID': '42'}
    root = {'full_name': 'styayur/portfolio-governance', 'id': 1449400406, 'private': False, 'default_branch': 'main'}
    target = {'full_name': 'styayur/example', 'id': 2, 'private': False}
    pr = {'number': 39, 'state': 'open', 'head': {'sha': env['EXPECTED_HEAD']},
          'base': {'sha': env['EXPECTED_BASE'], 'repo': {'id': 2}}}
    run = {'id': 42, 'repository': {'id': 2}, 'referenced_workflows': [{
        'path': 'styayur/portfolio-governance/.github/workflows/reusable-portfolio-gate.yml@' + SHA, 'sha': SHA}]}
    comparison = {'status': 'ahead', 'base_commit': {'sha': SHA}, 'merge_base_commit': {'sha': SHA}}
    data = {'repos/styayur/example': target, 'repos/styayur/example/pulls/39': pr, 'repos/styayur/portfolio-governance': root,
            'repos/styayur/example/actions/runs/42': run,
            'repos/styayur/portfolio-governance/compare/' + SHA + '...main': comparison}
    source = WORKFLOW['jobs']['provenance']['steps'][0]['run']
    code = source.split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    namespace = {'__name__': 'unit_test'}
    exec(compile(code, '<protected-inline-provenance>', 'exec'), namespace)
    return env, data, namespace['validate']


def test_provenance_guard_precedes_every_executable_checkout_job():
    jobs = WORKFLOW['jobs']
    assert jobs['provenance']['permissions'] == {'contents': 'read', 'actions': 'read'}
    assert len(jobs['provenance']['steps']) == 1
    assert jobs['classify']['needs'] == 'provenance'
    assert jobs['review']['needs'] == 'classify'
    assert jobs['ai-review']['needs'] == ['classify', 'review']
    assert 'ai-review' in jobs['evidence']['needs']
    assert 'provenance' in jobs['evidence']['needs']
    assert jobs['evidence']['if'] == 'always()'
    assert 'uses' not in jobs['evidence']['steps'][0]
    assert jobs['merge']['needs'] == 'evidence'


def test_valid_public_protected_callee_is_accepted():
    env, data, validate = fixture()
    validate(env, lambda path: copy.deepcopy(data[path]))


@pytest.mark.parametrize('key,value', [('CENTRAL_SHA', 'main'), ('EXPECTED_HEAD', '$(untrusted)'),
    ('EXPECTED_BASE', 'a' * 39), ('PR_NUMBER', '-1'), ('GITHUB_EVENT_NAME', 'pull_request_review'),
    ('GITHUB_REPOSITORY', 'styayur/site')])
def test_untrusted_inputs_are_rejected_before_checkout(key, value):
    env, data, validate = fixture()
    env[key] = value
    with pytest.raises(ValueError):
        validate(env, lambda path: copy.deepcopy(data[path]))


@pytest.mark.parametrize('kind', ['private-target', 'wrong-root-id', 'private-root', 'different-callee',
    'missing-callee', 'duplicate-callee', 'mutable-callee', 'wrong-run', 'wrong-run-repo', 'diverged-root', 'unmerged-root'])
def test_provenance_mismatch_fails_closed(kind):
    env, data, validate = fixture()
    root = data['repos/styayur/portfolio-governance']
    run = data['repos/styayur/example/actions/runs/42']
    comparison = data['repos/styayur/portfolio-governance/compare/' + SHA + '...main']
    if kind == 'private-target': data['repos/styayur/example']['private'] = True
    if kind == 'wrong-root-id': root['id'] = 3
    if kind == 'private-root': root['private'] = True
    if kind == 'different-callee': run['referenced_workflows'][0]['sha'] = 'd' * 40
    if kind == 'missing-callee': run['referenced_workflows'] = []
    if kind == 'duplicate-callee': run['referenced_workflows'] *= 2
    if kind == 'mutable-callee': run['referenced_workflows'][0]['path'] = run['referenced_workflows'][0]['path'].replace(SHA, 'main')
    if kind == 'wrong-run': run['id'] = 43
    if kind == 'wrong-run-repo': run['repository']['id'] = 3
    if kind == 'diverged-root': comparison['status'] = 'diverged'
    if kind == 'unmerged-root': comparison['merge_base_commit']['sha'] = 'd' * 40
    with pytest.raises(ValueError): validate(env, lambda path: copy.deepcopy(data[path]))


def test_dispatch_requires_actual_owner_and_first_attempt():
    env, data, validate = fixture()
    env.update(GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_ACTOR_ID='324560549')
    validate(env, lambda path: copy.deepcopy(data[path]))
    for key, value in [('GITHUB_ACTOR_ID', '1'), ('GITHUB_RUN_ATTEMPT', '2')]:
        bad = {**env, key: value}
        with pytest.raises(ValueError): validate(bad, lambda path: copy.deepcopy(data[path]))


def test_api_failure_does_not_allow_checkout():
    env, data, validate = fixture()
    def unavailable(path): raise RuntimeError('API unavailable')
    with pytest.raises(RuntimeError): validate(env, unavailable)


@pytest.mark.parametrize('kind', ['wrong-number', 'closed', 'stale-head', 'stale-base', 'wrong-base-repository'])
def test_live_pr_identity_must_match_inputs_before_checkout(kind):
    env, data, validate = fixture()
    pr = data['repos/styayur/example/pulls/39']
    if kind == 'wrong-number': pr['number'] = 40
    if kind == 'closed': pr['state'] = 'closed'
    if kind == 'stale-head': pr['head']['sha'] = 'd' * 40
    if kind == 'stale-base': pr['base']['sha'] = 'd' * 40
    if kind == 'wrong-base-repository': pr['base']['repo']['id'] = 3
    with pytest.raises(ValueError): validate(env, lambda path: copy.deepcopy(data[path]))


@pytest.mark.parametrize('key', ['PROVENANCE_RESULT', 'CLASSIFY_RESULT', 'STATIC_RESULT', 'AI_RESULT'])
@pytest.mark.parametrize('state', ['failure', 'cancelled', 'skipped', ''])
def test_required_verify_check_fails_instead_of_being_skipped(key, state):
    step = WORKFLOW['jobs']['evidence']['steps'][0]
    code = step['run'].split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    namespace = {'__name__': 'unit_test'}
    exec(compile(code, '<protected-required-check-guard>', 'exec'), namespace)
    env = {k: 'success' for k in ['PROVENANCE_RESULT', 'CLASSIFY_RESULT', 'STATIC_RESULT', 'AI_RESULT']}
    namespace['require_successful_upstream'](env)
    env[key] = state
    with pytest.raises(SystemExit): namespace['require_successful_upstream'](env)
