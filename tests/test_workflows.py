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


def test_evidence_gate_is_not_an_executable_workflow():
    assert not (ROOT / '.github/workflows/reusable-portfolio-gate.yml').exists()
    retired = ROOT / 'evidence/retired/reusable-portfolio-gate.yml'
    assert retired.exists()
    live = '\n'.join(path.read_text(encoding='utf-8') for path in workflow_files())
    assert 'Portfolio Evidence Gate' not in live
    assert 'PORTFOLIO_AI_REVIEW' not in live
    assert 'reusable-portfolio-gate.yml' not in live


def test_caller_template_is_outside_executable_workflow_directory():
    template = ROOT / 'templates/caller-portfolio-gate.yml'
    assert template.exists()
    assert 'PINNED_CENTRAL_SHA' in template.read_text()
    assert not (ROOT / '.github/workflows/portfolio-gate.yml').exists()


def test_evidence_matrix_covers_all_public_repositories():
    matrix = yaml.safe_load((ROOT / 'policy/evidence-matrix.v1.json').read_text())
    assert len(matrix['repositories']) == 30
    assert {'styayur/petite-grace', 'styayur/Skimmer-Scraper'} <= set(matrix['repositories'])
    assert 'styayur/site' not in matrix['repositories']

def test_manual_approval_is_not_wired_to_a_live_workflow():
    assert not (ROOT / '.github/workflows/portfolio-gate.yml').exists()
    assert not (ROOT / '.github/workflows/reusable-portfolio-gate.yml').exists()
    live = '\n'.join(path.read_text(encoding='utf-8') for path in workflow_files())
    assert 'manual_approval.py' not in live
    policy = json.loads((ROOT / 'policy/manual-approval.v1.json').read_text())
    assert policy['requiresStrictBaseFreshness'] is True
    assert policy['commands']['approve'] == '/portfolio approve-manual'


def test_native_automerge_does_not_execute_untrusted_heads():
    path = ROOT / '.github/workflows/native-automerge.yml'
    text = path.read_text()
    data = yaml.safe_load(text)
    triggers = data.get('on', data.get(True, {}))
    assert 'pull_request_target' not in triggers
    assert 'pull_request' in triggers
    assert 'actions/checkout' not in text
    assert '--admin' not in text
