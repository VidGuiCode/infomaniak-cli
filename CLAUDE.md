# CLAUDE.md — infomaniak-cli

This project builds `infomaniak-cli`, a Python CLI installed as `ik`.

## Goal

One CLI for Informaniak/kSuite, supporting multiple profiles such as `cylro` and `personal`, so Gui and Hermes can safely access company and personal Informaniak resources.

Do not build one MCP per service. Build the CLI/library first; add one optional MCP wrapper later.

## Key design decisions

- `ik setup` creates/updates profiles directly.
- Profiles are first-class and separate personal/company accounts.
- `ik bootstrap` should eventually autodiscover IDs rather than requiring Gui to hunt for them manually.
- Use explicit `--profile cylro` in cron/Hermes examples.
- Start read-only. Writes/sends/uploads must show profile/account/action context and require confirmation.

## Important files

- `README.md` — public overview.
- `docs/vision.md` — full vision.
- `docs/setup-and-profiles.md` — setup/auth/profile UX.
- `docs/commands.md` — proposed commands.
- `docs/security.md` — safety model.
- `docs/implementation-plan.md` — phased build plan.
- `context/HANDOFF.md` — private detailed handoff, gitignored.
- `context/TOMORROW.md` — private next-session starting notes, gitignored.

## Run tests

On this Windows/Git-Bash environment, use repo-local temp paths:

```bash
mkdir -p .tmp
TMPDIR="$PWD/.tmp" TEMP="$PWD/.tmp" TMP="$PWD/.tmp" uv run pytest -q
```

## Smoke test

```bash
IK_CONFIG_DIR="$PWD/.tmp/manual-config" uv run ik setup --profile cylro --non-interactive
IK_CONFIG_DIR="$PWD/.tmp/manual-config" uv run ik whoami --json
IK_CONFIG_DIR="$PWD/.tmp/manual-config" uv run ik doctor --json
```

## Current implementation state

Implemented foundation:

- uv Python project
- console script `ik`
- profile config path resolver
- JSON-backed profile storage
- token store
- basic secret redaction helper
- `ik setup`
- `ik whoami`
- `ik doctor`
- `ik profile list/show/use`
- `ik auth status/token`
- pytest suite

Not implemented yet:

- real Informaniak OAuth/browser login
- real REST API requests
- bootstrap account/product/service discovery
- kDrive/Mail/kChat/kMeet modules
- MCP wrapper

## Style

Keep implementation small and boring. Prefer stdlib first unless dependency improves clarity significantly. Do not add secrets to the repository.
