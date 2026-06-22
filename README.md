# infomaniak-cli

![version](https://img.shields.io/badge/version-0.1.0-blue) ![license](https://img.shields.io/badge/license-MIT-green) ![python](https://img.shields.io/badge/python-%3E%3D3.11-blue) ![platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20mac-lightgrey)

**Unofficial CLI for [Informaniak](https://www.infomaniak.com) — manage your kSuite accounts, kDrive, mail, and services from any terminal or IDE.**

Built for personal and company Informaniak accounts. Token-based auth — no browser session required.

> ⚠️ **Unofficial project** — this is not an official Informaniak product. It is a community tool built independently.
>
> 🤖 **AI-assisted development** — this project was built with AI assistance (Claude, Codex, Hermes). Architecture, tooling decisions, and implementation were developed through human-AI collaboration. The code works and the design is intentional, but it was not written line by line without AI involvement. Contributions are welcome regardless of how they are written.

## Install

Requires Python 3.11+.

Recommended global install with [pipx](https://pipx.pypa.io/):

```bash
pipx install infomaniak-cli
ik version
```

Alternative install with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install infomaniak-cli
ik version
```

Plain `pip` also works, but `pipx` or `uv tool` is preferred for a command-line app because it keeps the CLI isolated from your system Python packages.

```bash
pip install infomaniak-cli
```

Install directly from GitHub:

```bash
pipx install git+https://github.com/VidGuiCode/infomaniak-cli.git
```

For development:

```bash
git clone https://github.com/VidGuiCode/infomaniak-cli.git
cd infomaniak-cli
uv sync
```

## Quick start

```bash
ik setup --profile work
ik auth token
# paste your Informaniak Manager personal API token

ik whoami
ik doctor
ik bootstrap

ik account list
ik account products
ik account services

ik drive list
ik drive list --json
ik drive list --json --raw
```

Context (profile, account, drive) is sticky — set it once and every command uses it. Use `--profile` to override for a single command.

## Commands

| Area | Commands |
|------|----------|
| Setup | `setup`, `whoami`, `doctor` |
| Auth | `auth token`, `auth check`, `auth status` |
| Profile | `profile list`, `show`, `use`, `rename`, `delete` |
| Discovery | `account list`, `products`, `services` |
| kDrive | `drive list` |
| Debug | `debug probe` |

Run `ik <command> --help` for full options on any command.

## Using with AI agents

Any AI agent that can run shell commands (Claude Code, Cursor, Copilot, Hermes, CLI scripts) can use `infomaniak-cli` directly — no MCP server, no protocol, no setup.

### Recommended workflow

```bash
# 1. Orient
ik whoami --json
ik doctor --json

# 2. Discover
ik account list --json
ik account products --json
ik account services --json

# 3. Use services
ik drive list --json
ik drive list --json --raw
```

Use `--json` for structured output. Use `--raw` for full API payloads. Use `--profile` to target a specific account.

## Configuration

Login state is stored in your platform's app-data folder:

- **Windows:** `C:\Users\<user>\AppData\Roaming\infomaniak-cli\`
- **macOS:** `~/Library/Application Support/infomaniak-cli/`
- **Linux:** `~/.config/infomaniak-cli/`

This directory contains your profile config and API token. Treat it as a secret and do not share or commit it.

`ik auth logout` removes saved auth data. To remove the installed CLI itself:

```bash
pipx uninstall infomaniak-cli
```

If you installed with `uv tool`, run `uv tool uninstall infomaniak-cli`. If you installed with plain `pip`, run `pip uninstall infomaniak-cli`.

## How this differs from other tools

- **Official Informaniak Manager** is the web dashboard. `infomaniak-cli` talks to the API on behalf of a user — no web browser required.
- **One MCP per service** would mean separate integrations for Mail, kDrive, kChat, etc. `infomaniak-cli` is one unified CLI for all kSuite services, with an optional future MCP wrapper.

## Development

```bash
uv sync
uv run pytest -q
uv run ik --help
```

Tests use pytest. See `tests/` for coverage of the API client, config paths, profiles, auth, bootstrap, account discovery, and CLI smoke tests.

## Roadmap

See [`context/ROADMAP.md`](context/ROADMAP.md) (private working context) for planned features. Public docs:

- [`docs/vision.md`](docs/vision.md) — full product vision and service mapping
- [`docs/setup-and-profiles.md`](docs/setup-and-profiles.md) — setup/auth/profile flow
- [`docs/commands.md`](docs/commands.md) — CLI commands reference
- [`docs/security.md`](docs/security.md) — safety, secrets, profile separation
- [`docs/release.md`](docs/release.md) - install and release guidance

## License

[MIT](LICENSE)
