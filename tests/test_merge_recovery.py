"""Exercise the actual no-checkout merge preflight against stale-merge failures."""
import json
from pathlib import Path
import sys
import types

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/reusable-portfolio-gate.yml'
DATA = yaml.safe_load(WORKFLOW.read_text())
STEP = DATA['jobs']['merge']['steps'][0]
PROGRAM = STEP['run'].split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
HEAD = 'a' * 40
BASE = 'b' * 40
PR = {'headRefOid': HEAD, 'baseRefOid': BASE, 'mergeable': 'MERGEABLE', 'mergeStateStatus': 'UNSTABLE'}
FAILED_MERGE = {'name': 'portfolio / Portfolio Evidence Gate / merge', 'workflow': 'Portfolio Evidence Gate', 'state': 'FAILURE'}
NATIVE = {'name': 'test', 'workflow': 'Governance self-checks', 'state': 'SUCCESS'}


def run_preflight(monkeypatch, pr=None, checks=None):
    calls = []
    def read_only(command, **kwargs):
        calls.append(command)
        assert command[:3] in (['gh', 'pr', 'view'], ['gh', 'pr', 'checks'])
        return json.dumps((pr or PR) if command[2] == 'view' else checks)
    monkeypatch.setitem(sys.modules, 'subprocess', types.SimpleNamespace(check_output=read_only))
    for key, value in {'GITHUB_REPOSITORY': 'styayur/portfolio-governance', 'PR_NUMBER': '28',
                       'EXPECTED_HEAD': HEAD, 'EXPECTED_BASE': BASE}.items():
        monkeypatch.setenv(key, value)
    exec(compile(PROGRAM, '<actual-protected-merge-preflight>', 'exec'), {})
    return calls


def test_prior_merge_failure_can_recover_with_current_native_success(monkeypatch):
    calls = run_preflight(monkeypatch, checks=[FAILED_MERGE, NATIVE])
    assert len(calls) == 2


@pytest.mark.parametrize('state', ['FAILURE', 'CANCELLED', 'TIMED_OUT', 'ACTION_REQUIRED',
                                 'STARTUP_FAILURE', 'ERROR', 'STALE', 'PENDING',
                                 'IN_PROGRESS', 'QUEUED', 'SKIPPED', 'NEUTRAL', ''])
def test_recovery_never_ignores_nonpassing_native_checks(monkeypatch, state):
    with pytest.raises(SystemExit):
        run_preflight(monkeypatch, checks=[FAILED_MERGE, dict(NATIVE, state=state)])


@pytest.mark.parametrize('changes', [{'headRefOid': 'c' * 40}, {'baseRefOid': 'd' * 40},
                                   {'mergeable': 'CONFLICTING'}, {'mergeStateStatus': 'BEHIND'},
                                   {'mergeStateStatus': 'DIRTY'}, {'mergeStateStatus': 'DRAFT'}])
def test_preflight_rejects_binding_changes_and_unmergeable_states(monkeypatch, changes):
    with pytest.raises(SystemExit):
        run_preflight(monkeypatch, pr={**PR, **changes}, checks=[FAILED_MERGE, NATIVE])


@pytest.mark.parametrize('checks', [[], [FAILED_MERGE], [NATIVE],
                                  [dict(FAILED_MERGE, workflow='Untrusted'), NATIVE],
                                  [dict(FAILED_MERGE, name='another job'), NATIVE]])
def test_recovery_requires_only_actual_merge_failures_and_native_success(monkeypatch, checks):
    with pytest.raises(SystemExit):
        run_preflight(monkeypatch, checks=checks)


def test_named_codeql_success_cannot_exempt_skipped_native_recovery(monkeypatch):
    default = {'name': 'CodeQL', 'workflow': '', 'state': 'SUCCESS'}
    stacked = {'name': 'CodeQL stacked', 'workflow': 'Stacked PR CodeQL', 'state': 'SKIPPED'}
    with pytest.raises(SystemExit):
        run_preflight(monkeypatch, checks=[FAILED_MERGE, NATIVE, default, stacked])
    with pytest.raises(SystemExit):
        run_preflight(monkeypatch, checks=[FAILED_MERGE, NATIVE, stacked])
