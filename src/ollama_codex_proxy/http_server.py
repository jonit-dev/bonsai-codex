import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .metadata import cap_positive_int, model_metadata
from .recovery import payload_contains_successful_patch_output, payload_requests_force_patch_first
from .response_translation import translate_tool_text_response
from .streaming import responses_sse
from .tools import tool_denied, tool_name


def read_json(handler):
    length = int(handler.headers.get("content-length", "0"))
    body = handler.rfile.read(length) if length else b"{}"
    if not body:
        return {}
    return json.loads(body)


PROMPT_BUDGET_FRACTION = float(os.environ.get("LLAMA_CODEX_PROMPT_BUDGET", "0.75"))
ELIDED_FLOOR = 200


def budget_prompt(payload, items, context_window=None):
    """Keep a long conversation inside the window by shrinking its oldest tool output.

    A long run grows past the server's context and llama-server answers 400
    "exceeds the available context size", which ends the run: measured on tasks/web-app, the
    window reached 24700 tokens against a 24576 limit after a large write. The newest turns
    stay intact; the oldest tool results keep their first lines and say what was dropped.
    """
    if context_window is None:
        context_window = int(os.environ.get("LLAMA_CODEX_CONTEXT_WINDOW", "32768"))
    budget_chars = int(context_window * PROMPT_BUDGET_FRACTION * 4)
    total = len(json.dumps(items))
    if total <= budget_chars:
        return payload
    for item in items:
        if total <= budget_chars:
            break
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            continue
        output = item.get("output")
        if not isinstance(output, str) or len(output) <= ELIDED_FLOOR:
            continue
        dropped = len(output) - ELIDED_FLOOR
        item["output"] = (
            f"{output[:ELIDED_FLOOR]}\n"
            f"[llama-codex proxy: {dropped} older characters elided to keep the request "
            "inside the context window]"
        )
        total -= dropped
    return payload


def trim_tool_outputs(payload, limit=None):
    """Keep command output from eating the context window.

    Codex appends every command's output to the transcript verbatim, so one repo-wide
    `rg` or `cat` of a 900-line spec costs more than the task itself: measured on a real
    codebase, a single spec-writing task grew 6.9k -> 90k input tokens in six turns. Keep
    the head of each output and say what was elided, so the model re-reads a narrower
    range instead of the harness silently losing the tail.
    """
    if limit is None:
        limit = int(os.environ.get("LLAMA_CODEX_TOOL_OUTPUT_CHARS", "3000"))
    items = payload.get("input")
    if not isinstance(items, list):
        return payload
    payload = budget_prompt(payload, items)
    if limit <= 0:
        return payload
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            continue
        output = item.get("output")
        if isinstance(output, str) and len(output) > limit:
            elided = len(output) - limit
            item["output"] = (
                f"{output[:limit]}\n[llama-codex proxy: {elided} characters elided; "
                "read a narrower range (sed -n 'a,bp', rg -m 20) if you need more]"
            )
        elif isinstance(output, list):
            for part in output:
                text = part.get("text") if isinstance(part, dict) else None
                if isinstance(text, str) and len(text) > limit:
                    part["text"] = (
                        f"{text[:limit]}\n[llama-codex proxy: {len(text) - limit} characters elided]"
                    )
    return payload


def fold_instructions_into_leading_message(payload):
    """Keep exactly one system message, at position 0, for strict chat templates.

    llama.cpp's Responses -> chat conversion turns both `instructions` and a leading
    developer/system input message into system messages, and the Qwen3.8 template then
    rejects the request with "System message must be at the beginning". Folding the
    instructions into that leading message keeps the same text at the same priority
    without producing a second system message.
    """
    instructions = payload.get("instructions")
    items = payload.get("input")
    if not isinstance(instructions, str) or not instructions.strip():
        return payload
    if not isinstance(items, list) or not items:
        return payload
    first = items[0]
    if not isinstance(first, dict) or first.get("type") != "message":
        return payload
    if first.get("role") not in ("developer", "system"):
        return payload
    content = first.get("content")
    if isinstance(content, str):
        first["content"] = instructions + "\n\n" + content
    elif isinstance(content, list):
        first["content"] = [{"type": "input_text", "text": instructions}] + content
    else:
        return payload
    payload.pop("instructions", None)
    return payload


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def send_bytes(self, status, data, content_type="application/json"):
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, data):
        self.send_bytes(status, json.dumps(data).encode("utf-8"))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/v1/models", "/models"):
            self.send_json(200, model_metadata(self.server.model, self.server.context_window))
            return
        if path == "/api/tags":
            self.send_json(
                200,
                {
                    "models": [
                        {
                            "name": self.server.model,
                            "model": self.server.model,
                            "context_window": self.server.context_window,
                            "max_output_tokens": self.server.max_output_tokens,
                            "deny_tool_pattern": self.server.deny_tool_pattern,
                            "reject_shell_writes": self.server.reject_shell_writes,
                        }
                    ]
                },
            )
            return
        self.forward()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/v1/responses":
            payload = read_json(self)
            payload["model"] = self.server.model
            if self.server.max_output_tokens > 0:
                payload["max_output_tokens"] = cap_positive_int(
                    payload.get("max_output_tokens"),
                    self.server.max_output_tokens,
                )
                payload["max_tokens"] = cap_positive_int(
                    payload.get("max_tokens"),
                    self.server.max_output_tokens,
                )
                options = payload.get("options")
                if not isinstance(options, dict):
                    options = {}
                options["num_predict"] = cap_positive_int(
                    options.get("num_predict"),
                    self.server.max_output_tokens,
                )
                payload["options"] = options
            stream_response = bool(payload.get("stream"))
            payload = fold_instructions_into_leading_message(payload)
            payload = trim_tool_outputs(payload)
            force_patch_first = (
                payload_requests_force_patch_first(payload)
                and not payload_contains_successful_patch_output(payload)
            )
            require_update_after_patch = payload_contains_successful_patch_output(payload)
            payload["stream"] = False
            tools = payload.get("tools")
            allowed_tool_names = set()
            if isinstance(tools, list):
                before = len(tools)
                payload["tools"] = [
                    tool for tool in tools
                    if tool.get("type") == "function" and not tool_denied(tool_name(tool), self.server.deny_tool_pattern)
                ]
                allowed_tool_names = {name for name in (tool_name(tool) for tool in payload["tools"]) if name}
                if allowed_tool_names:
                    self.log_message("allowed function tools: %s", ",".join(sorted(allowed_tool_names)))
                removed_unsupported = sum(1 for tool in tools if tool.get("type") != "function")
                removed_denied = before - removed_unsupported - len(payload["tools"])
                if removed_unsupported:
                    self.log_message("removed %d unsupported non-function tool(s)", removed_unsupported)
                if removed_denied:
                    self.log_message("removed %d denied function tool(s)", removed_denied)
            self.forward(
                payload,
                allowed_tool_names=allowed_tool_names,
                stream_response=stream_response,
                force_patch_first=force_patch_first,
                require_update_after_patch=require_update_after_patch,
            )
            return
        self.forward(read_json(self))

    def forward(
        self,
        payload=None,
        allowed_tool_names=None,
        stream_response=False,
        force_patch_first=False,
        require_update_after_patch=False,
    ):
        url = self.server.backend.rstrip("/") + self.path
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["content-type"] = "application/json"
        req = Request(url, data=data, headers=headers, method=self.command)
        try:
            with urlopen(req, timeout=None) as resp:
                body = resp.read()
                content_type = resp.headers.get("content-type", "application/json")
                if allowed_tool_names and "application/json" in content_type:
                    try:
                        body = json.dumps(
                            translate_tool_text_response(
                                json.loads(body),
                                allowed_tool_names,
                                reject_shell_writes=self.server.reject_shell_writes,
                                force_patch_first=force_patch_first,
                                require_update_after_patch=require_update_after_patch,
                            )
                        ).encode("utf-8")
                    except json.JSONDecodeError:
                        pass
                if stream_response and "application/json" in content_type:
                    try:
                        body = responses_sse(json.loads(body))
                        content_type = "text/event-stream"
                    except json.JSONDecodeError:
                        pass
                self.send_bytes(resp.status, body, content_type)
        except HTTPError as err:
            body = err.read()
            self.log_message("backend HTTP %d: %s", err.code, body[:1200].decode("utf-8", "replace"))
            self.send_bytes(err.code, body, err.headers.get("content-type", "application/json"))
        except URLError as err:
            self.send_json(502, {"error": {"message": str(err), "type": "proxy_error"}})
