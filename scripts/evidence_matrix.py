#!/usr/bin/env python3
"""Required-evidence matrix and check provenance evaluation.

The functions in this module are pure except for loading JSON files. They do not
execute pull request content, workflow steps, or external commands.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PASS = 'PASS'
FAIL = 'FAIL'
MISSING = 'MISSING'
STALE = 'STALE'
CANCELLED = 'CANCELLED'
PENDING = 'PENDING'
SKIPPED = 'SKIPPED'
NOT_APPLICABLE = 'NOT_APPLICABLE'
NOT_VERIFIED = 'NOT_VERIFIED'
UNVERIFIED_SOURCE = 'UNVERIFIED_SOURCE'
UNVERIFIED_WORKFLOW = 'UNVERIFIED_WORKFLOW'

FAILURE_STATES = {'FAILURE', 'TIMED_OUT', 'ACTION_REQUIRED', 'STARTUP_FAILURE', 'ERROR'}
CANCELLED_STATES = {'CANCELLED'}
PENDING_STATES = {'QUEUED', 'IN_PROGRESS', 'PENDING', 'EXPECTED', 'WAITING', 'REQUESTED'}
SKIP_STATES = {'SKIPPED', 'NEUTRAL'}


def load_matrix(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text())
    if data.get('schemaVersion') != 1:
        raise ValueError('unsupported evidence matrix schema')
    if not data.get('riskRequirements') or not data.get('profiles'):
        raise ValueError('evidence matrix is missing required sections')
    return data


def load_rollout(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text())
    if data.get('schemaVersion') != 1 or data.get('mode') not in {'shadow', 'enforce'}:
        raise ValueError('invalid rollout policy')
    return data


def diff_digest(files) -> str:
    digest = hashlib.sha256()
    for item in sorted(files or [], key=lambda x: str(x.get('filename') or '')):
        digest.update(str(item.get('filename') or '').encode('utf-8'))
        digest.update(b'\0')
        digest.update(str(item.get('status') or '').encode('utf-8'))
        digest.update(b'\0')
        digest.update(str(item.get('patch') or '').encode('utf-8'))
        digest.update(b'\0')
    return digest.hexdigest()


def repository_profile(matrix: dict, repo: str):
    override = (matrix.get('repositories') or {}).get(repo) or {}
    profile_name = override.get('profile') or matrix.get('defaultProfile') or 'mixed'
    profile = (matrix.get('profiles') or {}).get(profile_name)
    if not profile:
        raise ValueError(f'unknown evidence profile {profile_name!r} for {repo}')
    return profile_name, profile, override


def effective_requirements(matrix: dict, repo: str, risk_level: str) -> dict:
    profile_name, profile, override = repository_profile(matrix, repo)
    risk = (matrix.get('riskRequirements') or {}).get(risk_level)
    if not risk:
        raise ValueError(f'unknown risk level {risk_level!r}')

    required = []
    not_applicable = []
    for role in risk.get('requiredRoles') or []:
        if role == 'build' and profile.get('build') is False:
            not_applicable.append({'role': 'build', 'reason': 'repository profile does not require a build'})
            continue
        required.append({'role': role, 'kind': 'role', 'platform': None})

    native_platforms = list(profile.get('nativePlatforms') or [])
    if risk.get('nativeIfConfigured') and native_platforms:
        for platform in native_platforms:
            required.append({'role': f'native:{platform}', 'kind': 'native', 'platform': platform})
    else:
        not_applicable.append({'role': 'native', 'reason': 'repository has no required native platform for this risk tier'})

    return {
        'risk': risk_level,
        'profile': profile_name,
        'required': required,
        'notApplicable': not_applicable,
        'aiReviewRequired': bool(risk.get('aiReviewRequired')),
        'manualReview': bool(risk.get('manualReview')),
        'specialistAdapterRequired': bool(risk.get('specialistAdapterRequired')),
        'explicitAuthorizationRequired': bool(risk.get('explicitAuthorizationRequired')),
        'override': override,
    }


def _matches(patterns, text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def matches_role(check: dict, spec: dict, role_patterns: dict) -> bool:
    text = f"{check.get('name') or ''} {check.get('workflow') or ''}".strip()
    if spec['kind'] == 'native':
        patterns = (((role_patterns.get('native') or {}).get(spec['platform'])) or [])
        return _matches(patterns, text)
    return _matches((role_patterns.get(spec['role']) or []), text)


def normalise_check(raw: dict, expected_head: str, trusted_sources: dict) -> dict:
    typename = raw.get('typename') or raw.get('__typename') or 'CheckRun'
    name = raw.get('name') or raw.get('context') or 'unknown'
    workflow = raw.get('workflow') or raw.get('workflowName') or ''
    app_slug = raw.get('appSlug') or ''
    app_name = raw.get('appName') or ''
    app_node_id = raw.get('appNodeId') or ''
    creator = raw.get('creator') or ''
    workflow_run_id = raw.get('workflowRunId')
    head_sha = raw.get('headSha') or ''
    status = str(raw.get('status') or '').upper()
    conclusion = str(raw.get('conclusion') or '').upper()
    state = str(raw.get('state') or '').upper()
    if not state:
        state = conclusion if status == 'COMPLETED' else status
    state = state or 'UNVERIFIED'

    trusted_apps = {str(x).casefold() for x in (trusted_sources.get('appSlugs') or [])}
    trusted_creators = {str(x).casefold() for x in (trusted_sources.get('statusCreators') or [])}
    if typename == 'CheckRun':
        trusted_source = str(app_slug).casefold() in trusted_apps
    elif typename == 'StatusContext':
        trusted_source = str(creator).casefold() in trusted_creators
    else:
        trusted_source = False

    fresh = bool(expected_head and head_sha and head_sha == expected_head)
    require_run = bool(trusted_sources.get('requireWorkflowRun', True))
    if not trusted_source:
        trust_status = UNVERIFIED_SOURCE
        trust_reason = 'check source app/creator is not trusted'
    elif require_run and not workflow_run_id:
        trust_status = UNVERIFIED_WORKFLOW
        trust_reason = 'required workflow run identity is missing'
    elif not fresh:
        trust_status = STALE
        trust_reason = 'check commit does not match the requested head SHA'
    else:
        trust_status = 'VERIFIED'
        trust_reason = ''
    return {
        'name': name,
        'workflow': workflow,
        'state': state,
        'status': status,
        'conclusion': conclusion,
        'url': raw.get('url') or raw.get('detailsUrl') or raw.get('targetUrl'),
        'typename': typename,
        'sourceType': typename,
        'appSlug': app_slug,
        'appName': app_name,
        'appNodeId': app_node_id,
        'creator': creator,
        'workflowRunId': workflow_run_id,
        'headSha': head_sha,
        'fresh': fresh,
        'trustedSource': trusted_source,
        'trustStatus': trust_status,
        'trustReason': trust_reason,
        'notApplicableReason': None,
    }


def mark_special_not_applicable(checks: list[dict]) -> list[dict]:
    """Only mark redundant stacked CodeQL skips when an independent default CodeQL succeeds."""
    default_codeql_success = any(
        c['trustStatus'] == 'VERIFIED'
        and c['state'] == 'SUCCESS'
        and 'codeql' in f"{c.get('name')} {c.get('workflow')}".casefold()
        and 'stacked' not in c.get('name', '').casefold()
        for c in checks
    )
    changed = []
    for check in checks:
        text = f"{check.get('name')} {check.get('workflow')}".casefold()
        if default_codeql_success and 'stacked' in text and 'codeql' in text and check['state'] in SKIP_STATES:
            check = dict(check)
            check['state'] = NOT_APPLICABLE
            check['notApplicableReason'] = 'redundant stacked CodeQL job; default CodeQL succeeded'
            changed.append(check)
        else:
            changed.append(check)
    return changed


def evaluate_group(checks: list[dict], spec: dict, role_patterns: dict) -> dict:
    matches = [c for c in checks if matches_role(c, spec, role_patterns)]
    base = {'role': spec['role'], 'kind': spec['kind'], 'platform': spec.get('platform'), 'matches': matches}
    if not matches:
        return {**base, 'status': MISSING, 'reason': 'no check matched this required evidence group'}

    valid = [c for c in matches if c['trustStatus'] == 'VERIFIED']
    if any(c['state'] in FAILURE_STATES for c in valid):
        return {**base, 'status': FAIL, 'reason': 'a trusted exact-head check failed'}
    if any(c['state'] in CANCELLED_STATES for c in valid):
        return {**base, 'status': CANCELLED, 'reason': 'a trusted exact-head check was cancelled'}
    if any(c['state'] in PENDING_STATES for c in valid):
        return {**base, 'status': PENDING, 'reason': 'a trusted exact-head check is still pending'}
    if any(c['state'] == 'SUCCESS' for c in valid):
        return {**base, 'status': PASS, 'reason': 'required trusted exact-head evidence passed'}

    states = {c['state'] for c in valid}
    if states == {NOT_APPLICABLE}:
        return {**base, 'status': NOT_APPLICABLE, 'reason': 'all matching checks were explicitly not applicable'}
    if valid and states <= SKIP_STATES:
        return {**base, 'status': SKIPPED, 'reason': 'matching checks were skipped without an approved not-applicable rule'}

    trust_statuses = {c['trustStatus'] for c in matches if c['trustStatus'] != 'VERIFIED'}
    if UNVERIFIED_SOURCE in trust_statuses:
        return {**base, 'status': UNVERIFIED_SOURCE, 'reason': 'only untrusted check sources were found'}
    if STALE in trust_statuses:
        return {**base, 'status': STALE, 'reason': 'matching checks do not belong to the exact head SHA'}
    if UNVERIFIED_WORKFLOW in trust_statuses:
        return {**base, 'status': UNVERIFIED_WORKFLOW, 'reason': 'matching checks lack required workflow-run identity'}
    return {**base, 'status': NOT_VERIFIED, 'reason': 'matching checks could not be verified'}


def aggregate_group_status(groups: list[dict]) -> str:
    statuses = [g['status'] for g in groups]
    if FAIL in statuses:
        return FAIL
    if CANCELLED in statuses:
        return CANCELLED
    if STALE in statuses:
        return STALE
    if UNVERIFIED_SOURCE in statuses or UNVERIFIED_WORKFLOW in statuses or NOT_VERIFIED in statuses:
        return NOT_VERIFIED
    if PENDING in statuses:
        return PENDING
    if MISSING in statuses or SKIPPED in statuses:
        return MISSING
    if all(s in {PASS, NOT_APPLICABLE} for s in statuses):
        return PASS
    return NOT_VERIFIED


def evaluate(checks, matrix: dict, repo: str, risk_level: str, expected_head: str) -> dict:
    trusted_sources = matrix.get('trustedCheckSources') or {}
    normalised = [normalise_check(c, expected_head, trusted_sources) for c in checks]
    normalised = mark_special_not_applicable(normalised)
    requirements = effective_requirements(matrix, repo, risk_level)
    groups = [evaluate_group(normalised, spec, matrix.get('rolePatterns') or {}) for spec in requirements['required']]
    status = aggregate_group_status(groups)
    return {
        'status': status,
        'requirements': requirements,
        'groups': groups,
        'notApplicableGroups': requirements['notApplicable'],
        'checks': normalised,
        'sourceValidation': {
            'trusted': sum(1 for c in normalised if c['trustedSource']),
            'untrusted': sum(1 for c in normalised if not c['trustedSource']),
            'missingWorkflowRun': sum(1 for c in normalised if c['trustStatus'] == UNVERIFIED_WORKFLOW),
            'stale': sum(1 for c in normalised if c['trustStatus'] == STALE),
        },
    }
