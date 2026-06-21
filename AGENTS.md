# AGENTS.md — infomaniak-cli

## Project purpose

`infomaniak-cli` builds a unified Python CLI for Informaniak/kSuite. The installed command is `ik`.

The CLI should let Gui and Hermes manage personal/company Informaniak access through safe profiles, with autodiscovery of accounts/products/services and an optional future MCP wrapper.

## Working directory

Windows path:

```text
E:\Nextcloud\github\infomaniak-cli
```

Git Bash/MSYS path:

```bash
cd '/e/Nextcloud/github/infomaniak-cli'
```

## Private context

`context/` is gitignored. Use it for private notes, rough handoffs, token setup notes, and non-public working context.

Important private files:

- `context/HANDOFF.md`
- `context/TOMORROW.md`

Do not move private context into public docs unless Gui explicitly asks.

## Commands

Because the Windows temp folder may be permission-problematic in this environment, run pytest with a repo-local temp folder:

```bash
mkdir -p .tmp
TMPDIR="$PWD/.tmp" TEMP="$PWD/.tmp" TMP="$PWD/.tmp" uv run pytest -q
```

CLI smoke checks:

```bash
IK_CONFIG_DIR="$PWD/.tmp/manual-config" uv run ik setup --profile cylro --non-interactive
IK_CONFIG_DIR="$PWD/.tmp/manual-config" uv run ik whoami --json
IK_CONFIG_DIR="$PWD/.tmp/manual-config" uv run ik doctor --json
```

## Current architecture

Python package:

```text
src/infomaniak_cli/
  __init__.py
  api.py
  auth.py
  cli.py
  config_paths.py
  doctor.py
  profiles.py
```

Tests:

```text
tests/
  test_api.py
  test_auth.py
  test_cli.py
  test_config_paths.py
  test_profiles.py
```

## Development rules

1. Use TDD for new behavior: write failing test, run it, implement, run tests.
2. Keep setup/profile/auth safe and boring.
3. No real tokens or credentials in git.
4. Keep `context/` private and ignored.
5. Prefer explicit `--profile cylro` in examples for Hermes/cron.
6. For commands with external side effects later, require confirmation and show profile/account/action context.
7. Do not implement destructive operations early: no deleting mail, deleting kDrive files, DNS changes, or user/mailbox deletion until explicit approval.

## Next priority

Continue from `docs/implementation-plan.md`, Phase 3/4:

1. Improve `ik auth token` UX if needed.
2. Add REST API client tests around request construction and safe errors.
3. Investigate easiest Informaniak OAuth/token flow.
4. Implement bootstrap discovery with mocked API responses before live API calls.
