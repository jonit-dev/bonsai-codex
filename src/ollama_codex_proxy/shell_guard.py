import json
import re
import shlex

from .patches import (
    add_file_patch,
    apply_patch_command,
    apply_patch_compat_command,
    conditional_apply_patch_command,
    is_patch_text,
    patch_delimiter,
    repair_add_file_content_lines,
    repair_wrapped_unified_diff,
)


def unquote_shell_word(value):
    try:
        parts = shlex.split(value)
    except ValueError:
        return None
    if len(parts) != 1:
        return None
    return parts[0]


FORBIDDEN_SHELL_WRITE = re.compile(
    r"(^|[;&|]\s*)touch\b|"
    r"(^|[;&|]\s*)mkdir\s+|"
    r"(^|[;&|]\s*)mv\s+|"
    r"(^|[;&|]\s*)cp\s+|"
    r"(^|[;&|]\s*)rm\s+|"
    r"(^|[;&|]\s*)unlink\s+|"
    r"\bcat\s*>|"
    r"\bcat\s*<<|"
    r"\btee\s+|"
    r"\bsed\s+-i\b|"
    r"\bperl\s+-i\b|"
    r">\s*[\w./~-]+|"
    r"\bpython3?\b.*(\bopen\s*\([^)]*,\s*['\"][wax]|\bopen\s*\([^)]*,\s*mode\s*=\s*['\"][wax]|\bwrite_text\s*\(|\bwrite_bytes\s*\()",
    re.DOTALL,
)


FORBIDDEN_TAIL_MESSAGE = (
    "llama-codex proxy rejected commands chained after a patch heredoc that write files; "
    "send the patch alone, then run the verification command separately."
)


def rejected_edit_command(cmd, message):
    rejected = f"llama-codex proxy rejected edit command: {cmd}"
    return (
        "printf '%s\\n' "
        f"{shlex.quote(message)} "
        f"{shlex.quote(rejected)} "
        ">&2; exit 2"
    )


def with_trailing_commands(command, tail):
    """Keep the commands a model chained after a heredoc, or reject a forbidden tail.

    `cat > f <<'EOF' ... EOF; cat f` is one command with a verification step attached.
    Dropping the tail silently would hide the write's own smoke test from the model;
    returning None means the tail writes files, so the caller rejects the whole command.
    """
    tail = tail.strip()
    if not tail:
        return command
    if FORBIDDEN_SHELL_WRITE.search(tail):
        return None
    return f"{command}\n{tail}"


def rewrite_cat_heredoc(cmd):
    path_first = (
        r"\s*cat\s*>\s*(?P<path>(?:'[^']+'|\"[^\"]+\"|[^\s]+))"
        r"\s*<<\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z0-9_-]*)\2"
        r"\s*\n(?P<body>.*)\n(?P=delimiter)\s*;?\s*(?P<tail>[\s\S]*)$"
    )
    heredoc_first = (
        r"\s*cat\s*<<\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z0-9_-]*)\1"
        r"\s*>\s*(?P<path>(?:'[^']+'|\"[^\"]+\"|[^\s]+))"
        r"\s*\n(?P<body>.*)\n(?P=delimiter)\s*;?\s*(?P<tail>[\s\S]*)$"
    )
    match = re.match(path_first, cmd, re.DOTALL) or re.match(heredoc_first, cmd, re.DOTALL)
    if not match:
        return None
    path = unquote_shell_word(match.group("path"))
    if not path:
        return None
    command = conditional_apply_patch_command(path, match.group("body"))
    if command is None:
        return None
    return with_trailing_commands(command, match.group("tail"))


def rewrite_touch(cmd):
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return None
    if len(parts) < 2 or parts[0] != "touch":
        return None
    paths = [part for part in parts[1:] if not part.startswith("-")]
    if len(paths) != len(parts) - 1:
        return None
    commands = []
    for path in paths:
        patch = add_file_patch(path, "")
        if patch is None:
            return None
        delimiter = patch_delimiter(patch)
        if "/" not in path and path.endswith(".py"):
            package_dir = path[:-3]
            commands.extend(
                [
                    f"if [ ! -e {shlex.quote(path)} ] && [ -d {shlex.quote(package_dir)} ]; then",
                    (
                        "printf '%s\\n' "
                        f"{shlex.quote(f'llama-codex proxy rejected creation of {path}: {package_dir}/ already exists; edit the package files instead.')} "
                        ">&2; exit 2"
                    ),
                    "fi",
                ]
            )
        commands.extend(
            [
                f"if [ -e {shlex.quote(path)} ]; then",
                ":",
                "else",
                f"apply_patch <<'{delimiter}'",
                patch,
                delimiter,
                "fi",
            ]
        )
    return "\n".join(commands)


def rewrite_echo_redirect(cmd):
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return None
    if len(parts) != 4 or parts[0] != "echo" or parts[2] != ">":
        return None
    if parts[1].startswith("-"):
        return None
    return conditional_apply_patch_command(parts[3], parts[1])


def malformed_apply_patch_command(cmd):
    message = (
        "llama-codex proxy rejected malformed apply_patch command: use a heredoc like "
        "apply_patch <<'PATCH' ... PATCH; apply_patch does not accept --file or --patch flags."
    )
    rejected = f"llama-codex proxy rejected edit command: {cmd}"
    return (
        "printf '%s\\n' "
        f"{shlex.quote(message)} "
        f"{shlex.quote(rejected)} "
        ">&2; exit 2"
    )


def rewrite_apply_patch_heredoc_command(cmd):
    match = re.match(
        r"^\s*apply_patch\s*<<\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z0-9_-]*)\1\s*\n",
        cmd,
    )
    if not match:
        return None
    delimiter = match.group("delimiter")
    rest = cmd[match.end():]
    lines = rest.splitlines()
    try:
        first_delimiter_index = lines.index(delimiter)
    except ValueError:
        return None
    body_lines = lines[:first_delimiter_index]
    trailing = "\n".join(lines[first_delimiter_index + 1:])
    if any(line.strip() == "*** End Patch" for line in body_lines):
        body = "\n".join(body_lines)
        repaired = repair_wrapped_unified_diff(body)
        if repaired != body:
            rewritten = with_trailing_commands(apply_patch_compat_command(repaired), trailing)
            return rewritten or rejected_edit_command(cmd, FORBIDDEN_TAIL_MESSAGE)
        repaired = repair_add_file_content_lines(body)
        if repaired != body:
            rewritten = with_trailing_commands(apply_patch_command(repaired), trailing)
            return rewritten or rejected_edit_command(cmd, FORBIDDEN_TAIL_MESSAGE)
        return None
    tail_lines = lines[first_delimiter_index + 1:]
    for tail_index, line in enumerate(tail_lines):
        if line.strip() != "*** End Patch":
            continue
        repaired = "\n".join([*body_lines, line])
        return apply_patch_command(repaired)
    if body_lines and body_lines[0].strip() == "*** Begin Patch":
        repaired = "\n".join([*body_lines, "*** End Patch"])
        return apply_patch_command(repaired)
    return None


def rewrite_apply_patch_shell_command(cmd):
    stripped = cmd.lstrip()
    if not stripped.startswith("apply_patch"):
        return None
    if re.match(r"^\s*apply_patch\s*(?:<<|<)\s*", cmd):
        return rewrite_apply_patch_heredoc_command(cmd)
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return malformed_apply_patch_command(cmd)
    if not parts or parts[0] != "apply_patch":
        return None
    if len(parts) == 1:
        return malformed_apply_patch_command(cmd)
    if "--file" in parts or "--patch" in parts:
        try:
            path = parts[parts.index("--file") + 1]
            patch_or_content = parts[parts.index("--patch") + 1]
        except (ValueError, IndexError):
            return malformed_apply_patch_command(cmd)
        if is_patch_text(patch_or_content):
            return apply_patch_compat_command(patch_or_content)
        return malformed_apply_patch_command(cmd)
    if len(parts) == 2 and is_patch_text(parts[1]):
        return apply_patch_compat_command(parts[1])
    return malformed_apply_patch_command(cmd)


def rewrite_shell_write_command(cmd):
    return rewrite_cat_heredoc(cmd) or rewrite_echo_redirect(cmd) or rewrite_touch(cmd)


def extract_nested_exec_arguments(cmd):
    if not re.match(r"\s*(?:exec_command|[\w.]+\.exec_command)\s*\(", cmd):
        return None
    json_start = cmd.find("{")
    if json_start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(cmd[json_start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("cmd"), str):
        return None
    return data


def apply_exec_guard(name, arguments, reject_shell_writes):
    if not reject_shell_writes or not name:
        return arguments
    if name.rsplit(".", 1)[-1] != "exec_command":
        return arguments
    try:
        data = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    if not isinstance(data, dict):
        return arguments
    cmd = data.get("cmd")
    if not isinstance(cmd, str):
        return arguments
    changed = False
    nested = extract_nested_exec_arguments(cmd)
    if nested is not None:
        data.update(nested)
        cmd = data["cmd"]
        changed = True
    stripped = cmd.lstrip()
    if "llama-codex apply_patch compatibility" in cmd:
        return arguments
    if stripped.startswith("apply_patch"):
        rewritten = rewrite_apply_patch_shell_command(cmd)
        if rewritten:
            data["cmd"] = rewritten
            return json.dumps(data)
        return arguments
    rewritten = rewrite_shell_write_command(cmd)
    if rewritten:
        data["cmd"] = rewritten
        return json.dumps(data)

    forbidden = FORBIDDEN_SHELL_WRITE
    if not forbidden.search(cmd):
        if changed:
            return json.dumps(data)
        return arguments
    rejected = f"llama-codex proxy rejected edit command: {cmd}"
    data["cmd"] = (
        "printf '%s\\n' "
        "'llama-codex proxy rejected this edit command: use apply_patch for file creation/modification; do not use touch, rm, cat >, tee, redirects, sed -i, perl -i, or Python file writes.' "
        f"{shlex.quote(rejected)} "
        ">&2; exit 2"
    )
    return json.dumps(data)
