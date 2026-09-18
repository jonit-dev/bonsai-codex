import json
import os
import re
import shlex

from .patches import (
    DELIMITER_BASE,
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
    # A file redirect, but not to /dev/null: `cmd 2>/dev/null` and `cmd >/dev/null` are
    # ordinary plumbing, and every read that used them was being rejected as a write.
    r">\s*(?!/dev/null\b)[\w./~-]+|"
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
    # The write does not have to start the command: models prefix it with `cd <dir> &&`,
    # a bare `cd <dir>` line, or a `;`. Anchor on the heredoc itself and keep the prefix,
    # so `cd x\ncat > f <<'EOF' ... EOF` rewrites like the bare form. Without this the
    # command falls through to the shell-write scan and the edit is rejected.
    prefix = r"(?P<prefix>[\s\S]*?)"
    path_first = (
        prefix + r"cat\s*>\s*(?P<path>(?:'[^']+'|\"[^\"]+\"|[^\s]+))"
        r"\s*<<\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z0-9_-]*)(?P=quote)"
        r"\s*\n(?P<body>.*)\n(?P=delimiter)\s*;?\s*(?P<tail>[\s\S]*)$"
    )
    heredoc_first = (
        prefix + r"cat\s*<<\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z0-9_-]*)(?P=quote)"
        r"\s*>\s*(?P<path>(?:'[^']+'|\"[^\"]+\"|[^\s]+))"
        r"\s*\n(?P<body>.*)\n(?P=delimiter)\s*;?\s*(?P<tail>[\s\S]*)$"
    )
    match = re.match(path_first, cmd, re.DOTALL) or re.match(heredoc_first, cmd, re.DOTALL)
    if not match:
        return None
    path = unquote_shell_word(match.group("path"))
    if not path:
        return None
    leading = match.group("prefix")
    if FORBIDDEN_SHELL_WRITE.search(leading):
        return None
    command = conditional_apply_patch_command(path, match.group("body"))
    if command is None:
        return None
    rewritten = with_trailing_commands(command, match.group("tail"))
    return None if rewritten is None else leading + rewritten


def rewrite_copy_command(cmd):
    """Turn `mv src dst` / `cp src dst` into a patch for dst when src is readable.

    Models draft into a scratch file and then move it into place; rejecting that throws
    away the whole draft (observed on a real repo: a complete spec lost on `mv`). Reading
    the source here keeps the edit on the patch path, so the destination is still created
    through apply_patch and the unsafe-path check.
    """
    prefix = ""
    cd_prefix = re.match(r"^\s*cd\s+(?:\S+|'[^']*'|\"[^\"]*\")\s*&&\s*", cmd)
    if cd_prefix:
        prefix = cmd[: cd_prefix.end()]
        cmd = cmd[cd_prefix.end():]
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return None
    if len(parts) < 3 or parts[0] not in ("mv", "cp"):
        return None
    source, destination = parts[1], parts[2]
    if not os.path.isfile(source):
        return None
    try:
        if os.path.getsize(source) > 200_000:
            return None
        with open(source, encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        return None
    command = conditional_apply_patch_command(destination, content)
    if command is None:
        return None
    tail = " ".join(shlex.quote(part) for part in parts[3:])
    return prefix + command + (f"\n{tail}" if tail else "")


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


def split_patch_sections(body_lines):
    """Split a heredoc body that closes one patch and opens another into its sections.

    A model replacing a file often writes '*** End Patch' before the second operation:

        *** Begin Patch
        *** Delete File: f
        *** End Patch
        *** Add File: f
        +...

    apply_patch honours the first End marker and silently drops the rest, so the file is
    deleted and never rewritten. Running each section as its own invocation keeps the
    model's intent.
    """
    sections, current = [], []
    for line in body_lines:
        stripped = line.strip()
        if stripped == "*** Begin Patch" and current:
            sections.append(current)
            current = [line]
            continue
        current.append(line)
        if stripped == "*** End Patch":
            sections.append(current)
            current = []
    if any(line.strip() for line in current):
        sections.append(current)
    return ["\n".join(section) for section in sections if any(line.strip() for line in section)]


OPERATION_LINE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File:\s*(?P<path>.+?)\s*$")


def split_patch_operations(patch_text):
    """One apply_patch invocation per file operation.

    apply_patch refuses a patch carrying two operations for the same path ("multiple
    operations target <path>"), and a delete-then-add rewrite is exactly that. Models write
    it either as two sections or as two operations in one section; splitting on the
    operation headers covers both, and keeps each call independent.
    """
    lines = patch_text.splitlines()
    header, footer = "*** Begin Patch", "*** End Patch"
    operations, current = [], None
    for line in lines:
        if line.strip() in (header, footer):
            continue
        if OPERATION_LINE.match(line):
            if current is not None:
                operations.append(current)
            current = [line]
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        operations.append(current)
    if len(operations) < 2:
        return []
    return ["\n".join([header, *operation, footer]) for operation in operations]


def complete_patch(text):
    lines = text.splitlines()
    if not any(line.strip() == "*** Begin Patch" for line in lines):
        lines = ["*** Begin Patch", *lines]
    if not any(line.strip() == "*** End Patch" for line in lines):
        lines = [*lines, "*** End Patch"]
    return "\n".join(lines)


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
        split = split_patch_operations("\n".join(body_lines))
        if split:
            commands = [apply_patch_command(repair_add_file_content_lines(part)) for part in split]
            rewritten = with_trailing_commands("\n".join(commands), trailing)
            return rewritten or rejected_edit_command(cmd, FORBIDDEN_TAIL_MESSAGE)
        sections = split_patch_sections(body_lines)
        if len(sections) > 1:
            commands = []
            for section in sections:
                repaired = repair_add_file_content_lines(complete_patch(section))
                commands.append(apply_patch_command(repaired))
            joined = "\n".join(commands)
            rewritten = with_trailing_commands(joined, trailing)
            return rewritten or rejected_edit_command(cmd, FORBIDDEN_TAIL_MESSAGE)
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
    return (
        rewrite_cat_heredoc(cmd)
        or rewrite_copy_command(cmd)
        or rewrite_echo_redirect(cmd)
        or rewrite_touch(cmd)
    )


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


HEREDOC_START = re.compile(
    r"<<-?\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z0-9_-]*)(?P=quote)"
)


def shell_without_heredoc_bodies(cmd):
    """The shell commands in cmd, with every heredoc body removed.

    A heredoc body is data, not shell. `<!DOCTYPE html>` and '<li><strong>Note' inside a patch
    matched the redirect rule and got whole edits rejected, whatever delimiter the model chose.
    """
    lines = cmd.splitlines()
    kept, index = [], 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        for match in HEREDOC_START.finditer(line):
            delimiter = match.group("delimiter")
            while index < len(lines) and lines[index].strip() != delimiter:
                index += 1
            if index < len(lines):
                kept.append(lines[index])
                index += 1
    return "\n".join(kept)


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
    if "llama-codex apply_patch compatibility" in cmd or DELIMITER_BASE in cmd:
        # A command this proxy generated, fed back through the guard. Scanning or rewriting it
        # again mangles it: the compat block's own `cat >"$patch_file" <<'PATCH_LLAMACODEX'`
        # looks like a shell write, and an HTML patch body matched '>Note' as a redirect.
        return arguments
    # `cd <dir> && apply_patch <<'PATCH' ...` is the same edit command. Without this the
    # patch body falls through to the shell-write scan, where any HTML or shell-looking
    # line inside the patch matches the redirect rule and the whole edit is rejected -
    # observed with a <!DOCTYPE html> patch that never reached apply_patch.
    prefix = ""
    cd_prefix = re.match(r"^\s*cd\s+(?:\S+|'[^']*'|\"[^\"]*\")\s*&&\s*", cmd)
    if cd_prefix:
        prefix = cmd[: cd_prefix.end()]
        stripped = cmd[cd_prefix.end():].lstrip()
    if stripped.startswith("apply_patch"):
        rewritten = rewrite_apply_patch_shell_command(stripped)
        if rewritten:
            data["cmd"] = prefix + rewritten
            return json.dumps(data)
        return arguments
    rewritten = rewrite_shell_write_command(cmd)
    if rewritten:
        data["cmd"] = rewritten
        return json.dumps(data)
    forbidden = FORBIDDEN_SHELL_WRITE
    if not forbidden.search(shell_without_heredoc_bodies(cmd)):
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
