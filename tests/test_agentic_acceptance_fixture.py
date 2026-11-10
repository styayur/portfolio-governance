"""Controlled production CI/repair acceptance; no product defect is asserted."""
import json
from pathlib import Path
from scripts.evidence_gate import successful_decision


def test_controlled_fixture_preserves_fail_closed_policy():
    fixture = json.loads((Path(__file__).parent / 'fixtures/agentic_acceptance.json').read_text())
    assert successful_decision(fixture['decision']) is fixture['expectedAllowed']
