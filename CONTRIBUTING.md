# Contributing to infomaniak-cli

Thanks for helping improve `ik`. This project is a small, boring, **read-only**
CLI for Infomaniak/kSuite. Keep changes minimal and prefer the standard library.

## Setup

The project uses [uv](https://docs.astral.sh/uv/).

```bash
uv sync            # create the environment and install dev dependencies
uv run ik --help   # run the CLI from source
```

## Running tests

The suite is fully offline (no network, no live Informaniak API). On
Windows/Git-Bash the system temp dir can be permission-flaky, so pin temp to a
repo-local `.tmp`:

```bash
mkdir -p .tmp
TMPDIR="$PWD/.tmp" TEMP="$PWD/.tmp" TMP="$PWD/.tmp" uv run pytest -q
```

On Linux/macOS the `TMPDIR` pin is harmless but optional. CI
(`.github/workflows/ci.yml`) runs the same suite on Linux (Python 3.11–3.13) and
Windows on every push and pull request.

## Ground rules

- **Read-only.** No service writes (no mail send, kDrive upload/move/delete,
  kChat post, calendar/contact create). Protected writes are a future `0.2.x`
  line with confirmation + `--dry-run`.
- **Stdlib first.** Do not add a runtime dependency without discussing it — the
  project intentionally has none.
- **No secrets, ever.** Never commit tokens, app passwords, or real personal
  data. Tests use `IK_CONFIG_DIR` / tmp paths and injectable transports/clients;
  they must not touch your real config or hit the network.
- **TDD.** Add or update tests for every behavior change. Keep existing tests
  passing.
- **Redaction.** Tokens, passwords, cookies, and `Authorization` headers must be
  redacted from all output and errors.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the module map and the
injectable-transport testing approach.

## Release flow

Maintainers cut releases from `master` (the repo ships via GitHub releases, not
PyPI):

1. Bump the version in `pyproject.toml`, `src/infomaniak_cli/__init__.py`, and
   the README badge; add a `CHANGELOG.md` entry.
2. `mkdir -p .tmp && TMPDIR="$PWD/.tmp" uv run pytest -q` — suite green.
3. `uv build` then `uv run python scripts/check_package_contents.py` and
   `bash scripts/smoke_install.sh`.
4. Commit, `git tag -a vX.Y.Z`, push, and
   `gh release create vX.Y.Z dist/*.whl dist/*.tar.gz`.

See [docs/release.md](docs/release.md) for the full release guidance.
