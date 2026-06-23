# Install and Release Guidance

`infomaniak-cli` is a Python CLI. The installed command is `ik`.

This is different from `plane-cli`: `plane-cli` is developed as a Bun/TypeScript app and released as a Node-compatible npm package tarball. `infomaniak-cli` should use Python packaging because the codebase is Python.

## Recommended User Install

Use `pipx` for a global CLI install:

```bash
pipx install infomaniak-cli --backend pip
ik version
```

Why `pipx`:

- installs the CLI globally;
- keeps dependencies isolated;
- avoids modifying the system Python environment;
- provides clean upgrades and uninstalls.

## Alternative User Install

Use `uv tool` if the user already prefers uv:

```bash
uv tool install infomaniak-cli
ik version
```

Plain `pip` works, but it should not be the primary recommendation for a CLI:

```bash
pip install infomaniak-cli
```

## Install From GitHub

For unreleased code:

```bash
pipx install git+https://github.com/VidGuiCode/infomaniak-cli.git --backend pip
```

For a GitHub release wheel:

```bash
pipx install https://github.com/VidGuiCode/infomaniak-cli/releases/download/v0.1.7/infomaniak_cli-0.1.7-py3-none-any.whl --backend pip
```

## Upgrade

For `pipx` installs:

```bash
pipx upgrade infomaniak-cli
```

For `uv tool` installs:

```bash
uv tool upgrade infomaniak-cli
```

For plain `pip` installs:

```bash
pip install --upgrade infomaniak-cli
```

## Uninstall

For `pipx` installs:

```bash
pipx uninstall infomaniak-cli
```

For `uv tool` installs:

```bash
uv tool uninstall infomaniak-cli
```

For plain `pip` installs:

```bash
pip uninstall infomaniak-cli
```

## Release Artifacts

Python releases should publish:

- source distribution: `.tar.gz`;
- wheel: `.whl`;
- optional GitHub release attaching the same wheel and source archive.

Do not publish private local state:

- `context/`;
- `.agents/`;
- `.codex/`;
- `.codex-tmp/`;
- `.tmp/`;
- `.venv/`;
- profile configs;
- token files.

## Release Verification

Before publishing, verify the built package in a clean install environment:

```bash
uv build
pipx install --force --backend pip dist/infomaniak_cli-0.1.7-py3-none-any.whl
ik version
ik --help
ik setup --profile test --non-interactive
ik whoami --json
ik doctor --json
```

The release is ready when the installed `ik` command works without relying on the source checkout.

## Comparison With plane-cli

| Project | Runtime | Main installer | Artifact | Command mapping |
|---|---|---|---|---|
| `infomaniak-cli` | Python 3.11+ | `pipx` / `uv tool` / `pip` | wheel / sdist | `pyproject.toml [project.scripts]` |
| `plane-cli` | Node.js 20+ | `npm install -g` | npm `.tgz` | `package.json bin` |

Both approaches are normal. The better choice is the native packaging ecosystem for the implementation language.
