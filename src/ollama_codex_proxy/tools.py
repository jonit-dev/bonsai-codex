import html
import json
import re

from .text import normalize_model_text


def parse_tool_text(text, allowed_names):
    text = normalize_model_text(text)
    candidates = []
    xml_tool_calls = []
    for match in re.finditer(
        r"<tool\s+[^>]*name=(['\"])(?P<name>.*?)\1[^>]*function=(['\"])(?P<function>.*?)\3\s*/?>",
        text,
        re.DOTALL,
    ):
        xml_tool_calls.append((html.unescape(match.group("name")), html.unescape(match.group("function"))))
    for match in re.finditer(r"<(?:tools?|tool_call)>\s*(\{.*?\})\s*</(?:tools?|tool_call)>", text, re.DOTALL):
        candidates.append(match.group(1))
    if "</tool_call>" in text:
        before_tool_end = text.split("</tool_call>", 1)[0]
        json_start = before_tool_end.find("{")
        if json_start >= 0:
            try:
                data, _ = json.JSONDecoder().raw_decode(before_tool_end[json_start:])
                candidates.append(json.dumps(data))
            except json.JSONDecodeError:
                pass
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        candidates.append(match.group(1))
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            data, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "name" in data and "arguments" in data:
            candidates.append(json.dumps(data))

    for name, function_payload in xml_tool_calls:
        if name not in allowed_names:
            continue
        try:
            arguments = json.loads(function_payload)
        except json.JSONDecodeError:
            continue
        if isinstance(arguments, dict):
            return name, json.dumps(arguments)

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        name = data.get("name")
        arguments = data.get("arguments")
        if not name or name not in allowed_names or not isinstance(arguments, dict):
            continue
        return name, json.dumps(arguments)
    return None


def tool_name(tool):
    if not isinstance(tool, dict):
        return None
    if tool.get("name"):
        return tool.get("name")
    function = tool.get("function")
    if isinstance(function, dict):
        return function.get("name")
    return None


def tool_denied(name, pattern):
    if not name or not pattern:
        return False
    short_name = name.rsplit(".", 1)[-1]
    return bool(re.search(pattern, name) or re.search(pattern, short_name))
