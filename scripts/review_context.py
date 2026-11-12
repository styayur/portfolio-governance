"""Read complete public PR text and real CI metadata without executing PR code."""
import base64
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

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

def read_blob(repo, path, sha, reader, trees):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('invalid immutable source SHA')
    if not path or path.startswith(('/', '\\')) or '\\' in path or '..' in path.split('/') or any(ord(c) < 32 for c in path):
        raise ValueError('invalid source path')
    if sha not in trees:
        commit = reader(f'repos/{repo}/git/commits/{sha}')
        tree_sha = (commit.get('tree') or {}).get('sha')
        if commit.get('sha') != sha or not re.fullmatch(r'[0-9a-f]{40}', str(tree_sha)):
            raise ValueError('commit/tree identity mismatch')
        tree = reader(f'repos/{repo}/git/trees/{tree_sha}?recursive=1')
        if tree.get('sha') != tree_sha or tree.get('truncated') is not False:
            raise ValueError('tree identity mismatch or incomplete tree')
        trees[sha] = {item['path']: item for item in tree['tree']}
    entry = trees[sha].get(path) or {}
    if entry.get('type') != 'blob' or entry.get('mode') not in {'100644', '100755'} or not 0 <= entry.get('size', MAX_BLOB_BYTES + 1) <= MAX_BLOB_BYTES:
        raise ValueError('source path is not a bounded regular Git blob')
    expected = entry.get('sha')
    if not re.fullmatch(r'[0-9a-f]{40}', str(expected)):
        raise ValueError('invalid tree blob identity')
    data = reader(f'repos/{repo}/git/blobs/{expected}')
    if data.get('sha') != expected or data.get('encoding') != 'base64' or data.get('size') != entry['size']:
        raise ValueError('unsupported or oversized source blob')
    content = base64.b64decode(data['content'].replace('\n', ''), validate=True)
    oid = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
    if len(content) != data['size'] or oid != data.get('sha') or b'\0' in content:
        raise ValueError('blob identity or text validation failed')
    return content.decode('utf-8'), oid

def lf_lines(text):
    """Split only at LF, preserving CR and every Unicode code point."""
    chunks = text.split('\n')
    return [line + '\n' for line in chunks[:-1]] + ([chunks[-1]] if chunks[-1] else [])

def exact_text_diff(old, new, name):
    parts = difflib.unified_diff(lf_lines(old), lf_lines(new), fromfile='a/' + name, tofile='b/' + name)
    return ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n' for line in parts)

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

def enrich_context(context, risk, *, expected_repository, reader=api, pr_reader=fetch_pr, evaluator=evaluate_checks, authorizer=collect_authorization):
    """Keep the existing diff digest, supplement only with immutable source reads."""
    repo = context.get('repository') or ''
    if repo != expected_repository:
        raise ValueError('review context does not match the protected caller repository')
    if not re.fullmatch(r'styayur/[A-Za-z0-9_.-]+', repo) or repo.casefold() == 'styayur/site':
        raise ValueError('repository outside public portfolio scope')
    expected = context.get('expectedChangedFileCount')
    if type(expected) is not int or not 0 < expected <= 3000 or expected != len(context.get('files') or []) or context.get('changedFileCount') != expected:
        raise ValueError('PR file coverage count is missing or incomplete')
    meta = reader('repos/' + repo)
    if meta.get('private') is not False or meta.get('id') != context.get('repositoryId') or meta.get('full_name') != repo:
        raise ValueError('public repository identity mismatch')
    errors = []; files = []; size = 0; trees = {}
    for original in context.get('files') or []:
        item = dict(original)
        workflow_file = str(item.get('filename') or '').startswith(('.github/workflows/', 'automation/workflows/')) and str(item.get('filename') or '').endswith(('.yml', '.yaml'))
        if workflow_file or not complete_patch(item):
            try:
                status = item.get('status'); name = item['filename']
                if status not in {'added', 'removed', 'modified', 'renamed'}:
                    raise ValueError('unsupported change status')
                old, old_oid = ('', None) if status == 'added' else read_blob(repo, item.get('previous_filename') or name, context['baseSha'], reader, trees)
                new, new_oid = ('', None) if status == 'removed' else read_blob(repo, name, context['headSha'], reader, trees)
                item['reviewPatch'] = exact_text_diff(old, new, name)
                item['reviewBaseContent'] = old
                item['reviewHeadContent'] = new
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
            'evidenceCollection': {'source': 'protected code reading GitHub API', 'repository': expected_repository, 'headSha': context['headSha'], 'baseSha': context['baseSha'], 'executesPrCode': False}}
