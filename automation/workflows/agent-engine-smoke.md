---
description: Verifies the configured Codex-compatible model endpoint with a read-only repository probe.
on:
  workflow_dispatch:

permissions:
  contents: read

engine:
  id: codex
  model: deepseek-chat
  env:
    OPENAI_BASE_URL: https://api.deepseek.com/v1
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

network: defaults
tools:
  github:
    toolsets: [repos]
  bash: false
  cli-proxy: false
safe-outputs:
  noop:
timeout-minutes: 5
---

# Agent Engine Smoke Test

Perform a read-only probe of `${{ github.repository }}`. Use GitHub read tools to
read repository metadata and the default branch. Return a concise JSON object with
`repository`, `defaultBranch`, and `engine: deepseek-chat`. Do not modify files,
issues, pull requests, or repository settings.
