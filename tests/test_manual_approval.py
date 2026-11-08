import json
from pathlib import Path

from scripts import manual_approval

ROOT = Path(__file__).resolve().parents[1]
HEAD = 'b' * 40
OLD_HEAD = '9' * 40
BASE = 'a' * 40
DIFF = 'd' * 64
OLD_DIFF = 'e' * 64
CONFIG = json.loads((ROOT / 'policy/manual-approval.v1.json').read_text())
PR_NUMBER = 23


def risk(level='R3'):
    return {'risk': level, 'prNumber': PR_NUMBER, 'headSha': HEAD, 'baseSha': BASE, 'diffSha256': DIFF}


def meta(labels=None, head=HEAD, base=BASE):
    return {'number': PR_NUMBER, 'state': 'open', 'headSha': head, 'baseSha': base, 'labels': labels or []}


def body(command='approve-manual', head=HEAD, base=BASE, diff=DIFF, risk_level='R3', pr=PR_NUMBER, reason=None):
    lines = [
        f'/portfolio {command}',
        f'pr={pr}',
        f'head={head}',
        f'base={base}',
        f'diff={diff}',
        f'risk={risk_level}',
    ]
    if reason:
        lines.append(f'reason={reason}')
    return '\n'.join(lines) + '\n'


def review(review_id=1, login='styayur', state='COMMENTED', commit=HEAD, text=None, user_type='User', submitted='2026-11-08T10:00:00Z'):
    return {
        'id': review_id,
        'user': {'login': login, 'type': user_type},
        'state': state,
        'commit_id': commit,
        'body': text if text is not None else body(),
        'submitted_at': submitted,
    }


def permissions(mapping):
    return lambda repo, login: mapping.get(login, 'none')


def evaluate(reviews, risk_level='R3', labels=None, mapping=None):
    return manual_approval.evaluate(
        reviews,
        meta(labels=labels),
        risk(risk_level),
        CONFIG,
        permission_fetcher=permissions(mapping or {'styayur': 'admin'}),
        repo='styayur/Nickspeare',
    )


def test_r3_exact_bound_maintainer_approval_is_approved_manual():
    result = evaluate([review()])
    assert result['state'] == 'APPROVED_MANUAL'
    assert result['actions'][0]['command'] == 'approve-manual'
    assert result['headSha'] == HEAD and result['baseSha'] == BASE and result['diffSha256'] == DIFF


def test_r3_missing_approval_is_pending_manual():
    result = evaluate([])
    assert result['state'] == 'PENDING_MANUAL'
    assert any('approve-manual' in reason for reason in result['reasons'])


def test_r4_requires_label_approval_and_explicit_authorization():
    approve = review(review_id=1, text=body('approve-manual', risk_level='R4'))
    authorize = review(review_id=2, text=body('authorize-r4', risk_level='R4'), submitted='2026-11-08T10:01:00Z')
    pending = evaluate([approve, authorize], risk_level='R4')
    assert pending['state'] == 'PENDING_MANUAL'
    approved = evaluate([approve, authorize], risk_level='R4', labels=[CONFIG['r4']['authorizationLabel']])
    assert approved['state'] == 'APPROVED_MANUAL'
    only_approve = evaluate([approve], risk_level='R4', labels=[CONFIG['r4']['authorizationLabel']])
    assert only_approve['state'] == 'PENDING_MANUAL'


def test_unauthorized_write_role_and_forged_identity_cannot_approve():
    write_role = evaluate([review()], mapping={'styayur': 'write'})
    assert write_role['state'] == 'PENDING_MANUAL'
    assert any('not an authorized maintainer' in item['reason'] for item in write_role['ignored'])
    forged = evaluate([review(login='attacker')], mapping={'attacker': 'none'})
    assert forged['state'] == 'PENDING_MANUAL'
    assert any('authorized maintainer' in item['reason'] for item in forged['ignored'])


def test_bot_authored_approval_is_never_human_authorization():
    result = evaluate([review(login='approval-bot[bot]', user_type='Bot')], mapping={'approval-bot[bot]': 'admin'})
    assert result['state'] == 'PENDING_MANUAL'
    assert any('bot-authored' in item['reason'] for item in result['ignored'])


def test_stale_review_commit_or_command_binding_is_pending():
    old_commit = evaluate([review(commit=OLD_HEAD)])
    assert old_commit['state'] == 'PENDING_MANUAL'
    assert any('current head' in item['reason'] for item in old_commit['ignored'])
    stale_command = evaluate([review(text=body(head=OLD_HEAD))])
    assert stale_command['state'] == 'PENDING_MANUAL'
    assert any('stale' in item['reason'] for item in stale_command['ignored'])


def test_replayed_approval_from_old_diff_or_pr_is_pending():
    old_diff = evaluate([review(text=body(diff=OLD_DIFF))])
    assert old_diff['state'] == 'PENDING_MANUAL'
    other_pr = evaluate([review(text=body(pr=PR_NUMBER + 1))])
    assert other_pr['state'] == 'PENDING_MANUAL'


def test_authorized_rejection_is_rejected_manual_and_later_approval_can_supersede_it():
    rejected = evaluate([review(text=body('reject-manual', reason='unsafe'), submitted='2026-11-08T10:02:00Z')])
    assert rejected['state'] == 'REJECTED_MANUAL'
    restored = evaluate([
        review(text=body('reject-manual', reason='unsafe'), submitted='2026-11-08T10:02:00Z'),
        review(review_id=2, text=body(), submitted='2026-11-08T10:03:00Z'),
    ])
    assert restored['state'] == 'APPROVED_MANUAL'


def test_malformed_or_multiple_commands_are_ignored():
    malformed = evaluate([review(text='approve please')])
    assert malformed['state'] == 'PENDING_MANUAL'
    multiple = evaluate([review(text=body() + body('reject-manual', reason='no'))])
    assert multiple['state'] == 'PENDING_MANUAL'


def test_dismissed_review_is_not_approval():
    result = evaluate([review(state='DISMISSED')])
    assert result['state'] == 'PENDING_MANUAL'
    assert any('dismissed' in item['reason'] for item in result['ignored'])


def test_approval_protocol_policy_is_active_and_exact():
    assert CONFIG['status'] == 'ACTIVE'
    assert CONFIG['commands']['approve'] == '/portfolio approve-manual'
    assert CONFIG['commands']['reject'] == '/portfolio reject-manual'
    assert CONFIG['commands']['authorizeR4'] == '/portfolio authorize-r4'
    assert CONFIG['bindingFields'] == ['pr', 'head', 'base', 'diff', 'risk']
