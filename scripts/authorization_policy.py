#!/usr/bin/env python3
"""Evaluate proposed R4 authorization records without self-approval."""
from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatch


AUTO_AUTHORIZED = 'AUTO_AUTHORIZED'
PREAUTHORIZED_CONDITIONAL = 'PREAUTHORIZED_CONDITIONAL'
OWNER_AUTHORIZATION_REQUIRED = 'OWNER_AUTHORIZATION_REQUIRED'
PROHIBITED = 'PROHIBITED'


def _matches(path: str, patterns) -> bool:
    return any(fnmatch(path, pattern) or path == pattern for pattern in patterns)


def classify_change(policy: dict, changed_paths) -> str:
    paths = list(changed_paths or [])
    if any(path in {'policy/r4-authorization.v1.json', 'scripts/authorization_policy.py'} for path in paths):
        return PROHIBITED if policy.get('status') != 'ACTIVE' else OWNER_AUTHORIZATION_REQUIRED
    trust_roots = policy.get('trustRootPaths') or []
    if any(_matches(path, trust_roots) for path in paths):
        return OWNER_AUTHORIZATION_REQUIRED
    return AUTO_AUTHORIZED


def validate_authorization(policy: dict, changed_paths, record: dict | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    classification = classify_change(policy, changed_paths)
    if classification == PROHIBITED:
        return {'allowed': False, 'classification': PROHIBITED, 'reason': 'proposed policy cannot self-activate or self-authorize'}
    if classification == AUTO_AUTHORIZED:
        return {'allowed': True, 'classification': AUTO_AUTHORIZED, 'reason': 'not a trust-root change'}
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
    try:
        expires = datetime.fromisoformat(str(record['expiresAt']).replace('Z', '+00:00'))
    except ValueError:
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'invalid expiresAt'}
    if expires <= now:
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'authorization expired'}
    scopes = record.get('scope') or []
    if not all(_matches(path, scopes) for path in changed_paths):
        return {'allowed': False, 'classification': OWNER_AUTHORIZATION_REQUIRED, 'reason': 'authorization scope does not cover changed paths'}
    return {'allowed': True, 'classification': PREAUTHORIZED_CONDITIONAL, 'reason': 'valid owner authorization record'}
