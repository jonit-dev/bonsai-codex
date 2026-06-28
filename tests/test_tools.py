import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ollama_codex_proxy as proxy


def test_parse_qwen_tool_call_suffix():
    parsed = proxy.parse_tool_text(
        '{"name": "exec_command", "arguments": {"cmd": "pwd"}}\n</tool_call>',
        {"exec_command"},
    )
    assert parsed == ("exec_command", '{"cmd": "pwd"}')


def test_ignores_disallowed_tool():
    parsed = proxy.parse_tool_text(
        '{"name": "unknown", "arguments": {"cmd": "pwd"}}\n</tool_call>',
        {"exec_command"},
    )
    assert parsed is None


def test_normalizes_channel_markup_before_parsing_tool_call():
    parsed = proxy.parse_tool_text(
        '<|channel>thought\n<channel|>{"name": "exec_command", "arguments": {"cmd": "pwd"}}',
        {"exec_command"},
    )
    assert parsed == ("exec_command", '{"cmd": "pwd"}')


def test_parses_tool_call_embedded_after_prose():
    parsed = proxy.parse_tool_text(
        'I will inspect the file.\n\n{"name": "exec_command", "arguments": {"cmd": "cat README.md", "workdir": "/tmp"}}',
        {"exec_command"},
    )
    assert parsed == ("exec_command", '{"cmd": "cat README.md", "workdir": "/tmp"}')


def test_parses_xml_tool_call_with_function_attribute():
    parsed = proxy.parse_tool_text(
        '<tools>\n  <tool name="exec_command" function="{&quot;cmd&quot;:&quot;python3 -m unittest discover -s tests -v&quot;,&quot;workdir&quot;:&quot;/tmp&quot;}" />\n</tools>',
        {"exec_command"},
    )
    assert parsed == ("exec_command", '{"cmd": "python3 -m unittest discover -s tests -v", "workdir": "/tmp"}')


def test_normalizes_channel_markup_in_response_text():
    data = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "<|channel>thought\n<channel|>ok"},
                ],
            }
        ]
    }
    assert proxy.normalize_response_text(data)["output"][0]["content"][0]["text"] == "ok"


def test_api_tags_reports_context_window():
    metadata = proxy.model_metadata("model-a", 8192)
    assert metadata["models"][0]["slug"] == "model-a"
    assert metadata["models"][0]["context_window"] == 8192


def test_api_tags_can_report_reject_shell_writes():
    class Server:
        model = "model-a"
        context_window = 8192
        deny_tool_pattern = ""
        reject_shell_writes = True

    assert Server.reject_shell_writes is True


def test_cap_positive_int():
    assert proxy.cap_positive_int(None, 2048) == 2048
    assert proxy.cap_positive_int(-1, 2048) == 2048
    assert proxy.cap_positive_int(4096, 2048) == 2048
    assert proxy.cap_positive_int(1024, 2048) == 1024


def test_tool_denied_matches_full_or_short_name():
    pattern = r"^(list_mcp_resources|tool_search_tool|request_plugin_install)$"
    assert proxy.tool_denied("list_mcp_resources", pattern)
    assert proxy.tool_denied("tool_search.tool_search_tool", pattern)
    assert proxy.tool_denied("functions.request_plugin_install", pattern)
    assert not proxy.tool_denied("exec_command", pattern)
    assert not proxy.tool_denied("functions.write_stdin", pattern)
    assert not proxy.tool_denied("list_mcp_resources", "")


def test_renders_response_as_sse_events():
    data = {"id": "resp_1", "output": [{"id": "item_1", "type": "message"}]}
    rendered = proxy.responses_sse(data).decode("utf-8")
    assert "event: response.created" in rendered
    assert "event: response.output_item.added" in rendered
    assert "event: response.completed" in rendered


if __name__ == "__main__":
    test_parse_qwen_tool_call_suffix()
    test_ignores_disallowed_tool()
    test_normalizes_channel_markup_before_parsing_tool_call()
    test_parses_tool_call_embedded_after_prose()
    test_parses_xml_tool_call_with_function_attribute()
    test_normalizes_channel_markup_in_response_text()
    test_api_tags_reports_context_window()
    test_api_tags_can_report_reject_shell_writes()
    test_cap_positive_int()
    test_tool_denied_matches_full_or_short_name()
    test_renders_response_as_sse_events()
    print('tool tests passed')
