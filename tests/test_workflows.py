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
