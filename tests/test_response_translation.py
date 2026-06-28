import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ollama_codex_proxy as proxy


def test_translates_native_apply_patch_call_to_exec_command():
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "apply_patch",
                "arguments": json.dumps({"patch": "*** Begin Patch\n*** Add File: a.txt\n+ok\n*** End Patch"}),
            }
        ]
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    item = translated["output"][0]
    assert item["name"] == "exec_command"
    data = json.loads(item["arguments"])
    assert "llama-codex apply_patch compatibility" in data["cmd"]
    assert "apply_patch <\"$patch_file\"" in data["cmd"]
    assert "git apply --recount" in data["cmd"]
    assert "*** Add File: a.txt" in data["cmd"]


def test_malformed_native_apply_patch_call_becomes_exec_diagnostic():
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "apply_patch",
                "arguments": json.dumps({"cmd": "not a patch"}),
            }
        ]
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    item = translated["output"][0]
    assert item["name"] == "exec_command"
    data = json.loads(item["arguments"])
    assert "rejected native apply_patch call" in data["cmd"]
    assert "not a patch" in data["cmd"]


def test_translates_text_apply_patch_call_to_exec_command():
    response = {
        "id": "resp-test",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "name": "apply_patch",
                                "arguments": {
                                    "patch": "*** Begin Patch\n*** Add File: a.txt\n+ok\n*** End Patch"
                                },
                            }
                        ),
                    }
                ],
            }
        ],
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    item = translated["output"][0]
    assert item["type"] == "function_call"
    assert item["name"] == "exec_command"
    data = json.loads(item["arguments"])
    assert "*** Add File: a.txt" in data["cmd"]


def test_translates_custom_apply_patch_input_to_exec_command():
    response = {
        "output": [
            {
                "id": "cp_1",
                "type": "custom_tool_call",
                "name": "apply_patch",
                "input": "*** Begin Patch\n*** Add File: a.txt\n+ok\n*** End Patch",
            }
        ]
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    item = translated["output"][0]
    assert item["type"] == "function_call"
    assert item["name"] == "exec_command"
    assert item["call_id"] == "call_cp_1"
    data = json.loads(item["arguments"])
    assert "*** Add File: a.txt" in data["cmd"]
    assert "input" not in item


def test_translates_nested_apply_patch_object():
    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "tool_call",
                        "call": {
                            "name": "apply_patch",
                            "input": "*** Begin Patch\n*** Add File: a.txt\n+ok\n*** End Patch",
                        },
                    }
                ],
            }
        ]
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    call = translated["output"][0]["content"][0]["call"]
    assert call["name"] == "exec_command"
    assert call["type"] == "function_call"
    data = json.loads(call["arguments"])
    assert "*** Add File: a.txt" in data["cmd"]


def test_malformed_nested_apply_patch_object_becomes_exec_diagnostic():
    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "tool_call",
                        "call": {
                            "name": "apply_patch",
                            "arguments": {"cmd": "still not a patch"},
                        },
                    }
                ],
            }
        ]
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    call = translated["output"][0]["content"][0]["call"]
    assert call["name"] == "exec_command"
    data = json.loads(call["arguments"])
    assert "rejected native apply_patch call" in data["cmd"]
    assert "still not a patch" in data["cmd"]


def test_translates_premature_prose_to_exec_diagnostic():
    response = {
        "id": "resp-test",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "The problem is the ID generation. Let me fix the implementation:",
                    }
                ],
            }
        ],
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    item = translated["output"][0]
    assert item["type"] == "function_call"
    assert item["name"] == "exec_command"
    data = json.loads(item["arguments"])
    assert "rejected premature prose-only response" in data["cmd"]


def test_does_not_translate_completion_prose_to_exec_diagnostic():
    response = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Done. All tests pass."}],
            }
        ],
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    assert translated["output"][0]["type"] == "message"


def test_translates_embedded_patch_text_to_exec_command():
    response = {
        "id": "resp-test",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": (
                            "Here is the patch:\n\n"
                            "*** Begin Patch\n"
                            "*** Add File: a.txt\n"
                            "+ok\n"
                            "*** End Patch\n"
                        ),
                    }
                ],
            }
        ],
    }
    translated = proxy.translate_tool_text_response(
        response,
        {"exec_command"},
        reject_shell_writes=True,
        force_patch_first=True,
    )
    item = translated["output"][0]
    assert item["type"] == "function_call"
    assert item["name"] == "exec_command"
    data = json.loads(item["arguments"])
    assert "*** Add File: a.txt" in data["cmd"]
    assert "llama-codex apply_patch compatibility" in data["cmd"]


def test_translates_embedded_unified_diff_text_to_exec_command():
    response = {
        "id": "resp-test",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": (
                            "apply patch\n"
                            "diff --git a/bookmarks/vault.py b/bookmarks/vault.py\n"
                            "index abc..def 100644\n"
                            "--- a/bookmarks/vault.py\n"
                            "+++ b/bookmarks/vault.py\n"
                            "@@ -1,2 +1,3 @@\n"
                            " class BookmarkVault:\n"
                            "-    pass\n"
                            "+    def __init__(self, path):\n"
                            "+        self.path = path\n"
                            "\\ No newline at end of file\n"
                            "PATCH\n"
                        ),
                    }
                ],
            }
        ],
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    item = translated["output"][0]
    assert item["type"] == "function_call"
    assert item["name"] == "exec_command"
    data = json.loads(item["arguments"])
    assert "llama-codex apply_patch compatibility" in data["cmd"]
    assert "diff --git a/bookmarks/vault.py b/bookmarks/vault.py" in data["cmd"]
    assert "\nPATCH\n" not in data["cmd"].split("cat >\"$patch_file\"", 1)[-1]


if __name__ == "__main__":
    test_translates_native_apply_patch_call_to_exec_command()
    test_malformed_native_apply_patch_call_becomes_exec_diagnostic()
    test_translates_text_apply_patch_call_to_exec_command()
    test_translates_custom_apply_patch_input_to_exec_command()
    test_translates_nested_apply_patch_object()
    test_malformed_nested_apply_patch_object_becomes_exec_diagnostic()
    test_translates_premature_prose_to_exec_diagnostic()
    test_does_not_translate_completion_prose_to_exec_diagnostic()
    test_translates_embedded_patch_text_to_exec_command()
    test_translates_embedded_unified_diff_text_to_exec_command()
    print('response translation tests passed')
