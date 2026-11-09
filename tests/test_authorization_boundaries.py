from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from scripts.authorization_policy import validate_authorization

ROOT = Path(__file__).resolve().parents[1]


def case():
    now = datetime(2026, 11, 9, 10, tzinfo=timezone.utc)
    policy = json.loads((ROOT / 'policy/r4-authorization.v1.json').read_text())
    policy.update(status='ACTIVE', policyVersion='test', trustedIssuers=['protected-owner-service'])
    record = dict(authorizationId='test', ownerIdentity='styayur', issuedBy='protected-owner-service',
                  scope=['src/*'], policyVersion='test', repository='styayur/example', prNumber=1,
                  commitSha='a'*40, baseSha='b'*40, diffSha256='c'*64,
                  issuedAt=(now-timedelta(minutes=1)).isoformat(),
                  expiresAt=(now+timedelta(hours=1)).isoformat(), signature='test-signature',
                  source='protected-github-event', selfIssued=False)
    context = {k: record[k] for k in ['ownerIdentity','repository','prNumber','commitSha','baseSha','diffSha256']}
    return now, policy, record, context


def test_plain_signature_and_active_string_cannot_authorize():
    now, policy, record, context = case()
    assert not validate_authorization(policy, ['src/app.py'], record, now, context=context)['allowed']
    assert not validate_authorization(policy, ['src/app.py'], record, now, context=context, verifier=lambda *_: False)['allowed']


def test_exact_preexisting_protected_authorization_can_cover_engineering_only():
    now, policy, record, context = case()
    evaluate = lambda paths: validate_authorization(policy, paths, record, now, context=context, verifier=lambda *_: True)
    assert evaluate(['src/app.py'])['allowed']
    assert not evaluate(['policy/r4-authorization.v1.json'])['allowed']
    record['scope'] = ['*']
    assert not evaluate(['scripts/evidence_gate.py'])['allowed']


def test_expiry_future_issue_and_binding_are_checked():
    now, policy, record, context = case()
    def check():
        return validate_authorization(policy, ['src/app.py'], record, now, context=context, verifier=lambda *_: True)['allowed']
    original = dict(record)
    for delta in [dict(commitSha='d'*40), dict(baseSha='d'*40), dict(repository='other/repo'),
                  dict(issuedAt=(now+timedelta(minutes=1)).isoformat()),
                  dict(expiresAt=(now+timedelta(days=2)).isoformat()),
                  dict(expiresAt='invalid'), dict(expiresAt=now.isoformat()),
                  dict(issuedBy='untrusted'), dict(scope=['other/*'])]:
        record.clear(); record.update(original); record.update(delta)
        assert not check(), delta


def test_proposal_is_never_active_by_inference():
    now, policy, record, context = case()
    policy['status'] = 'PROPOSED'
    assert not validate_authorization(policy, ['src/app.py'], record, now, context=context, verifier=lambda *_: True)['allowed']
