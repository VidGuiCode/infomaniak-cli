# infomaniak-cli Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a Python CLI named `ik` for Informaniak/kSuite with setup-created profiles, autodiscovery, diagnostics, and safe first service commands.

**Architecture:** CLI-first integration with modular service connectors. The CLI owns auth/profile/bootstrap and service modules; a later MCP server wraps the same library rather than duplicating logic.

**Tech Stack:** Python 3.11+, `uv`, Typer or Click, `httpx` or `requests`, `pydantic` or dataclasses, pytest. Later: IMAP/SMTP stdlib or mail libs, CalDAV/CardDAV libs, MCP SDK.

---

## Phase 0: Repository skeleton

### Task 1: Initialize Python project

**Objective:** Create a minimal installable Python CLI project.

**Files:**

- Create: `pyproject.toml`
- Create: `src/infomaniak_cli/__init__.py`
- Create: `src/infomaniak_cli/cli.py`
- Create: `tests/test_cli_smoke.py`

**Implementation notes:**

- Package name: `infomaniak-cli`
- Python module: `infomaniak_cli`
- Console script: `ik = infomaniak_cli.cli:app`
- Prefer Typer for ergonomic subcommands.

**Verification:**

```bash
uv run ik --help
uv run pytest
```

Expected: CLI help appears and tests pass.

### Task 2: Add repository hygiene

**Objective:** Add gitignore and basic docs/license placeholders.

**Files:**

- Create: `.gitignore`
- Create: `LICENSE` if desired
- Update: `README.md`

**Important `.gitignore` entries:**

```gitignore
.venv/
__pycache__/
.pytest_cache/
.env
*.token.json
secrets.json
config.local.yaml
```

**Verification:**

```bash
git status --short
```

Expected: no secret/config artifacts tracked.

---

## Phase 1: Profile and config foundation

### Task 3: Config path detection

**Objective:** Implement a cross-platform config directory resolver.

**Files:**

- Create: `src/infomaniak_cli/config_paths.py`
- Test: `tests/test_config_paths.py`

**Rules:**

- Windows: use `%APPDATA%/infomaniak-cli` when available.
- POSIX: use `$XDG_CONFIG_HOME/infomaniak-cli` or `~/.config/infomaniak-cli`.
- Allow override via `IK_CONFIG_DIR` for tests.

**Verification:**

```bash
uv run pytest tests/test_config_paths.py -v
```

### Task 4: Profile model and storage

**Objective:** Add profile create/list/show/use storage without auth yet.

**Files:**

- Create: `src/infomaniak_cli/profiles.py`
- Modify: `src/infomaniak_cli/cli.py`
- Test: `tests/test_profiles.py`

**Commands:**

```bash
ik profile list
ik profile show
ik profile use cylro
```

**Notes:**

- Store profiles as YAML or JSON.
- Store default/current profile in a small config file.
- Tests should use `IK_CONFIG_DIR` tempdir.

**Verification:**

```bash
uv run pytest tests/test_profiles.py -v
```

---

## Phase 2: Setup-first UX

### Task 5: `ik setup` creates profile

**Objective:** Implement setup flow that creates/updates a profile before real auth is wired.

**Files:**

- Modify: `src/infomaniak_cli/cli.py`
- Modify: `src/infomaniak_cli/profiles.py`
- Test: `tests/test_setup.py`

**Behavior:**

```bash
ik setup --profile cylro --non-interactive
```

Creates profile `cylro`, marks it default if no default exists.

**Verification:**

```bash
uv run ik setup --profile cylro --non-interactive
uv run ik profile show
```

### Task 6: `ik whoami` and `ik doctor`

**Objective:** Add diagnostic commands that work even before real Informaniak auth.

**Files:**

- Modify: `src/infomaniak_cli/cli.py`
- Create: `src/infomaniak_cli/doctor.py`
- Test: `tests/test_doctor.py`

**Initial behavior:**

- show active profile;
- show whether token exists;
- show configured account/mailbox/drive IDs if present;
- return non-zero only for serious config errors.

**Verification:**

```bash
uv run ik whoami
uv run ik doctor
```

---

## Phase 3: Informaniak API client and auth

### Task 7: API client shell

**Objective:** Add REST client with base URL, bearer token, JSON handling, rate-limit-friendly errors.

**Files:**

- Create: `src/infomaniak_cli/api.py`
- Test: `tests/test_api.py`

**Features:**

- `get(path, params=None)`
- `post(path, json=None)`
- error class with status code and safe message
- redact Authorization headers from errors

**Verification:**

Use mocked HTTP responses in tests.

### Task 8: Auth token storage

**Objective:** Store/retrieve token per profile.

**Files:**

- Create: `src/infomaniak_cli/auth.py`
- Modify: `src/infomaniak_cli/cli.py`
- Test: `tests/test_auth.py`

**Commands:**

```bash
ik auth status
ik --profile cylro auth token
ik auth logout
```

For first version, token paste is acceptable. OAuth browser flow can come later.

**Safety:**

- never print full token;
- redact in logs/errors.

---

## Phase 4: Bootstrap/autodiscovery

### Task 9: Bootstrap profile/account discovery

**Objective:** Discover authenticated user and accessible accounts.

**Files:**

- Create: `src/infomaniak_cli/bootstrap.py`
- Create: `src/infomaniak_cli/services/admin.py`
- Modify: `src/infomaniak_cli/cli.py`
- Test: `tests/test_bootstrap.py`

**API candidates from docs:**

- profile endpoints under `/2/profile`
- accounts endpoints under `/1/accounts`
- account products/services endpoints under `/1/accounts/{account_id}/products` and `/1/accounts/{account_id}/services`
- my kSuite endpoints under `/1/my_ksuite/current` or `/1/my_ksuite/{id}`

**Behavior:**

- if one account: choose it automatically;
- if multiple: interactive picker;
- in non-interactive mode: require `--account-id` or fail with clear choices.

### Task 10: Discover mail/kDrive/kChat/kMeet defaults

**Objective:** Extend bootstrap to find service IDs and choose defaults.

**Files:**

- Modify: `src/infomaniak_cli/bootstrap.py`
- Modify: `src/infomaniak_cli/services/admin.py`
- Create: `src/infomaniak_cli/services/drive.py`
- Create: `src/infomaniak_cli/services/chat.py`
- Create: `src/infomaniak_cli/services/meet.py`
- Tests: service bootstrap tests with mocked responses

**Behavior:**

- discover mail hostings and mailboxes;
- discover kDrive list;
- discover kChat teams/channels if accessible;
- discover kMeet rooms/settings if accessible;
- save selected defaults in profile.

---

## Phase 5: First useful service commands

### Task 11: Admin read-only commands

**Objective:** Add account/product/mailbox/alias listing.

**Commands:**

```bash
ik admin accounts
ik admin products
ik admin mailboxes
ik admin aliases
```

**Verification:**

- mocked tests;
- later live test with real token.

### Task 12: kDrive search/list/download

**Objective:** Add read-only kDrive commands.

**Commands:**

```bash
ik drive list
ik drive search "invoice"
ik drive info <file_id>
ik drive download <file_id>
```

**Safety:**

- downloads to current directory or `--output`;
- never overwrite without confirmation or `--force`.

### Task 13: Mail read-only IMAP commands

**Objective:** Add unread/search/read for actual mailbox content.

**Commands:**

```bash
ik mail unread
ik mail search "invoice"
ik mail read <message_id>
```

**Notes:**

- store IMAP username/app password per profile or mailbox;
- use safe summaries for Hermes output;
- do not dump giant raw MIME by default.

### Task 14: kChat channels/post

**Objective:** Add kChat channel list and protected post.

**Commands:**

```bash
ik chat channels
ik chat post --channel admin "Message"
```

**Safety:**

Before posting, display profile/team/channel/message and require confirmation unless `--yes` is provided with explicit `--profile`.

---

## Phase 6: JSON output and Hermes readiness

### Task 15: Add output formatting layer

**Objective:** Support human, compact, and JSON output consistently.

**Flags:**

```bash
--json
--compact
```

**Rules:**

- JSON output must be stable and parseable;
- errors should be structured in JSON mode;
- compact mode should be good for Hermes terminal calls.

### Task 16: Add optional MCP wrapper plan

**Objective:** Document and stub future MCP wrapper after CLI is useful.

**Files:**

- Create: `src/infomaniak_cli/mcp_server.py`
- Create: `docs/mcp.md`

**Initial MCP tools:**

- whoami
- doctor
- mail_search
- mail_read
- drive_search
- drive_download
- admin_mailboxes
- chat_post

Do not build MCP before CLI auth/profile/bootstrap is solid.

---

## Definition of done for MVP

MVP is done when these work:

```bash
ik setup --profile cylro
ik whoami
ik doctor
ik admin accounts
ik admin mailboxes
ik drive search "invoice"
ik mail unread
```

And all sensitive writes are either not implemented or protected by confirmations.
