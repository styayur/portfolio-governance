import pytest
from scripts.evidence_gate import successful_decision


@pytest.mark.parametrize('decision', [
    'MANUAL_REVIEW_REQUIRED', 'PENDING_MANUAL', 'REJECTED_MANUAL',
    'BLOCKED_POLICY', 'BLOCKED_MERGE_STATE', 'SHADOW_BLOCKED',
    'SHADOW_ELIGIBLE', 'NOT_VERIFIED', 'FAILED_EVIDENCE_MISSING',
    '', 'UNKNOWN_FUTURE_STATE', None,
])
def test_incomplete_or_unknown_decisions_never_publish_required_check_success(decision):
    assert successful_decision(decision) is False


@pytest.mark.parametrize('decision', ['AUTO_MERGE_ELIGIBLE', 'APPROVED_MANUAL'])
def test_only_explicit_authorized_terminal_decisions_succeed(decision):
    assert successful_decision(decision) is True
