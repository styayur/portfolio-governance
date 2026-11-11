"""Read complete public PR text and real CI metadata without executing PR code."""
import base64
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

try:
    from evidence_gate import fetch_pr, evaluate_checks, external_checks
except ModuleNotFoundError:
    from scripts.evidence_gate import fetch_pr, evaluate_checks, external_checks

MAX_BLOB_BYTES = 512_000
MAX_REVIEW_BYTES = 4_000_000

def api(path):
    result = subprocess.run(['gh', 'api', path], capture_output=True, check=True, text=True)
    return json.loads(result.stdout)

def complete_patch(item):
    patch = item.get('patch') or ''
    if not patch:
        return False
    added = sum(line.startswith('+') and not line.startswith('+++') for line in patch.splitlines())
    removed = sum(line.startswith('-') and not line.startswith('---') for line in patch.splitlines())
    return added == item.get('additions') and removed == item.get('deletions')

def read_blob(repo, path, sha, reader):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('invalid immutable source SHA')
    if not path or path.startswith(('/', '\\')) or '\\' in path or '..' in path.split('/') or any(ord(c) < 32 for c in path):
        raise ValueError('invalid source path')
    data = reader(f'repos/{repo}/contents/{quote(path, safe="/")}?ref={sha}')
    if data.get('type') != 'file' or data.get('encoding') != 'base64' or not 0 <= data.get('size', MAX_BLOB_BYTES + 1) <= MAX_BLOB_BYTES:
        raise ValueError('unsupported or oversized source blob')
    content = base64.b64decode(data['content'].replace('\n', ''), validate=True)
    oid = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
    if len(content) != data['size'] or oid != data.get('sha') or b'\0' in content:
        raise ValueError('blob identity or text validation failed')
    return content.decode('utf-8'), oid

def collect_authorization(repo, number, risk):
    try:
        try:
            import manual_approval as manual
        except ModuleNotFoundError:
            from scripts import manual_approval as manual
        policy = json.loads((Path(__file__).resolve().parents[1] / 'policy/manual-approval.v1.json').read_text())
        result = manual.evaluate(manual.fetch_reviews(repo, number), manual.fetch_pr(repo, number), risk, policy, repo=repo)
        return {k: result.get(k) for k in ['state', 'risk', 'prNumber', 'headSha', 'baseSha', 'diffSha256', 'actions', 'evaluatedAt']}
    except Exception as exc:
        return {'state': 'NOT_VERIFIED', 'error': type(exc).__name__}

def enrich_context(context, risk, *, reader=api, pr_reader=fetch_pr, evaluator=evaluate_checks, authorizer=collect_authorization):
    """Keep the existing diff digest, supplement only with immutable source reads."""
    repo = context.get('repository') or ''
    if not re.fullmatch(r'styayur/[A-Za-z0-9_.-]+', repo) or repo.casefold() == 'styayur/site':
        raise ValueError('repository outside public portfolio scope')
    meta = reader('repos/' + repo)
    if meta.get('private') is not False or meta.get('id') != context.get('repositoryId') or meta.get('full_name') != repo:
        raise ValueError('public repository identity mismatch')
    errors = []; files = []; size = 0
    for original in context.get('files') or []:
        item = dict(original)
        if not complete_patch(item):
            try:
                status = item.get('status'); name = item['filename']
                if status not in {'added', 'removed', 'modified', 'renamed'}:
                    raise ValueError('unsupported change status')
                old, old_oid = ('', None) if status == 'added' else read_blob(repo, item.get('previous_filename') or name, context['baseSha'], reader)
                new, new_oid = ('', None) if status == 'removed' else read_blob(repo, name, context['headSha'], reader)
                item['reviewPatch'] = '\n'.join(difflib.unified_diff(old.splitlines(), new.splitlines(), fromfile='a/' + name, tofile='b/' + name, lineterm='')) + '\n'
                item['reviewSource'] = {'baseSha': context['baseSha'], 'headSha': context['headSha'], 'baseBlob': old_oid, 'headBlob': new_oid, 'coverage': 'COMPLETE_UTF8_BLOBS', 'baseEndsWithNewline': old.endswith('\n'), 'headEndsWithNewline': new.endswith('\n')}
            except Exception as exc:
                errors.append({'path': item.get('filename'), 'error': type(exc).__name__})
        size += len(json.dumps(item, ensure_ascii=False).encode('utf-8'))
        files.append(item)
        if size > MAX_REVIEW_BYTES:
            raise ValueError('TOTAL_REVIEW_INPUT_BUDGET_EXCEEDED')
    pr = pr_reader(repo, context['prNumber'])
    if pr.get('headRefOid') != context['headSha'] or pr.get('baseRefOid') != context['baseSha']:
        raise ValueError('PR binding changed while collecting review context')
    if pr.get('checksTruncated'):
        errors.append({'error': 'CHECK_ROLLUP_TRUNCATED'})
    matrix = evaluator(external_checks(pr.get('checks') or []), risk['risk'], repo=repo, expected_head=context['headSha'])
    return {**context, 'files': files, 'reviewInputComplete': not errors, 'reviewInputErrors': errors,
            'observedEvidenceMatrix': matrix,
            'authenticatedAuthorization': authorizer(repo, context['prNumber'], risk),
            'evidenceCollection': {'source': 'protected code reading GitHub API', 'headSha': context['headSha'], 'baseSha': context['baseSha'], 'executesPrCode': False}}
