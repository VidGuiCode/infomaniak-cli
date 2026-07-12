import argparse


def _extract_commands(parser: argparse.ArgumentParser, path: tuple[str, ...] | None = None) -> dict[tuple[str, ...], list[tuple[str, str]]]:
    if path is None:
        path = ("ik",)
    commands = {}
    
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subcmds = []
            helps = {a.dest: a.help for a in action._choices_actions if a.help}
            for name, subparser in action.choices.items():
                desc = helps.get(name) or subparser.description or ""
                subcmds.append((name, desc))
                commands.update(_extract_commands(subparser, path + (name,)))
            commands[path] = subcmds
    return commands


def generate_bash(parser: argparse.ArgumentParser) -> str:
    commands = _extract_commands(parser)
    lines = [
        "_ik_completion() {",
        "    local cur prev words cword",
        "    COMPREPLY=()",
        '    cur="${COMP_WORDS[COMP_CWORD]}"',
        '    prev="${COMP_WORDS[COMP_CWORD-1]}"',
        "",
        "    local cmd_words=()",
        "    for ((i=0; i<COMP_CWORD; i++)); do",
        '        local w="${COMP_WORDS[i]}"',
        '        if [[ "$w" != -* ]]; then',
        '            cmd_words+=("$w")',
        "        fi",
        "    done",
        "",
        '    local cmd_path="${cmd_words[*]}"',
        "",
        '    case "$cmd_path" in',
    ]
    
    for path, subcmds in commands.items():
        if not subcmds:
            continue
        path_str = " ".join(path)
        words = " ".join(name for name, _ in subcmds)
        lines.append(f'        "{path_str}")')
        lines.append(f'            COMPREPLY=( $(compgen -W "{words}" -- "$cur") )')
        lines.append('            ;;')
        
    lines.extend([
        "    esac",
        "}",
        "complete -F _ik_completion ik",
        ""
    ])
    return "\n".join(lines)


def generate_zsh(parser: argparse.ArgumentParser) -> str:
    commands = _extract_commands(parser)
    lines = [
        "#compdef ik",
        "",
        "_ik() {",
        "    local line",
        "    local -a subcmds",
        "    local cmd_words=()",
        "",
        '    for w in "${words[@]:1}"; do',
        '        if [[ "$w" != -* && "$w" != "$words[$CURRENT]" ]]; then',
        '            cmd_words+=("$w")',
        "        fi",
        "    done",
        "",
        '    local cmd_path="ik"',
        '    if (( ${#cmd_words} > 0 )); then',
        '        cmd_path="ik ${(j: :)cmd_words}"',
        "    fi",
        "",
        '    case "$cmd_path" in',
    ]
    
    for path, subcmds in commands.items():
        if not subcmds:
            continue
        path_str = " ".join(path)
        lines.append(f'        "{path_str}")')
        lines.append('            subcmds=(')
        for name, desc in subcmds:
            safe_desc = desc.replace(":", "\\:").replace('"', '\\"')
            lines.append(f'                "{name}:{safe_desc}"')
        lines.append('            )')
        lines.append("            _describe 'command' subcmds")
        lines.append("            ;;")
        
    lines.extend([
        "    esac",
        "}",
        ""
    ])
    return "\n".join(lines)


def generate_fish(parser: argparse.ArgumentParser) -> str:
    commands = _extract_commands(parser)
    lines = [
        "complete -c ik -f",
        "",
        "function __fish_ik_needs_command",
        "    set -l cmd (commandline -opc)",
        "    if test (count $cmd) -eq 1",
        "        return 0",
        "    end",
        "    return 1",
        "end",
        "",
        "function __fish_ik_using_command",
        "    set -l cmd (commandline -opc)",
        "    set -l filtered",
        "    for w in $cmd",
        "        if not string match -q '-*' -- $w",
        "            set filtered $filtered $w",
        "        end",
        "    end",
        "    set -l expected $argv",
        "    if test (count $filtered) -eq (count $expected)",
        "        for i in (seq (count $expected))",
        "            if test $filtered[$i] != $expected[$i]",
        "                return 1",
        "            end",
        "        end",
        "        return 0",
        "    end",
        "    return 1",
        "end",
        "",
    ]
    
    for path, subcmds in commands.items():
        if not subcmds:
            continue
        path_str = " ".join(path)
        for name, desc in subcmds:
            safe_desc = desc.replace('"', '\\"')
            if path == ("ik",):
                lines.append(f'complete -c ik -n "__fish_ik_needs_command" -a {name} -d "{safe_desc}"')
            else:
                lines.append(f'complete -c ik -n "__fish_ik_using_command {path_str}" -a {name} -d "{safe_desc}"')
                
    lines.append("")
    return "\n".join(lines)


def generate_powershell(parser: argparse.ArgumentParser) -> str:
    commands = _extract_commands(parser)
    lines = [
        "$ik_completer = {",
        "    param($wordToComplete, $commandAst, $cursorPosition)",
        "",
        "    $tokens = $commandAst.Tokens | Where-Object { $_.TokenFlags -band [System.Management.Automation.TokenFlags]::CommandName -or $_.TokenFlags -band [System.Management.Automation.TokenFlags]::MemberName -or $_.Kind -eq 'IdentifierOrValue' }",
        "    $cmd_words = @()",
        "    foreach ($token in $tokens) {",
        "        if ($token.Extent.StartOffset -ge $cursorPosition) {",
        "            break",
        "        }",
        "        $val = $token.Text",
        "        if ($val -and !$val.StartsWith('-')) {",
        "            $cmd_words += $val",
        "        }",
        "    }",
        "",
        "    $cmd_path = $cmd_words -join ' '",
        "    switch ($cmd_path) {",
    ]
    
    for path, subcmds in commands.items():
        if not subcmds:
            continue
        path_str = " ".join(path)
        words = ", ".join(f"'{name}'" for name, _ in subcmds)
        lines.append(f"        '{path_str}' {{ $options = @({words}) }}")
        
    lines.extend([
        "    }",
        "",
        "    if ($options) {",
        '        $options | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {',
        "            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)",
        "        }",
        "    }",
        "}",
        "Register-ArgumentCompleter -Native -CommandName ik -ScriptBlock $ik_completer",
        ""
    ])
    return "\n".join(lines)
