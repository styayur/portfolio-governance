"""Seal existing model credentials to two approved GitHub repository public keys.

Runs only in trusted Actions. The local operator receives ciphertext and uses
their own authorized GitHub CLI session to store it; plaintext is never returned.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

ALLOWED = {'styayur/petite-grace': 1451642496, 'styayur/Skimmer-Scraper': 1450106896}
APPROVED_KEY_HASHES = {
    'styayur/petite-grace': '835562dd2ffb04c17a7594a13f48bf660ce3db4056937b62b6e2f614c0165ec6',
    'styayur/Skimmer-Scraper': 'c7425bac3919a2684055111ebdc33b226e9b1ae9930877180e37c8ec6ba0cea5',
}
SECRET_NAMES = ('OPENAI_API_KEY', 'PORTFOLIO_AI_REVIEW_API_KEY')


def validate_targets(targets):
    if not isinstance(targets, list) or len(targets) != len(ALLOWED):
        raise ValueError('exactly two approved public repository targets required')
    if {row.get('repo') for row in targets} != set(ALLOWED):
        raise ValueError('target repositories differ from the approved scope')
    for row in targets:
        if row.get('repositoryId') != ALLOWED[row['repo']]:
            raise ValueError('repository identity mismatch')
        if not str(row.get('keyId') or '').isdigit():
            raise ValueError('malformed GitHub public key identity')
        if len(base64.b64decode(row.get('publicKey') or '', validate=True)) != 32:
            raise ValueError('malformed GitHub repository public key')
        if hashlib.sha256(row['publicKey'].encode()).hexdigest() != APPROVED_KEY_HASHES[row['repo']]:
            raise ValueError('public key differs from the independently verified GitHub endpoint')


def main():
    targets = json.loads(Path('automation/bootstrap/approved-public-keys.json').read_text())
    validate_targets(targets)
    if any(not os.environ.get(name) for name in SECRET_NAMES):
        raise RuntimeError('required central model credentials are unavailable')
    from nacl.public import PublicKey, SealedBox

    sealed = []
    for row in targets:
        box = SealedBox(PublicKey(base64.b64decode(row['publicKey'], validate=True)))
        sealed.append({
            'repo': row['repo'], 'repositoryId': row['repositoryId'], 'keyId': row['keyId'],
            'secrets': [{'name': name, 'encrypted_value': base64.b64encode(
                box.encrypt(os.environ[name].encode('utf-8'))).decode('ascii')}
                for name in SECRET_NAMES],
        })
    output = Path(os.environ['RUNNER_TEMP']) / 'sealed-agentic-secrets.json'
    record = {'schemaVersion': 1, 'sourceCommit': os.environ['GITHUB_SHA'],
              'runId': os.environ['GITHUB_RUN_ID'], 'targets': sealed}
    with output.open('x', encoding='utf-8') as stream:
        os.chmod(output, 0o600)
        json.dump(record, stream)
    print('Sealed four model credentials for the two approved repository identities; no plaintext exported.')


if __name__ == '__main__':
    main()
