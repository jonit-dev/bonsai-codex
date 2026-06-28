import json
import re
import shlex

from .patches import (
    apply_patch_compat_command,
    extract_patch_argument,
    sanitize_patch_text,
)
from .recovery import (
    force_patch_first_command,
    force_patch_first_missing_tool_command,
    patch_first_is_satisfied,
    premature_prose_command,
    require_update_patch_after_prior_patch,
)
from .shell_guard import apply_exec_guard
from .text import normalize_response_text
from .tools import parse_tool_text


def extract_embedded_apply_patch(text):
    if not isinstance(text, str):
        return None
    match = re.search(r"\*\*\* Begin Patch\b.*?\n\*\*\* End Patch\b", text, re.DOTALL)
    if not match:
        return None
    return match.group(0).strip()


def extract_embedded_unified_diff(text):
    if not isinstance(text, str):
        return None
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("diff --git ") or line.startswith("--- "):
            start = index
            break
    if start is None:
        return None
    diff_lines = []
    saw_header = False
    saw_hunk = False
    for line in lines[start:]:
        if diff_lines and re.fullmatch(r"PATCH(?:_[A-Za-z0-9]+)?", line.strip()):
            break
        if line.startswith("diff --git "):
            if diff_lines and saw_hunk:
                break
            diff_lines.append(line)
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            saw_header = True
            diff_lines.append(line)
            continue
        if line.startswith("@@ "):
            saw_hunk = True
            diff_lines.append(line)
            continue
        if saw_header and (
            line.startswith(("+", "-", " "))
            or line.startswith("\\ No newline at end of file")
            or line.startswith(("index ", "new file mode ", "deleted file mode "))
        ):
            diff_lines.append(line)
            continue
        if saw_hunk:
            break
        if diff_lines:
            diff_lines.append(line)
    if not saw_header or not saw_hunk:
        return None
    return sanitize_patch_text("\n".join(diff_lines))


def missing_apply_patch_payload_command(original=None):
    message = (
        "llama-codex proxy rejected native apply_patch call: "
        "call exec_command with an apply_patch heredoc, or include a patch payload beginning with *** Begin Patch."
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
    parts = [
        "printf '%s\\n'",
        shlex.quote(message),
        shlex.quote(example),
    ]
    if original is not None:
        parts.append(shlex.quote(f"rejected apply_patch payload: {original}"))
    parts.append(">&2; exit 2")
    return " ".join(parts)


def translate_apply_patch_call(name, arguments, allowed_names):
    if not name or name.rsplit(".", 1)[-1] != "apply_patch":
        return name, arguments
    exec_name = next((candidate for candidate in allowed_names if candidate.rsplit(".", 1)[-1] == "exec_command"), None)
    if not exec_name:
        return name, arguments
    patch = extract_patch_argument(arguments)
    if patch is None:
        return exec_name, json.dumps({"cmd": missing_apply_patch_payload_command(arguments)})
    return exec_name, json.dumps({"cmd": apply_patch_compat_command(patch)})


def translate_apply_patch_item(item, allowed_names):
    name = item.get("name")
    if not name or name.rsplit(".", 1)[-1] != "apply_patch":
        return False
    patch = extract_patch_argument(item.get("arguments"))
    if patch is None:
        patch = extract_patch_argument(item.get("input"))
    exec_name = next((candidate for candidate in allowed_names if candidate.rsplit(".", 1)[-1] == "exec_command"), None)
    if not exec_name:
        return False
    item["type"] = "function_call"
    item["name"] = exec_name
    if patch is None:
        original = item.get("arguments") if "arguments" in item else item.get("input")
        item["arguments"] = json.dumps({"cmd": missing_apply_patch_payload_command(original)})
    else:
        item["arguments"] = json.dumps({"cmd": apply_patch_compat_command(patch)})
    item["status"] = item.get("status", "completed")
    item["call_id"] = item.get("call_id") or "call_" + item.get("id", "ollama_apply_patch").replace("-", "_")
    item.pop("input", None)
    return True


def translate_apply_patch_objects(value, allowed_names):
    if isinstance(value, list):
        for item in value:
            translate_apply_patch_objects(item, allowed_names)
        return value
    if not isinstance(value, dict):
        return value

    name = value.get("name")
    if isinstance(name, str) and name.rsplit(".", 1)[-1] == "apply_patch":
        translate_apply_patch_item(value, allowed_names)

    for child in list(value.values()):
        translate_apply_patch_objects(child, allowed_names)
    return value


def translate_tool_text_response(
    data,
    allowed_names,
    reject_shell_writes=False,
    force_patch_first=False,
    require_update_after_patch=False,
):
    data = normalize_response_text(data)
    translate_apply_patch_objects(data, allowed_names)
    output = data.get("output")
    if not isinstance(output, list):
        return data
    patch_first_satisfied = False
    for index, item in enumerate(output):
        if translate_apply_patch_item(item, allowed_names):
            item["arguments"] = apply_exec_guard(item.get("name"), item["arguments"], reject_shell_writes)
            if force_patch_first and not patch_first_satisfied:
                item["arguments"] = force_patch_first_command(item["arguments"])
                patch_first_satisfied = patch_first_is_satisfied(item["arguments"])
            if require_update_after_patch:
                item["arguments"] = require_update_patch_after_prior_patch(item["arguments"])
            continue
        if item.get("type") == "function_call":
            name = item.get("name")
            arguments = item.get("arguments")
            if isinstance(arguments, str):
                name, arguments = translate_apply_patch_call(name, arguments, allowed_names)
                item["name"] = name
                item["arguments"] = apply_exec_guard(name, arguments, reject_shell_writes)
                if force_patch_first and not patch_first_satisfied:
                    item["arguments"] = force_patch_first_command(item["arguments"])
                    patch_first_satisfied = patch_first_is_satisfied(item["arguments"])
                if require_update_after_patch:
                    item["arguments"] = require_update_patch_after_prior_patch(item["arguments"])
            continue
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        text = "".join(part.get("text", "") for part in content if part.get("type") == "output_text")
        parsed = parse_tool_text(text, set(allowed_names) | {"apply_patch"})
        if not parsed:
            exec_name = next((candidate for candidate in allowed_names if candidate.rsplit(".", 1)[-1] == "exec_command"), None)
            embedded_patch = extract_embedded_apply_patch(text)
            if embedded_patch is None:
                embedded_patch = extract_embedded_unified_diff(text)
            if exec_name and embedded_patch:
                call_id = "call_" + item.get("id", data.get("id", "ollama")).replace("-", "_")
                cmd = apply_patch_compat_command(embedded_patch)
                if force_patch_first and "*** Update File:" in embedded_patch and "*** Delete File:" not in embedded_patch:
                    cmd = force_patch_first_command(json.dumps({"cmd": cmd}))
                    try:
                        cmd = json.loads(cmd)["cmd"]
                    except (TypeError, json.JSONDecodeError, KeyError):
                        pass
                if require_update_after_patch:
                    guarded = require_update_patch_after_prior_patch(json.dumps({"cmd": cmd}))
                    try:
                        cmd = json.loads(guarded)["cmd"]
                    except (TypeError, json.JSONDecodeError, KeyError):
                        pass
                output[index] = {
                    "id": "fc_" + call_id.removeprefix("call_"),
                    "type": "function_call",
                    "status": "completed",
                    "call_id": call_id,
                    "name": exec_name,
                    "arguments": json.dumps({"cmd": cmd}),
                }
                return data
            if exec_name and force_patch_first:
                call_id = "call_" + item.get("id", data.get("id", "ollama")).replace("-", "_")
                output[index] = {
                    "id": "fc_" + call_id.removeprefix("call_"),
                    "type": "function_call",
                    "status": "completed",
                    "call_id": call_id,
                    "name": exec_name,
                    "arguments": json.dumps({"cmd": force_patch_first_missing_tool_command()}),
                }
                return data
            premature_command = premature_prose_command(text)
            if exec_name and premature_command:
                call_id = "call_" + item.get("id", data.get("id", "ollama")).replace("-", "_")
                output[index] = {
                    "id": "fc_" + call_id.removeprefix("call_"),
                    "type": "function_call",
                    "status": "completed",
                    "call_id": call_id,
                    "name": exec_name,
                    "arguments": json.dumps({"cmd": premature_command}),
                }
                return data
            continue
        name, arguments = parsed
        name, arguments = translate_apply_patch_call(name, arguments, allowed_names)
        arguments = apply_exec_guard(name, arguments, reject_shell_writes)
        if force_patch_first and not patch_first_satisfied:
            arguments = force_patch_first_command(arguments)
            patch_first_satisfied = patch_first_is_satisfied(arguments)
        if require_update_after_patch:
            arguments = require_update_patch_after_prior_patch(arguments)
        call_id = "call_" + item.get("id", data.get("id", "ollama")).replace("-", "_")
        output[index] = {
            "id": "fc_" + call_id.removeprefix("call_"),
            "type": "function_call",
            "status": "completed",
            "call_id": call_id,
            "name": name,
            "arguments": arguments,
        }
        return data
    return data
