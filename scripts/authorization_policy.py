#!/usr/bin/env python3
"""Evaluate proposed R4 authorization records without self-approval."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from fnmatch import fnmatch
import re


AUTO_AUTHORIZED = 'AUTO_AUTHORIZED'
PREAUTHORIZED_CONDITIONAL = 'PREAUTHORIZED_CONDITIONAL'
EXTERNAL_AUTHORIZATION_REQUIRED = 'EXTERNAL_AUTHORIZATION_REQUIRED'
OWNER_AUTHORIZATION_REQUIRED = EXTERNAL_AUTHORIZATION_REQUIRED
PROHIBITED = 'PROHIBITED'


def _matches(path: str, patterns) -> bool:
    return any(fnmatch(path, pattern) or path == pattern for pattern in patterns)


def classify_change(policy: dict, changed_paths) -> str:
    paths = list(changed_paths or [])
    if any(path in {'policy/r4-authorization.v1.json', 'scripts/authorization_policy.py'} for path in paths):
        return PROHIBITED
    trust_roots = policy.get('trustRootPaths') or []
    if any(_matches(path, trust_roots) for path in paths):
        return OWNER_AUTHORIZATION_REQUIRED
    return AUTO_AUTHORIZED


def validate_authorization(policy: dict, changed_paths, record: dict | None, now: datetime | None = None, *, context=None, verifier=None) -> dict:
    """The verifier must be supplied by protected caller code, never PR content."""
    now = now or datetime.now(timezone.utc)
    changed_paths = list(changed_paths or [])
    if not changed_paths or any(not isinstance(path, str) or path.startswith(('/', '\\')) or '\\' in path or '..' in path.split('/') for path in changed_paths):
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'invalid changed paths'}
    classification = classify_change(policy, changed_paths)
    if classification == PROHIBITED:
        return {'allowed': False, 'classification': PROHIBITED, 'reason': 'proposed policy cannot self-activate or self-authorize'}
    if policy.get('status') != 'ACTIVE':
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'proposed policy cannot self-activate'}
    if not context or not callable(verifier):
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'protected verifier and exact context required'}
    if not record:
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'owner authorization record missing'}
    required = set((policy.get('authorizationRecord') or {}).get('requiredFields') or [])
    missing = sorted(field for field in required if not record.get(field))
    if missing:
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': f'missing authorization fields: {missing}'}
    if record.get('selfIssued') is True or record.get('issuedBy') == record.get('ownerIdentity'):
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'self-issued authorization rejected'}
    if record.get('policyVersion') != policy.get('policyVersion'):
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'policy version mismatch'}
    if record.get('issuedBy') not in policy.get('trustedIssuers', []):
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'untrusted issuer'}
    if record.get('ownerIdentity') != context.get('ownerIdentity') or any(record.get(k) != context.get(k) for k in ('repository', 'prNumber', 'commitSha', 'baseSha', 'diffSha256')):
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'owner or exact binding mismatch'}
    if any(not re.fullmatch('[0-9a-f]{40}', str(record.get(k))) for k in ('commitSha', 'baseSha')) or not re.fullmatch('[0-9a-f]{64}', str(record.get('diffSha256'))):
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'invalid SHA or digest'}
    try:
        issued = datetime.fromisoformat(str(record['issuedAt']).replace('Z', '+00:00'))
        expires = datetime.fromisoformat(str(record['expiresAt']).replace('Z', '+00:00'))
        valid = bool(issued.tzinfo and expires.tzinfo and now.tzinfo) and issued <= now < expires and timedelta(0) < expires-issued <= timedelta(hours=min(24, (policy.get('authorizationRecord') or {}).get('maxValidityHours', 24)))
    except (ValueError, TypeError, KeyError):
        valid = False
    if not valid:
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'invalid authorization validity window'}
    scopes = record.get('scope') or []
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes) or not all(_matches(path, scopes) for path in changed_paths):
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'authorization scope does not cover changed paths'}
    if classification != AUTO_AUTHORIZED:
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'trust-root changes require existing protected protocol'}
    try:
        authenticated = verifier(record, context) is True
    except Exception:
        authenticated = False
    if not authenticated:
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'authorization signature/source/activation not verified'}
    return {'allowed': True, 'classification': PREAUTHORIZED_CONDITIONAL, 'reason': 'valid owner authorization record'}
