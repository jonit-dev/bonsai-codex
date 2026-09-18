import json
import re
import shlex


def force_patch_first_command(arguments):
    try:
        data = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    if not isinstance(data, dict):
        return arguments
    cmd = data.get("cmd")
    if not isinstance(cmd, str):
        return arguments
    stripped = cmd.lstrip()
    if stripped.startswith("apply_patch") or "llama-codex apply_patch compatibility" in cmd:
        if "*** Update File:" in cmd and "*** Delete File:" not in cmd:
            message = (
                "llama-codex proxy rejected update-hunk patch during forced recovery: "
                "use full-file replacement with *** Delete File followed by *** Add File."
            )
            example = (
                "required command shape: apply_patch <<'PATCH'\\n"
                "*** Begin Patch\\n"
                "*** Delete File: path/to/file\\n"
                "*** Add File: path/to/file\\n"
                "+full corrected file line\\n"
                "*** End Patch\\n"
                "PATCH"
            )
            data["cmd"] = (
                "printf '%s\\n' "
                f"{shlex.quote(message)} "
                f"{shlex.quote(example)} "
                ">&2; exit 2"
            )
            return json.dumps(data)
        return arguments
    message = (
        "llama-codex proxy rejected diagnostic command during forced patch recovery: "
        "the first tool call must be exec_command whose cmd is an apply_patch shell heredoc that changes an implementation file."
    )
    rejected = f"rejected command: {cmd}"
    example = (
        "required command shape: apply_patch <<'PATCH'\\n"
        "*** Begin Patch\\n"
        "*** Delete File: path/to/file\\n"
        "*** Add File: path/to/file\\n"
        "+full corrected file line\\n"
        "*** End Patch\\n"
        "PATCH"
    )
    data["cmd"] = (
        "printf '%s\\n' "
        f"{shlex.quote(message)} "
        f"{shlex.quote(rejected)} "
        f"{shlex.quote(example)} "
        ">&2; exit 2"
    )
    return json.dumps(data)


def patch_first_is_satisfied(arguments):
    try:
        data = json.loads(arguments)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    cmd = data.get("cmd")
    if not isinstance(cmd, str):
        return False
    stripped = cmd.lstrip()
    return stripped.startswith("apply_patch") or "llama-codex apply_patch compatibility" in cmd


def require_update_patch_after_prior_patch(arguments):
    try:
        data = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    if not isinstance(data, dict):
        return arguments
    cmd = data.get("cmd")
    if not isinstance(cmd, str):
        return arguments
    stripped = cmd.lstrip()
    is_patch_command = stripped.startswith("apply_patch") or "llama-codex apply_patch compatibility" in cmd
    if not is_patch_command:
        return arguments
    if "*** Update File:" in cmd and "llama-codex apply_patch compatibility" not in cmd:
        return arguments
    message = (
        "llama-codex proxy rejected full rewrite after a prior patch: "
        "the workspace already has implementation changes; use a targeted *** Update File patch against the current file."
    )
    example = (
        "required command shape: apply_patch <<'PATCH'\\n"
        "*** Begin Patch\\n"
        "*** Update File: path/to/file\\n"
        "@@\\n"
        " unchanged context line\\n"
        "-old line\\n"
        "+new line\\n"
        "*** End Patch\\n"
        "PATCH"
    )
    data["cmd"] = (
        "printf '%s\\n' "
        f"{shlex.quote(message)} "
        f"{shlex.quote(example)} "
        ">&2; exit 2"
    )
    return json.dumps(data)


def force_patch_first_missing_tool_command():
    message = (
        "llama-codex proxy rejected forced patch recovery response: "
        "no tool call was made; the first action must be exec_command with cmd set to an apply_patch shell heredoc."
    )
    example = (
        "required command shape: apply_patch <<'PATCH'\\n"
        "*** Begin Patch\\n"
        "*** Delete File: path/to/file\\n"
        "*** Add File: path/to/file\\n"
        "+full corrected file line\\n"
        "*** End Patch\\n"
        "PATCH"
    )
    return (
        "printf '%s\\n' "
        f"{shlex.quote(message)} "
        f"{shlex.quote(example)} "
        ">&2; exit 2"
    )


def payload_requests_force_patch_first(value):
    if isinstance(value, dict):
        return any(payload_requests_force_patch_first(child) for child in value.values())
    if isinstance(value, list):
        return any(payload_requests_force_patch_first(child) for child in value)
    if not isinstance(value, str):
        return False
    normalized = " ".join(value.lower().split())
    return (
        "your first tool call in the next turn must be exec_command" in normalized
        or "first action must be exec_command with cmd set to an apply_patch" in normalized
        or "first tool call must be exec_command whose cmd is an apply_patch" in normalized
    )


def payload_contains_successful_patch_output(value):
    if isinstance(value, dict):
        return any(payload_contains_successful_patch_output(child) for child in value.values())
    if isinstance(value, list):
        return any(payload_contains_successful_patch_output(child) for child in value)
    if not isinstance(value, str):
        return False
    normalized = value.lower()
    return (
        "patch: completed" in normalized
        or "success. updated the following files:" in normalized
        or "successfully applied patch" in normalized
    )


def premature_prose_command(text):
    if not isinstance(text, str):
        return None
    normalized = " ".join(text.lower().split())
    if not normalized:
        return None
    intent_patterns = (
        "let me fix",
        "i will fix",
        "i'll fix",
        "let me update",
        "i will update",
        "i'll update",
        "let me patch",
        "i will patch",
        "i'll patch",
        "the problem is",
        "the issue is",
    )
    if not any(pattern in normalized for pattern in intent_patterns):
        return None
    if any(done in normalized for done in ("tests pass", "verification passed", "all tests pass", "done")):
        return None
    message = (
        "llama-codex proxy rejected premature prose-only response: call exec_command with "
        "apply_patch or a verification command instead of saying what you will do."
    )
    return f"printf '%s\\n' {shlex.quote(message)} >&2; exit 2"

FENCED_CODE_BLOCK = re.compile(r"```[A-Za-z0-9_+.-]*[ \t]*\n(?P<body>.*?)```", re.DOTALL)
READ_ONLY_COMMAND = re.compile(r"^\s*(?:cd\s+\S+\s*&&\s*)?(?:cat|sed|head|tail|wc|ls|rg|grep|find|od|file|stat)\b")


def drafted_code_block(text, min_lines=12):
    """The body of the largest fenced code block, if it is big enough to be a file draft."""
    largest = None
    for match in FENCED_CODE_BLOCK.finditer(text or ""):
        body = match.group("body")
        if body.count("\n") + 1 < min_lines:
            continue
        if largest is None or len(body) > len(largest):
            largest = body
    return largest


def read_target(cmd):
    """The path a read-only command is about, so the nag can name the file to patch."""
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return ""
    for part in reversed(parts):
        if part.startswith("-") or part in ("&&", "||", ";", "|"):
            continue
        if "/" in part or part.endswith((".py", ".ts", ".js", ".tsx", ".json", ".md", ".rs", ".go")):
            return part
    return ""


def prose_draft_command(text, target=""):
    """Direct a model that pasted an implementation into a message back to a tool call."""
    block = drafted_code_block(text)
    if block is None:
        return None
    lines = block.count("\n") + 1
    where = f" for {target}" if target else ""
    message = (
        f"llama-codex proxy: you pasted {lines} lines of code as message text, so nothing was "
        f"written. Send that code now as an apply_patch tool call{where}; the code is still in "
        "the conversation. Do not re-read the file and do not paste code in a message again."
    )
    return f"printf '%s\\n' {shlex.quote(message)} >&2; exit 2"
