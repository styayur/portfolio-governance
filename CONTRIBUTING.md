# Contributing

Start interactive work in a GitHub Codespace. Keep the change scoped to the governance contract or one repository at a time.

Before opening a PR:

```bash
python3 -m pytest -q
python3 -m compileall -q scripts tests
git diff --check
```

Do not add secrets or private data. Do not weaken a gate to make a PR pass. R3/R4 changes must state their compatibility, migration and security considerations and remain a maintainer decision.
