"""Shared safety contracts that every command must satisfy.

These tests introspect the real parser rather than a hand-maintained list, so a
new mutating command cannot ship without the protected-write guarantees. When
one of these fails, the design is working: either add the missing flag, or add a
documented exception below with a reason.
"""

from __future__ import annotations

import argparse
import inspect

import pytest

from infomaniak_cli import cli
from infomaniak_cli.api import InformaniakAPIError
from infomaniak_cli.services.calendar import CalendarError
from infomaniak_cli.services.chat import ChatError
from infomaniak_cli.services.contacts import ContactError
from infomaniak_cli.services.mail import MailError


# Commands that legitimately take --yes without the full service-write contract.
# Each entry needs a reason: an exception must be a decision, not an oversight.
LOCAL_ONLY_YES = {
    "profile delete": "removes local profile config only; never contacts a service",
    "auth logout": "removes locally stored secrets only; never contacts a service",
    "doctor": "--fix-path edits the local PATH, not a service",
    "update": "installs a new version of this CLI locally",
}


def _walk_subcommands(parser: argparse.ArgumentParser, prefix: str = ""):
    """Yield (path, parser) for every subcommand in the tree."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            path = f"{prefix} {name}".strip()
            yield path, sub
            yield from _walk_subcommands(sub, path)


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    options: set[str] = set()
    for action in parser._actions:
        options.update(action.option_strings)
    return options


def _commands_with(option: str) -> list[tuple[str, argparse.ArgumentParser]]:
    parser = cli.build_parser()
    return [
        (path, sub)
        for path, sub in _walk_subcommands(parser)
        if option in _option_strings(sub)
    ]


def _is_local_only(path: str) -> bool:
    return any(path == name or path.startswith(f"{name} ") for name in LOCAL_ONLY_YES)


def test_every_protected_write_offers_a_dry_run():
    """A command that can write unattended must be previewable first."""
    missing = [
        path
        for path, sub in _commands_with("--yes")
        if not _is_local_only(path) and "--dry-run" not in _option_strings(sub)
    ]

    assert missing == [], (
        "these commands accept --yes but offer no --dry-run, so a caller cannot "
        f"preview what they would do: {missing}"
    )


def test_every_protected_write_offers_structured_output():
    """Automation needs a machine-readable result, not just prose."""
    missing = [
        path
        for path, sub in _commands_with("--yes")
        if not _is_local_only(path)
        and not {"--json", "--compact"} <= _option_strings(sub)
    ]

    assert missing == [], f"these protected writes lack --json/--compact: {missing}"


def test_every_dry_run_command_is_also_gated_by_yes():
    """If an action is worth previewing, it is worth gating."""
    missing = [
        path
        for path, sub in _commands_with("--dry-run")
        if "--yes" not in _option_strings(sub)
    ]

    assert missing == [], f"these commands offer --dry-run but no --yes gate: {missing}"


def test_yes_always_has_the_short_form():
    inconsistent = [
        path
        for path, sub in _commands_with("--yes")
        if not _is_local_only(path) and "-y" not in _option_strings(sub)
    ]

    assert inconsistent == [], f"these commands accept --yes but not -y: {inconsistent}"


def test_protected_writes_route_through_the_shared_profile_gate():
    """Every service write must gate --yes on an explicit profile.

    Checked by source inspection so a new command cannot quietly reimplement or
    skip the rule.
    """
    gate_names = (
        "_require_explicit_profile_for_yes",
        "_validate_mail_write_yes",
        "_contacts_write_gate",
        "_calendar_write_gate",
        "_chat_write_gate",
        "_profile_is_explicit",
    )
    def _reaches_gate(func, depth: int = 2) -> bool:
        """True when the handler gates directly or via a helper it delegates to."""
        try:
            source = inspect.getsource(func)
        except (OSError, TypeError):  # pragma: no cover - defensive
            return False
        if any(name in source for name in gate_names):
            return True
        if depth <= 0:
            return False
        # Follow one level of delegation, e.g. cmd_mail_reply -> _mail_reply_forward.
        for helper_name, helper in vars(cli).items():
            if not helper_name.startswith("_") or not callable(helper):
                continue
            if f"{helper_name}(" in source and _reaches_gate(helper, depth - 1):
                return True
        return False

    offenders = []
    for path, sub in _commands_with("--yes"):
        if _is_local_only(path):
            continue
        handler = sub.get_default("func")
        if handler is None:
            continue
        if not _reaches_gate(handler):
            offenders.append(path)

    assert offenders == [], (
        "these protected writes never reference the explicit-profile gate: " f"{offenders}"
    )


def test_api_errors_redact_their_secrets_at_construction():
    secret = "secret-api-token"

    exc = InformaniakAPIError(500, f"failed for {secret}", secrets=[secret])

    assert secret not in str(exc)


@pytest.mark.parametrize(
    "module_name",
    ["mail", "calendar", "contacts", "chat", "dav_discovery"],
)
def test_every_secret_bearing_service_wires_redaction_into_its_error_paths(module_name):
    """A service that holds a credential must scrub it from its own errors.

    These service errors are plain exceptions — they do not self-redact — so the
    protection lives at the raise sites. This asserts each module actually wires
    a redactor in, rather than trusting each new error path to remember.
    """
    module = __import__(
        f"infomaniak_cli.services.{module_name}", fromlist=["*"]
    )
    source = inspect.getsource(module)

    scrubs = "redact_secret" in source or ".replace(self.password" in source
    assert scrubs, (
        f"services/{module_name}.py holds a credential but never scrubs it from an "
        "error message"
    )


@pytest.mark.parametrize(
    "raw, secret",
    [
        ("Authorization: Bearer abc123def456", "abc123def456"),
        ("failed with token=abc123def456", "abc123def456"),
        ("failed with password=abc123def456", "abc123def456"),
    ],
)
def test_shared_output_redactor_scrubs_known_secret_shapes(raw, secret):
    """The output redactor is the last line of defence before the terminal."""
    redacted = cli.redact(raw)

    assert secret not in redacted
    assert "***" in redacted


def test_diff_fields_reports_only_what_changed():
    before = {"summary": "Old", "location": "Office", "unchanged": 1}
    after = {"summary": "New", "location": "Office", "unchanged": 1}

    assert cli._diff_fields(before, after) == {
        "summary": {"before": "Old", "after": "New"}
    }


def test_diff_fields_handles_added_and_removed_keys():
    assert cli._diff_fields({"a": 1}, {"a": 1, "b": 2}) == {
        "b": {"before": None, "after": 2}
    }
    assert cli._diff_fields({"a": 1, "b": 2}, {"a": 1}) == {
        "b": {"before": 2, "after": None}
    }


def test_diff_fields_is_empty_for_identical_states():
    assert cli._diff_fields({"a": 1}, {"a": 1}) == {}


def test_notified_field_is_accurate_not_merely_present():
    """`notified` must state the real external effect, not a blanket false.

    A blanket `notified: false` would be worse than no field at all: mail send
    and chat post genuinely do reach other people. This asserts the outbound
    commands claim notification and the local-only ones do not.
    """
    source = inspect.getsource(cli)

    # outbound communication must report notified: True on success
    for marker in (
        '"sent": True, "notified": True',
        '"posted": True, "notified": True',
    ):
        assert marker in source, f"missing accurate notification claim: {marker}"

    # a write that reaches nobody must say so rather than stay silent
    for marker in (
        '"drafted": True, "notified": False',
        '"created": True, "existed": False, "notified": False',
    ):
        assert marker in source, f"missing explicit no-notification claim: {marker}"


def test_every_dry_run_that_reports_notified_reports_false():
    """A dry run notifies nobody, by definition."""
    source = inspect.getsource(cli)

    for line in source.splitlines():
        if '"dry_run": True' in line and '"notified"' in line:
            assert '"notified": False' in line, (
                f"a dry run must never claim it notified anyone: {line.strip()}"
            )
