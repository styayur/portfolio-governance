from pathlib import Path
import hashlib, json, yaml
root = Path(__file__).resolve().parents[2]
workflows_dir = root / 'automation' / 'workflows'
catalog_path = root / 'automation' / 'catalog' / 'workflow-catalog.json'
old = json.loads(catalog_path.read_text())
records = []
for path in sorted(workflows_dir.glob('*.md')):
    text = path.read_text()
    end = text.find('\n---\n', 4)
    front = yaml.safe_load(text[4:end])
    lock = path.with_suffix('.lock.yml')
    records.append({
        'id': path.stem,
        'path': str(path.relative_to(root)).replace('\\','/'),
        'sha256': hashlib.sha256(text.encode()).hexdigest(),
        'lockPath': str(lock.relative_to(root)).replace('\\','/'),
        'lockSha256': hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
        'compiled': lock.exists(),
        'engine': front.get('engine', {}).get('id') if isinstance(front.get('engine'), dict) else front.get('engine'),
        'model': front.get('engine', {}).get('model') if isinstance(front.get('engine'), dict) else front.get('model'),
        'triggers': sorted((front.get('on') or {}).keys()) if isinstance(front.get('on'), dict) else [str(front.get('on'))],
        'permissions': front.get('permissions', {}),
        'safeOutputs': sorted((front.get('safe-outputs') or {}).keys()),
        'maxTurns': front.get('max-turns'),
        'maxAiCredits': front.get('max-ai-credits'),
        'maxDailyAiCredits': front.get('max-daily-ai-credits'),
        'timeoutMinutes': front.get('timeout-minutes')
    })
old['workflows'] = records
old['generatedBy'] = 'gh-aw v1.0.1'
old['sourceCatalog'] = 'githubnext/agentics'
old['centralServices'] = [
    {'id': 'evidence-gate', 'kind': 'deterministic-reusable-workflow', 'path': '.github/workflows/reusable-portfolio-gate.yml', 'status': 'EXISTING'},
    {'id': 'portfolio-project-sync', 'kind': 'github-actions', 'path': '.github/workflows/project-sync.yml', 'status': 'EXISTING'},
    {'id': 'dependabot-risk-lifecycle', 'kind': 'github-actions', 'path': '.github/workflows/risk-operations.yml', 'status': 'PR_21_BLOCKED'},
    {'id': 'final-acceptance', 'kind': 'github-actions', 'path': '.github/workflows/final-acceptance.yml', 'status': 'PR_21_BLOCKED'},
    {'id': 'governance-drift', 'kind': 'github-actions', 'path': '.github/workflows/portfolio-audit.yml', 'status': 'EXISTING'},
    {'id': 'automation-cost-monitoring', 'kind': 'gh-aw-audit', 'path': 'automation/reports/agent-permission-audit.json', 'status': 'CATALOGED'}
]
catalog_path.write_text(json.dumps(old, ensure_ascii=False, indent=2) + '\n')
print('catalog refreshed', len(records))
