import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sealer', ROOT / 'automation/scripts/seal_agentic_bootstrap_secrets.py')
sealer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sealer)


def approved():
    return json.loads((ROOT / 'automation/bootstrap/approved-public-keys.json').read_text())


def test_only_the_verified_public_repository_identities_are_accepted():
    sealer.validate_targets(approved())
    for field, replacement in [('repo', 'styayur/site'), ('repositoryId', 1),
                               ('keyId', ''), ('publicKey', 'not-base64')]:
        rows = copy.deepcopy(approved())
        rows[0][field] = replacement
        with pytest.raises((ValueError, KeyError)):
            sealer.validate_targets(rows)
    with pytest.raises(ValueError):
        sealer.validate_targets([approved()[0], approved()[0]])
    rows = approved()
    rows[0]['publicKey'], rows[1]['publicKey'] = rows[1]['publicKey'], rows[0]['publicKey']
    with pytest.raises(ValueError, match='independently verified'):
        sealer.validate_targets(rows)
