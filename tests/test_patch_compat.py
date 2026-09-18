import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ollama_codex_proxy as proxy


def test_translates_unified_diff_apply_patch_to_compat_command():
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "apply_patch",
                "arguments": json.dumps({"patch": "--- /dev/null\n+++ b/a.txt\n@@ -0,0 +1 @@\n+ok\n"}),
            }
        ]
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    item = translated["output"][0]
    assert item["name"] == "exec_command"
    data = json.loads(item["arguments"])
    assert "if [ -e a.txt ]; then" in data["cmd"]
    assert "*** Delete File: a.txt" in data["cmd"]
    assert "*** Add File: a.txt" in data["cmd"]
    assert "+ok" in data["cmd"]


def test_repairs_shorthand_apply_patch_header():
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "apply_patch",
                "arguments": json.dumps(
                    {"patch": "*** Begin Patch\n*** notes/__init__.py\n+from .store import NoteStore\n*** End Patch"}
                ),
            }
        ]
    }
    translated = proxy.translate_tool_text_response(response, {"exec_command"}, reject_shell_writes=True)
    data = json.loads(translated["output"][0]["arguments"])
    assert "*** Delete File: notes/__init__.py" in data["cmd"]
    assert "*** Add File: notes/__init__.py" in data["cmd"]
    assert "+from .store import NoteStore" in data["cmd"]
    assert "llama-codex apply_patch compatibility" not in data["cmd"]


def test_shorthand_patch_rejects_top_level_module_shadowing_package():
    command = proxy.shorthand_patch_command("*** Begin Patch\n*** notes.py\n+VALUE = 1\n*** End Patch")
    assert command is not None
    assert "[ -d notes ]" in command
    assert "edit the package files instead" in command


def test_repairs_unprefixed_add_file_lines():
    command = proxy.apply_patch_compat_command(
        "*** Begin Patch\n"
        "*** Delete File: a.py\n"
        "*** Add File: a.py\n"
        "+def one():\n"
        "    return 1\n"
        "*** End Patch"
    )
    assert "+def one():" in command
    assert "+    return 1" in command


def test_unified_add_file_patch_becomes_conditional_apply_patch():
    command = proxy.apply_patch_compat_command(
        "--- /dev/null\n"
        "+++ b/bookmarks/vault.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+import json\n"
        "+\n"
        "+print('ok')\n"
        "\\ No newline at end of file"
    )
    assert "llama-codex apply_patch compatibility" not in command
    assert "if [ -e bookmarks/vault.py ]; then" in command
    assert "*** Delete File: bookmarks/vault.py" in command
    assert "*** Add File: bookmarks/vault.py" in command
    assert "+import json" in command
    assert "+print('ok')" in command


def test_repairs_malformed_wrapped_unified_diff_header():
    command = proxy.apply_patch_compat_command(
        "*** Begin Patch\n"
        "-- a.py\n"
        "++ a.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "*** End Patch"
    )
    assert "--- a.py" in command
    assert "+++ a.py" in command
    assert "-- a.py" not in command.splitlines()


if __name__ == "__main__":
    test_translates_unified_diff_apply_patch_to_compat_command()
    test_repairs_shorthand_apply_patch_header()
    test_shorthand_patch_rejects_top_level_module_shadowing_package()
    test_repairs_unprefixed_add_file_lines()
    test_unified_add_file_patch_becomes_conditional_apply_patch()
    test_repairs_malformed_wrapped_unified_diff_header()
    print('patch compatibility tests passed')


def test_invented_replace_file_header_becomes_a_delete_and_add():
    # The model invented '*** Replace File: p' and dumped the whole old/new body under it.
    # apply_patch rejected the header; the '+' lines are the new file, so the edit survives.
    cmd = (
        "apply_patch <<'P'\n*** Begin Patch\n*** Replace File: app.py\n"
        "-old line\n-another old\n+new line\n+second new\n*** End Patch\nP"
    )
    out = json.loads(proxy.apply_exec_guard("exec_command", json.dumps({"cmd": cmd}), True))["cmd"]
    assert "*** Delete File: app.py" in out
    assert "*** Add File: app.py" in out
    assert "+new line" in out and "+second new" in out
    assert "-old line" not in out
    assert out.count("apply_patch <<") == 2


def test_replace_header_with_added_context_is_left_alone():
    cmd = (
        "apply_patch <<'P'\n*** Begin Patch\n*** Replace File: app.py\n"
        " context line\n+new line\n*** End Patch\nP"
    )
    out = json.loads(proxy.apply_exec_guard("exec_command", json.dumps({"cmd": cmd}), True))["cmd"]
    assert "*** Add File: app.py" not in out
