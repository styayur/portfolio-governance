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
    assert len(matrix['repositories']) == 28
    assert 'styayur/site' not in matrix['repositories']

def test_final_acceptance_waits_for_all_related_workflows():
    data = yaml.safe_load((ROOT / '.github/workflows/final-acceptance.yml').read_text())
    text = str(data)
    assert 'Governance self-checks' in text
    assert 'Portfolio audit' in text
    assert 'Portfolio project sync' in text
    assert 'Portfolio risk operations' in text
    assert 'collect_workflow_artifacts.py' in text
    steps = data['jobs']['snapshot']['steps']
    target_index = next(i for i, step in enumerate(steps) if step.get('id') == 'target')
    checkout_index = next(i for i, step in enumerate(steps) if str(step.get('uses', '')).startswith('actions/checkout@'))
    assert target_index < checkout_index
    assert steps[checkout_index]['with']['ref'] == '${{ steps.target.outputs.sha }}'


def test_risk_operations_has_rotation_and_dependabot_checks():
    text = (ROOT / '.github/workflows/risk-operations.yml').read_text()
    assert 'dependabot_risk_audit.py' in text
    assert 'pat_rotation_audit.py' in text
    assert 'sync_risk_issue.py' in text
    assert "steps.sync.outcome == 'failure'" in text
    assert "steps.sync.outcome == 'skipped'" in text
