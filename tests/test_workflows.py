import json
import re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r'^[0-9a-f]{40}$')


def workflow_files():
    return list((ROOT / '.github/workflows').glob('*.yml'))


def test_workflows_are_valid_yaml_and_pin_actions():
    for path in workflow_files():
        data = yaml.safe_load(path.read_text())
        assert isinstance(data, dict), path
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith('uses:'):
                ref = stripped.split('@', 1)[1].split()[0] if '@' in stripped else ''
                assert PIN.fullmatch(ref), f'{path}: action is not pinned: {stripped}'


def test_reusable_gate_has_stable_required_check_name():
    data = yaml.safe_load((ROOT / '.github/workflows/reusable-portfolio-gate.yml').read_text())
    assert 'jobs' in data
    names = [job.get('name') for job in data['jobs'].values()]
    assert 'Portfolio Evidence Gate / verify' in names


def test_caller_template_is_outside_executable_workflow_directory():
    template = ROOT / 'templates/caller-portfolio-gate.yml'
    assert template.exists()
    assert 'PINNED_CENTRAL_SHA' in template.read_text()

def test_gate_has_independent_ai_review_and_exact_checkout_pin():
    data = yaml.safe_load((ROOT / '.github/workflows/reusable-portfolio-gate.yml').read_text())
    names = [job.get('name') for job in data['jobs'].values()]
    assert 'Portfolio Evidence Gate / ai-review' in names
    assert data['jobs']['ai-review']['needs'] == ['classify', 'review']
    assert '--base-sha' in str(data['jobs']['evidence']['steps'])


def test_evidence_matrix_covers_all_public_repositories():
    matrix = yaml.safe_load((ROOT / 'policy/evidence-matrix.v1.json').read_text())
    assert len(matrix['repositories']) == 30
    assert {'styayur/petite-grace', 'styayur/Skimmer-Scraper'} <= set(matrix['repositories'])
    assert 'styayur/site' not in matrix['repositories']

def test_authenticated_review_records_are_consumed_through_safe_refresh_events():
    for name in ('.github/workflows/portfolio-gate.yml', 'templates/caller-portfolio-gate.yml'):
        data = yaml.safe_load((ROOT / name).read_text())
        triggers = data.get('on', data.get(True, {}))
        assert 'pull_request_review' not in triggers
        assert 'pull_request_target' in triggers
        assert 'workflow_dispatch' in triggers
        assert "github.actor_id == '324560549'" in data['jobs']['portfolio']['if']
        assert 'github.run_attempt == 1' in data['jobs']['portfolio']['if']
    workflow = (ROOT / '.github/workflows/reusable-portfolio-gate.yml').read_text()
    assert 'manual_approval.py' in workflow
    assert '--manual-approval' in workflow
    policy = json.loads((ROOT / 'policy/manual-approval.v1.json').read_text())
    assert policy['status'] == 'ACTIVE'
    assert policy['requiresStrictBaseFreshness'] is True
    assert policy['commands']['approve'] == '/portfolio approve-manual'
