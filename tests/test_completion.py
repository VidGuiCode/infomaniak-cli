"""Tests for shell completion."""

from infomaniak_cli.cli import build_parser
from infomaniak_cli.completion import (
    generate_bash,
    generate_zsh,
    generate_fish,
    generate_powershell,
)

def test_generate_bash_contains_subcommands():
    parser = build_parser()
    script = generate_bash(parser)
    assert "_ik_completion() {" in script
    assert "setup" in script
    assert "account" in script
    assert "drive" in script
    assert "mail" in script
    assert "contacts" in script
    assert "calendar" in script
    assert "chat" in script

def test_generate_zsh_contains_subcommands():
    parser = build_parser()
    script = generate_zsh(parser)
    assert "#compdef ik" in script
    assert "_describe 'command' subcmds" in script
    assert "setup" in script

def test_generate_fish_contains_subcommands():
    parser = build_parser()
    script = generate_fish(parser)
    assert "complete -c ik -f" in script
    assert "function __fish_ik_needs_command" in script
    assert "setup" in script

def test_generate_powershell_contains_subcommands():
    parser = build_parser()
    script = generate_powershell(parser)
    assert "Register-ArgumentCompleter -Native -CommandName ik -ScriptBlock" in script
    assert "'setup'" in script
