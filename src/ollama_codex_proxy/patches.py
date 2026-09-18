import json
import re
import shlex


DELIMITER_BASE = "PATCH_LLAMACODEX"


def patch_delimiter(patch):
    base = DELIMITER_BASE
    delimiter = base
    counter = 1
    while re.search(rf"^{re.escape(delimiter)}$", patch, re.MULTILINE):
        delimiter = f"{base}_{counter}"
        counter += 1
    return delimiter


def patch_file_line(path):
    if "\n" in path or path.startswith("-"):
        return None
    return path


def add_file_patch(path, content):
    file_line = patch_file_line(path)
    if file_line is None:
        return None
    lines = ["*** Begin Patch", f"*** Add File: {file_line}"]
    content_lines = content.splitlines()
    if not content_lines:
        lines.append("+")
    else:
        lines.extend(f"+{line}" for line in content_lines)
    lines.append("*** End Patch")
    return "\n".join(lines)


def delete_file_patch(path):
    file_line = patch_file_line(path)
    if file_line is None:
        return None
    return "\n".join(["*** Begin Patch", f"*** Delete File: {file_line}", "*** End Patch"])


def apply_patch_command(patch):
    patch = repair_add_file_content_lines(patch)
    delimiter = patch_delimiter(patch)
    return f"apply_patch <<'{delimiter}'\n{patch}\n{delimiter}"


def shorthand_patch_command(patch):
    lines = patch.splitlines()
    if len(lines) < 4:
        return None
    if lines[0].strip() != "*** Begin Patch" or lines[-1].strip() != "*** End Patch":
        return None
    match = re.fullmatch(r"\*\*\*\s+(?!Add File:|Delete File:|Update File:)(?P<path>\S.*)", lines[1].strip())
    if not match:
        return None
    content = []
    for line in lines[2:-1]:
        if not line.startswith("+"):
            return None
        content.append(line[1:])
    return conditional_apply_patch_command(match.group("path"), "\n".join(content))


def apply_patch_compat_command(patch):
    patch = sanitize_patch_text(patch)
    patch = repair_wrapped_unified_diff(patch)
    unified_add = unified_add_file_command(patch)
    if unified_add:
        return unified_add
    patch = repair_add_file_content_lines(patch)
    shorthand = shorthand_patch_command(patch)
    if shorthand:
        return shorthand
    delimiter = patch_delimiter(patch)
    return "\n".join(
        [
            "# llama-codex apply_patch compatibility",
            "patch_file=$(mktemp)",
            "clean_patch_file=$(mktemp)",
            f"cat >\"$patch_file\" <<'{delimiter}'",
            patch,
            delimiter,
            "sed '/^\\*\\*\\* /d' \"$patch_file\" >\"$clean_patch_file\"",
            "python3 - \"$clean_patch_file\" \"$PWD\" <<'PY_LLAMACODEX_DIFF'",
            "import os",
            "import sys",
            "",
            "path, root = sys.argv[1], os.path.abspath(sys.argv[2])",
            "prefix = root.rstrip(os.sep) + os.sep",
            "normalized = []",
            "with open(path, 'r', encoding='utf-8') as handle:",
            "    for line in handle:",
            "        if line.startswith(('--- ', '+++ ')):",
            "            marker, rest = line[:4], line[4:].rstrip('\\n')",
            "            if rest.startswith(prefix):",
            "                rest = rest[len(prefix):]",
            "                line = marker + rest + '\\n'",
            "        normalized.append(line)",
            "with open(path, 'w', encoding='utf-8') as handle:",
            "    handle.writelines(normalized)",
            "PY_LLAMACODEX_DIFF",
            "rc=1",
            "if grep -q '^\\*\\*\\* Begin Patch' \"$patch_file\"; then",
            "  apply_output=$(apply_patch <\"$patch_file\" 2>&1)",
            "  rc=$?",
            "  printf '%s\\n' \"$apply_output\"",
            "  if [ \"$rc\" -eq 0 ] && ! printf '%s\\n' \"$apply_output\" | grep -qi '^Invalid patch'; then",
            "    rm -f \"$patch_file\" \"$clean_patch_file\"",
            "    exit 0",
            "  fi",
            "fi",
            "git apply --recount --whitespace=nowarn \"$clean_patch_file\" || "
            "git apply -p0 --recount --whitespace=nowarn \"$clean_patch_file\"",
            "rc=$?",
            "rm -f \"$patch_file\" \"$clean_patch_file\"",
            "exit $rc",
        ]
    )


def is_patch_text(value):
    if not isinstance(value, str):
        return False
    stripped = value.lstrip()
    return (
        stripped.startswith("*** Begin Patch")
        or stripped.startswith("diff --git ")
        or stripped.startswith("--- ")
    )


def sanitize_patch_text(patch):
    if not isinstance(patch, str):
        return patch
    lines = patch.strip().splitlines()
    if not lines:
        return patch
    if lines[0].strip() == "*** Begin Patch":
        sanitized = []
        for line in lines:
            sanitized.append(line)
            if line.strip() == "*** End Patch":
                break
        return "\n".join(sanitized)
    sanitized = []
    for line in lines:
        if sanitized and re.fullmatch(r"PATCH(?:_[A-Za-z0-9]+)?", line.strip()):
            break
        sanitized.append(line)
    return "\n".join(sanitized)


def repair_add_file_content_lines(patch):
    if not isinstance(patch, str) or "*** Add File:" not in patch:
        return patch
    repaired = []
    in_add_file = False
    for line in patch.splitlines():
        if line.startswith("*** Add File:"):
            in_add_file = True
            repaired.append(line)
            continue
        if line.startswith("*** "):
            in_add_file = False
            repaired.append(line)
            continue
        if in_add_file and not line.startswith("+"):
            repaired.append("+" + line)
            continue
        repaired.append(line)
    if patch.endswith("\n"):
        return "\n".join(repaired) + "\n"
    return "\n".join(repaired)


def repair_wrapped_unified_diff(patch):
    if not isinstance(patch, str):
        return patch
    lines = patch.splitlines()
    if not lines or lines[0].strip() != "*** Begin Patch":
        return patch
    if not any(line.strip() == "*** End Patch" for line in lines):
        return patch
    body = [line for line in lines[1:] if line.strip() != "*** End Patch"]
    first_content = next((line for line in body if line.strip()), "")
    if not (first_content.startswith("--- ") or first_content.startswith("-- ")):
        return patch
    if not any(line.startswith("+++ ") or line.startswith("++ ") for line in body):
        return patch
    repaired = []
    for line in body:
        if line.startswith("-- ") and not line.startswith("--- "):
            repaired.append("-" + line)
        elif line.startswith("++ ") and not line.startswith("+++ "):
            repaired.append("+" + line)
        else:
            repaired.append(line)
    return "\n".join(repaired)


def normalize_unified_diff_path(path):
    path = path.strip()
    if path == "/dev/null":
        return path
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def unified_add_file_command(patch):
    if not isinstance(patch, str):
        return None
    lines = patch.splitlines()
    if len(lines) < 3:
        return None
    if lines[0].strip() != "--- /dev/null":
        return None
    if not lines[1].startswith("+++ "):
        return None
    path = normalize_unified_diff_path(lines[1][4:])
    if not path or path == "/dev/null":
        return None
    content = []
    saw_hunk = False
    for line in lines[2:]:
        if line.startswith("@@ "):
            saw_hunk = True
            continue
        if not saw_hunk:
            continue
        if line.startswith("+"):
            content.append(line[1:])
            continue
        if line.startswith("\\ No newline at end of file"):
            continue
        if line:
            return None
    if not saw_hunk:
        return None
    return conditional_apply_patch_command(path, "\n".join(content))


REPLACE_FILE_LINE = re.compile(r"^\*\*\* Replace File:\s*(?P<path>.+?)\s*$")


def repair_replace_file_header(patch):
    """Turn '*** Replace File: p' plus a full -/+ body into a delete and an add.

    Models invent this header. The body it carries dumps the old file as '-' lines and the new
    file as '+' lines, so the new content is exactly the '+' lines and the edit is recoverable.
    Anything that is not a clean full-file dump is left alone for apply_patch to reject.
    """
    if not isinstance(patch, str) or "*** Replace File:" not in patch:
        return patch
    lines = patch.splitlines()
    out, index = [], 0
    while index < len(lines):
        match = REPLACE_FILE_LINE.match(lines[index])
        if not match:
            out.append(lines[index])
            index += 1
            continue
        path = match.group("path")
        index += 1
        added, clean = [], True
        while index < len(lines) and not lines[index].startswith("*** "):
            body_line = lines[index]
            if body_line.startswith("+"):
                added.append(body_line[1:])
            elif body_line.startswith("-") or body_line.startswith("\\") or not body_line.strip():
                pass
            else:
                clean = False
            index += 1
        if not clean or not added:
            return patch
        out.append(f"*** Delete File: {path}")
        out.append(f"*** Add File: {path}")
        out.extend(f"+{line}" for line in added)
    return "\n".join(out)


def extract_patch_argument(arguments):
    if is_patch_text(arguments):
        return sanitize_patch_text(arguments)
    if isinstance(arguments, dict):
        data = arguments
    elif isinstance(arguments, str):
        try:
            data = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    else:
        return None
    for key in ("patch", "input", "content", "text"):
        value = data.get(key)
        if is_patch_text(value):
            return sanitize_patch_text(value)
    return None


def conditional_apply_patch_command(path, content):
    add_patch = add_file_patch(path, content)
    delete_patch = delete_file_patch(path)
    if add_patch is None or delete_patch is None:
        return None
    quoted_path = shlex.quote(path)
    guard = []
    if "/" not in path and path.endswith(".py"):
        package_dir = path[:-3]
        guard = [
            f"if [ ! -e {quoted_path} ] && [ -d {shlex.quote(package_dir)} ]; then",
            (
                "printf '%s\\n' "
                f"{shlex.quote(f'llama-codex proxy rejected creation of {path}: {package_dir}/ already exists; edit the package files instead.')} "
                ">&2; exit 2"
            ),
            "fi",
        ]
    # Delete and add must be separate apply_patch calls: Codex's apply_patch rejects a
    # patch carrying two operations for the same path ("multiple operations target ...").
    return "\n".join(
        [
            *guard,
            f"if [ -e {quoted_path} ]; then",
            apply_patch_command(delete_patch),
            apply_patch_command(add_patch),
            "else",
            apply_patch_command(add_patch),
            "fi",
        ]
    )
