from pathlib import Path
import json, hashlib, subprocess, re

root = Path(__file__).resolve().parents[2]
reports = root / 'automation' / 'reports'
reports.mkdir(parents=True, exist_ok=True)
catalog_path = root / 'automation' / 'catalog' / 'workflow-catalog.json'
catalog = json.loads(catalog_path.read_text())

# Rebuild catalog with compiled lock paths and budget metadata.
workflows = []
for item in catalog['workflows']:
    md = root / item['path']
    lock = md.with_suffix('.lock.yml')
    workflows.append({**item, 'lockPath': str(lock.relative_to(root)).replace('\\','/'), 'compiled': lock.exists(), 'budget': 'bounded'})
catalog['workflows'] = workflows
catalog['centralServices'] = [
    {'id': 'evidence-gate', 'kind': 'deterministic-reusable-workflow', 'path': '.github/workflows/reusable-portfolio-gate.yml', 'status': 'EXISTING'},
    {'id': 'portfolio-project-sync', 'kind': 'github-actions', 'path': '.github/workflows/project-sync.yml', 'status': 'EXISTING'},
    {'id': 'dependabot-risk-lifecycle', 'kind': 'github-actions', 'path': '.github/workflows/risk-operations.yml', 'status': 'PR_21_BLOCKED'},
    {'id': 'final-acceptance', 'kind': 'github-actions', 'path': '.github/workflows/final-acceptance.yml', 'status': 'PR_21_BLOCKED'},
    {'id': 'governance-drift', 'kind': 'github-actions', 'path': '.github/workflows/portfolio-audit.yml', 'status': 'EXISTING'},
    {'id': 'automation-cost-monitoring', 'kind': 'gh-aw-audit', 'path': 'automation/reports/agent-permission-audit.json', 'status': 'CATALOGED'}
]
catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n')
(reports / 'workflow-catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n')

# Static authorization policy proposal. It is not active until the owner authorizes a trust-root change.
policy = {
  'schemaVersion': 1,
  'status': 'PROPOSED',
  'activation': 'OWNER_AUTHORIZATION_REQUIRED',
  'selfApprovalAllowed': False,
  'description': 'Separate authorization class from risk tier. This proposal does not activate itself or change current R3/R4 behavior.',
  'classes': {
    'AUTO_AUTHORIZED': {'description': 'Non-trust-root change with complete required evidence; eligible for automatic merge after matrix and independent review.', 'autoMerge': True},
    'PREAUTHORIZED_CONDITIONAL': {'description': 'R3/R4 engineering change covered by an existing owner authorization record with matching scope and policy version.', 'autoMerge': True},
    'OWNER_AUTHORIZATION_REQUIRED': {'description': 'Trust-root, credential, workflow-source, external side-effect, or policy-bound change requiring a fresh owner authorization record.', 'autoMerge': False},
    'PROHIBITED': {'description': 'Operations that would expand the agent trust boundary or self-authorize a policy change.', 'autoMerge': False}
  },
  'trustRootPaths': [
    '.github/workflows/reusable-portfolio-gate.yml',
    '.github/workflows/portfolio-gate.yml',
    '.github/workflows/final-acceptance.yml',
    '.github/workflows/risk-operations.yml',
    'scripts/evidence_gate.py',
    'scripts/evidence_matrix.py',
    'scripts/authorization_policy.py',
    'policy/rollout.json',
    'policy/evidence-matrix.v1.json',
    'policy/r4-authorization.v1.json',
    'policy/gate-pin.json',
    '.github/actions/**'
  ],
  'authorizationRecord': {
    'requiredFields': ['authorizationId', 'ownerIdentity', 'scope', 'policyVersion', 'commitSha', 'issuedAt', 'expiresAt', 'signature'],
    'maxValidityHours': 24,
    'rejectsSelfIssued': True,
    'rejectsScopeMismatch': True,
    'rejectsExpired': True
  },
  'activationRule': 'A new policy or trust-root change must be authorized by an existing protected policy and an independent owner authorization record. A PR cannot authorize its own changes.'
}
(root / 'policy' / 'r4-authorization.v1.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2) + '\n')
(reports / 'r4-authorization-policy.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2) + '\n')

# Initial coverage report; refreshed by deployment and run verification.
repo_names = [line.strip() for line in subprocess.check_output(['gh','repo','list','styayur','--visibility','public','--limit','100','--json','nameWithOwner','--jq','.[].nameWithOwner'], text=True).splitlines() if line.strip()]
coverage = {
  'schemaVersion': 1,
  'generatedAt': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat().replace('+00:00','Z'),
  'source': 'GitHub public repository enumeration plus default-branch workflow contents',
  'expectedRepositories': len(repo_names),
  'privateRepositoryExcluded': 'styayur/site',
  'coreWorkflows': ['issue-triage','independent-pr-review','ci-doctor','security-review','dependency-remediation','evidence-gate'],
  'repositories': [{'repository': r, 'coreDeployment': 'NOT_VERIFIED', 'actualRuns': {'success': 0, 'failure': 0, 'pending': 0}} for r in repo_names],
  'summary': {'coveredRepositories': 0, 'workflowsDeployed': 0, 'workflowsActuallyRunSuccessfully': 0},
  'status': 'BLOCKED',
  'note': 'Deployment PRs and actual successful runs are required; catalog compilation alone is not coverage.'
}
(reports / 'deployment-coverage.json').write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + '\n')

# Permission audit from compiled lock manifests.
permission_records = []
for item in workflows:
    lock = root / item['lockPath']
    text = lock.read_text(errors='replace')
    manifest = {}
    match = re.search(r'^# gh-aw-manifest: (\{.*\})$', text, re.M)
    if match:
        manifest = json.loads(match.group(1))
    permission_records.append({
      'workflow': item['id'],
      'lockPath': item['lockPath'],
      'secrets': manifest.get('secrets', []),
      'actions': [a.get('repo') for a in manifest.get('actions', [])],
      'containers': [c.get('image') for c in manifest.get('containers', [])],
      'mcpServers': [s.get('name') for s in manifest.get('mcp_servers', [])],
      'safeOutputTools': next((s.get('tools', []) for s in manifest.get('mcp_servers', []) if s.get('name') == 'safeoutputs'), []),
      'threatDetection': manifest.get('threat_detection'),
      'readOnlyAgentTools': manifest.get('mcp_servers', [])
    })
audit = {
  'schemaVersion': 1,
  'generatedAt': coverage['generatedAt'],
  'principle': 'Agents receive read-only tools; writes only through explicit safe outputs or a separately scoped App.',
  'workflows': permission_records,
  'findings': [
    {'severity': 'INFO', 'finding': 'All five production catalog workflows compile with bounded max-turns and AIC budgets.'},
    {'severity': 'NOT_VERIFIED', 'finding': 'No production repository has an exact-head successful run for the five workflows yet.'},
    {'severity': 'MEDIUM', 'finding': 'The Codex engine does not support bash command allow-listing; review workflows use bash:false. Other workflows use full bash inside the sandbox and must be run-verified.'}
  ],
  'status': 'NOT_VERIFIED'
}
(reports / 'agent-permission-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')

# Evidence matrix extension.
evidence = {
  'schemaVersion': 1,
  'extends': 'policy/evidence-matrix.v1.json',
  'agenticRequirements': {
    'R0': {'agents': ['issue-triage'], 'independentReview': False},
    'R1': {'agents': ['issue-triage','independent-pr-review','ci-doctor'], 'independentReview': False},
    'R2': {'agents': ['issue-triage','independent-pr-review','ci-doctor','security-review','dependency-remediation'], 'independentReview': True},
    'R3': {'agents': ['all-core'], 'independentReview': True, 'specialistEvidence': True, 'manualAuthorization': 'PROPOSED'},
    'R4': {'agents': ['all-core'], 'independentReview': True, 'specialistEvidence': True, 'authorizationClass': 'OWNER_AUTHORIZATION_REQUIRED'}
  },
  'evidenceStates': ['MISSING','STALE','SKIPPED','CANCELLED','NOT_APPLICABLE','NOT_VERIFIED','PASS','FAIL'],
  'rule': 'Workflow compilation, AI review comments and model output are not equivalent to real execution or native acceptance.',
  'status': 'CATALOGED_NOT_ACTIVE'
}
(reports / 'evidence-matrix.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')

# Repair loop is implemented as cataloged workflow but not yet exercised in production.
repair = {
  'schemaVersion': 1,
  'status': 'NOT_VERIFIED',
  'workflow': 'ci-doctor',
  'capabilities': ['deduplicate-issues','classify-root-cause','inspect-logs','propose-remediation','create-single-issue'],
  'notYetImplemented': ['automatic-code-fix-pr'],
  'limits': {'maxTurns': 4, 'maxAiCreditsPerRun': 60, 'maxDailyAiCredits': 180, 'timeoutMinutes': 10},
  'runs': [],
  'note': 'CI Doctor is cataloged and compiled. Automatic code-fix PR creation is intentionally not enabled until CI Doctor and PR Fix have successful production trials.'
}
(reports / 'autonomous-repair-results.json').write_text(json.dumps(repair, ensure_ascii=False, indent=2) + '\n')

# Negative acceptance report will be refreshed after tests run.
negative = {
  'schemaVersion': 1,
  'status': 'PENDING',
  'testFile': 'tests/test_agentic_automation.py',
  'cases': [
    'catalog-lock-presence',
    'no-pull-request-target',
    'review-trigger-is-pull-request',
    'review-safe-output-bounds',
    'security-review-read-only',
    'dependency-remediation-draft-only',
    'ci-doctor-main-branch-only',
    'budgets-present',
    'invalid-template-recorded',
    'authorization-self-approval-rejected',
    'reports-present'
  ],
  'note': 'PASS is recorded only after the test suite executes on the exact commit.'
}
(reports / 'negative-acceptance.json').write_text(json.dumps(negative, ensure_ascii=False, indent=2) + '\n')

readiness = {
  'schemaVersion': 1,
  'generatedAt': coverage['generatedAt'],
  'status': 'BLOCKED',
  'repositoryCoverage': {'covered': 0, 'expected': len(repo_names)},
  'workflowCatalog': {'compiled': len(workflows), 'actualSuccessfulProductionRuns': 0},
  'agentEngineSmoke': {'status': 'PASS','runId': 42460722540,'model': 'codex/deepseek-chat','note': 'staging only; not production coverage'},
  'capabilities': {
    'issueTriage': 'CATALOGED_NOT_DEPLOYED',
    'independentPrReview': 'CATALOGED_NOT_DEPLOYED',
    'ciDoctor': 'CATALOGED_NOT_DEPLOYED',
    'securityReview': 'CATALOGED_NOT_DEPLOYED',
    'dependencyRemediation': 'CATALOGED_NOT_DEPLOYED',
    'evidenceGate': 'EXISTING_DEPLOYED_PARTIAL',
    'autonomousRepair': 'NOT_VERIFIED',
    'r4Authorization': 'PROPOSED_NOT_ACTIVE'
  },
  'blockers': ['No production repo has all core workflows deployed on its default branch.', 'No exact-head production runs have been observed for the five agentic workflows.', 'Portfolio Governance #21 remains blocked.', 'TinySTT #9 remains Windows-native and RustSec blocked.'],
  'note': 'Catalog compilation and staging smoke success do not count as production coverage.'
}
(reports / 'final-automation-readiness.json').write_text(json.dumps(readiness, ensure_ascii=False, indent=2) + '\n')
print('reports generated')
