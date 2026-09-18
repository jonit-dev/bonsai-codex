import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ollama_codex_proxy as proxy


def test_detects_force_patch_first_prompt():
    assert proxy.payload_requests_force_patch_first(
        {"input": "Your first tool call in the next turn must be exec_command."}
    )
    assert not proxy.payload_requests_force_patch_first({"input": "Read files, then patch."})


def test_detects_successful_patch_output_in_payload():
    payload = {
        "input": [
            {"content": "Your first tool call in the next turn must be exec_command."},
            {"type": "function_call_output", "output": "patch: completed\n/path/to/file.py"},
        ]
    }
    assert proxy.payload_requests_force_patch_first(payload)
    assert proxy.payload_contains_successful_patch_output(payload)


def test_force_patch_first_rejects_diagnostic_exec_command():
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": "cat bookmarks/vault.py"}),
            }
        ]
    }
    translated = proxy.translate_tool_text_response(
        response,
        {"exec_command"},
        reject_shell_writes=True,
        force_patch_first=True,
    )
    data = json.loads(translated["output"][0]["arguments"])
    assert "rejected diagnostic command during forced patch recovery" in data["cmd"]
    assert "cat bookmarks/vault.py" in data["cmd"]
    assert "required command shape" in data["cmd"]


def test_force_patch_first_allows_apply_patch_command():
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps(
                    {"cmd": "apply_patch <<'PATCH'\n*** Begin Patch\n*** Add File: a.txt\n+ok\n*** End Patch\nPATCH"}
                ),
            }
        ]
    }
    translated = proxy.translate_tool_text_response(
        response,
        {"exec_command"},
        reject_shell_writes=True,
        force_patch_first=True,
    )
    data = json.loads(translated["output"][0]["arguments"])
    assert data["cmd"].startswith("apply_patch <<")


def test_force_patch_first_allows_commands_after_patch_in_same_response():
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps(
                    {"cmd": "apply_patch <<'PATCH'\n*** Begin Patch\n*** Add File: a.txt\n+ok\n*** End Patch\nPATCH"}
                ),
            },
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": "python3 -m unittest discover -s tests -v"}),
            },
        ]
    }
    translated = proxy.translate_tool_text_response(
        response,
        {"exec_command"},
        reject_shell_writes=True,
        force_patch_first=True,
    )
    first = json.loads(translated["output"][0]["arguments"])
    second = json.loads(translated["output"][1]["arguments"])
    assert first["cmd"].startswith("apply_patch <<")
    assert second["cmd"] == "python3 -m unittest discover -s tests -v"


def test_requires_update_patch_after_prior_patch_output():
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps(
                    {
                        "cmd": (
                            "apply_patch <<'PATCH'\n"
                            "*** Begin Patch\n"
                            "*** Add File: a.txt\n"
                            "+new\n"
                            "*** End Patch\n"
                            "PATCH"
                        )
                    }
                ),
            }
        ]
    }
    translated = proxy.translate_tool_text_response(
        response,
        {"exec_command"},
        reject_shell_writes=True,
        require_update_after_patch=True,
    )
    data = json.loads(translated["output"][0]["arguments"])
    assert "rejected full rewrite after a prior patch" in data["cmd"]
    assert "*** Update File" in data["cmd"]


def test_allows_update_patch_after_prior_patch_output():
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps(
                    {
                        "cmd": (
                            "apply_patch <<'PATCH'\n"
                            "*** Begin Patch\n"
                            "*** Update File: a.txt\n"
                            "@@\n"
                            " old\n"
                            "-bad\n"
                            "+good\n"
                            "*** End Patch\n"
                            "PATCH"
                        )
                    }
                ),
            }
        ]
    }
    translated = proxy.translate_tool_text_response(
        response,
        {"exec_command"},
        reject_shell_writes=True,
        require_update_after_patch=True,
    )
    data = json.loads(translated["output"][0]["arguments"])
    assert data["cmd"].startswith("apply_patch <<")
    assert "rejected full rewrite" not in data["cmd"]


def test_force_patch_first_rejects_update_hunk_patch():
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps(
                    {
                        "cmd": (
                            "apply_patch <<'PATCH'\n"
                            "*** Begin Patch\n"
                            "*** Update File: a.txt\n"
                            "@@\n"
                            "-old\n"
                            "+new\n"
                            "*** End Patch\n"
                            "PATCH"
                        )
                    }
                ),
            }
        ]
    }
    translated = proxy.translate_tool_text_response(
        response,
        {"exec_command"},
        reject_shell_writes=True,
        force_patch_first=True,
    )
    data = json.loads(translated["output"][0]["arguments"])
    assert "rejected update-hunk patch during forced recovery" in data["cmd"]
    assert "*** Delete File" in data["cmd"]


def test_force_patch_first_rejects_missing_tool_message():
    response = {
        "id": "resp-test",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": ""}],
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
    assert "no tool call was made" in data["cmd"]
    assert "apply_patch" in data["cmd"]


def test_recovery_allows_non_target_command_without_force_policy():
    original = json.dumps({"cmd": "python3 -m unittest"})
    assert proxy.force_patch_first_command(original) != original
    assert proxy.require_update_patch_after_prior_patch(original) == original


if __name__ == "__main__":
    test_detects_force_patch_first_prompt()
    test_detects_successful_patch_output_in_payload()
    test_force_patch_first_rejects_diagnostic_exec_command()
    test_force_patch_first_allows_apply_patch_command()
    test_force_patch_first_allows_commands_after_patch_in_same_response()
    test_requires_update_patch_after_prior_patch_output()
    test_allows_update_patch_after_prior_patch_output()
    test_force_patch_first_rejects_update_hunk_patch()
    test_force_patch_first_rejects_missing_tool_message()
    test_recovery_allows_non_target_command_without_force_policy()
    print('recovery tests passed')


def test_explicit_replace_is_allowed_after_a_prior_patch():
    # The anti-full-rewrite guard rejected the add half of a delete+add replace, which left the
    # file deleted with nothing written back - observed on the web-app fixture.
    replace = "apply_patch <<'PATCH'\n*** Begin Patch\n*** Delete File: app.py\n*** End Patch\nPATCH"
    out = proxy.require_update_patch_after_prior_patch(json.dumps({"cmd": replace}))
    assert "proxy rejected" not in out
    assert "*** Delete File: app.py" in json.loads(out)["cmd"]

    bare_add = "apply_patch <<'PATCH'\n*** Begin Patch\n*** Add File: app.py\n+x\n*** End Patch\nPATCH"
    out = proxy.require_update_patch_after_prior_patch(json.dumps({"cmd": bare_add}))
    assert "proxy rejected full rewrite" in json.loads(out)["cmd"]
