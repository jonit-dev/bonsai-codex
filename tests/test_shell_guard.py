import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ollama_codex_proxy as proxy


def test_rewrites_touch_to_apply_patch():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "touch tasklib/__init__.py tasklib/models.py"}),
        True,
    )
    data = json.loads(arguments)
    assert "apply_patch <<'PATCH_LLAMACODEX'" in data["cmd"]
    assert "*** Add File: tasklib/__init__.py" in data["cmd"]
    assert "*** Add File: tasklib/models.py" in data["cmd"]
    assert "touch" not in data["cmd"]


def test_rewritten_touch_rejects_top_level_module_shadowing_package():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "touch notes.py"}),
        True,
    )
    data = json.loads(arguments)
    assert "[ -d notes ]" in data["cmd"]
    assert "edit the package files instead" in data["cmd"]
    assert "*** Add File: notes.py" in data["cmd"]


def test_rewrites_cat_heredoc_to_apply_patch():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "cat > tasklib/models.py << 'EOF'\nclass Task:\n    pass\nEOF"}),
        True,
    )
    data = json.loads(arguments)
    assert "apply_patch <<'PATCH_LLAMACODEX'" in data["cmd"]
    assert "*** Delete File: tasklib/models.py" in data["cmd"]
    assert "*** Add File: tasklib/models.py" in data["cmd"]
    assert "+class Task:" in data["cmd"]
    assert "cat >" not in data["cmd"]


def test_rewrites_cat_heredoc_with_redirect_after_delimiter():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "cat <<'EOF' > ledger/store.py\nclass LedgerStore:\n    pass\nEOF"}),
        True,
    )
    data = json.loads(arguments)
    assert "*** Add File: ledger/store.py" in data["cmd"]
    assert "+class LedgerStore:" in data["cmd"]
    assert "cat <<" not in data["cmd"]


def test_rejected_shell_write_reports_original_command():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "printf 'x' > ledger/store.py"}),
        True,
    )
    data = json.loads(arguments)
    assert "proxy rejected this edit command" in data["cmd"]
    assert "printf" in data["cmd"]
    assert "ledger/store.py" in data["cmd"]


def test_rewrites_echo_redirect_to_apply_patch():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps(
            {
                "cmd": "echo 'from .store import LedgerStore\nfrom .server import create_app' > ledger/__init__.py"
            }
        ),
        True,
    )
    data = json.loads(arguments)
    assert "*** Add File: ledger/__init__.py" in data["cmd"]
    assert "+from .store import LedgerStore" in data["cmd"]
    assert "+from .server import create_app" in data["cmd"]
    assert "echo" not in data["cmd"]


def test_rejects_rm_source_edit_command():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "rm bookmarks/vault.py"}),
        True,
    )
    data = json.loads(arguments)
    assert "proxy rejected this edit command" in data["cmd"]
    assert "do not use touch, rm" in data["cmd"]
    assert "rm bookmarks/vault.py" in data["cmd"]


def test_unwraps_nested_exec_command_shell_text():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": 'exec_command("exec_command", {"cmd": "ls -la", "workdir": "/tmp"})'}),
        True,
    )
    data = json.loads(arguments)
    assert data["cmd"] == "ls -la"
    assert data["workdir"] == "/tmp"


def test_unwrapped_nested_exec_still_applies_shell_write_guard():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": 'exec_command("exec_command", {"cmd": "echo ok > a.txt"})'}),
        True,
    )
    data = json.loads(arguments)
    assert "*** Add File: a.txt" in data["cmd"]
    assert "+ok" in data["cmd"]


def test_rewrites_apply_patch_file_patch_flags_when_payload_is_real_patch():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps(
            {
                "cmd": "apply_patch --file ignored.js --patch '*** Begin Patch\n*** Update File: src/planner.js\n@@\n-old\n+new\n*** End Patch'"
            }
        ),
        True,
    )
    data = json.loads(arguments)
    assert "llama-codex apply_patch compatibility" in data["cmd"]
    assert "*** Update File: src/planner.js" in data["cmd"]
    assert "--file" not in data["cmd"]


def test_rejects_apply_patch_file_patch_flags_with_non_patch_payload():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "apply_patch --file src/planner.js --patch 'const id = `a${newTrip.activities.length + 1}`;'"}),
        True,
    )
    data = json.loads(arguments)
    assert "rejected malformed apply_patch command" in data["cmd"]
    assert "does not accept --file or --patch flags" in data["cmd"]
    assert "src/planner.js" in data["cmd"]


def test_rejects_malformed_apply_patch_shell_command_with_guidance():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "apply_patch --file src/planner.js"}),
        True,
    )
    data = json.loads(arguments)
    assert "rejected malformed apply_patch command" in data["cmd"]
    assert "does not accept --file or --patch flags" in data["cmd"]
    assert "src/planner.js" in data["cmd"]


def test_repairs_apply_patch_heredoc_closed_before_end_patch():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps(
            {
                "cmd": (
                    "apply_patch <<'PATCH'\n"
                    "*** Begin Patch\n"
                    "*** Add File: a.py\n"
                    "+ok = True\n"
                    "PATCH\n"
                    "*** End Patch\n"
                    "PATCH"
                )
            }
        ),
        True,
    )
    data = json.loads(arguments)
    assert data["cmd"].startswith("apply_patch <<")
    assert "*** End Patch\n" in data["cmd"]
    assert "PATCH\n*** End Patch" not in data["cmd"]


def test_rewrites_wrapped_unified_diff_heredoc_to_compat_command():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps(
            {
                "cmd": (
                    "apply_patch <<'PATCH'\n"
                    "*** Begin Patch\n"
                    "--- a.py\n"
                    "+++ a.py\n"
                    "@@ -1 +1 @@\n"
                    "-old\n"
                    "+new\n"
                    "*** End Patch\n"
                    "PATCH"
                )
            }
        ),
        True,
    )
    data = json.loads(arguments)
    assert "llama-codex apply_patch compatibility" in data["cmd"]
    assert "git apply --recount" in data["cmd"]
    assert "git apply -p0 --recount" in data["cmd"]
    assert "patch --batch" not in data["cmd"]
    assert "PY_LLAMACODEX_DIFF" in data["cmd"]
    assert "rest.startswith(prefix)" in data["cmd"]
    assert "grep -q '^\\*\\*\\* Begin Patch'" in data["cmd"]
    assert "grep -qi '^Invalid patch'" in data["cmd"]
    assert "*** Begin Patch" not in data["cmd"].split("cat >\"$patch_file\"", 1)[-1]


def test_repairs_complete_apply_patch_heredoc_missing_add_prefixes():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps(
            {
                "cmd": (
                    "apply_patch <<'PATCH'\n"
                    "*** Begin Patch\n"
                    "*** Delete File: a.py\n"
                    "*** Add File: a.py\n"
                    "import json\n"
                    "\n"
                    "print('ok')\n"
                    "*** End Patch\n"
                    "PATCH"
                )
            }
        ),
        True,
    )
    data = json.loads(arguments)
    assert "+import json" in data["cmd"]
    assert "+print('ok')" in data["cmd"]
    assert "\nimport json\n" not in data["cmd"]


def test_repairs_apply_patch_heredoc_missing_end_marker():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps(
            {
                "cmd": (
                    "apply_patch <<'PATCH'\n"
                    "*** Begin Patch\n"
                    "*** Delete File: a.py\n"
                    "*** Add File: a.py\n"
                    "import json\n"
                    "print('ok')\n"
                    "PATCH\n"
                    "PATCH"
                )
            }
        ),
        True,
    )
    data = json.loads(arguments)
    assert "+import json" in data["cmd"]
    assert "+print('ok')" in data["cmd"]
    assert "*** End Patch\n" in data["cmd"]
    assert data["cmd"].count("\nPATCH") == 1


def test_non_target_exec_command_passes_through():
    original = json.dumps({"cmd": "python3 -m unittest"})
    assert proxy.apply_exec_guard("exec_command", original, True) == original





def test_rewrites_cat_heredoc_with_trailing_verification_command():
    # The shape that stalled the Bonsai run: the model writes the file and chains its
    # own `cat` to check the result. Anchoring the heredoc at end-of-string rejected
    # the whole command, including a complete, correct 1000-token file body.
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "cat > api.py <<'PATCH'\nimport json\nPATCH\ncat api.py"}),
        True,
    )
    data = json.loads(arguments)
    assert "*** Add File: api.py" in data["cmd"]
    assert "+import json" in data["cmd"]
    assert "cat >" not in data["cmd"]
    assert data["cmd"].endswith("cat api.py")


def test_rejects_cat_heredoc_with_trailing_write_command():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "cat > api.py <<'PATCH'\nimport json\nPATCH\nrm -rf src"}),
        True,
    )
    data = json.loads(arguments)
    assert "proxy rejected this edit command" in data["cmd"]
    assert "*** Add File: api.py" not in data["cmd"]


def test_keeps_trailing_command_after_repaired_apply_patch_heredoc():
    patch = "*** Begin Patch\n*** Add File: api.py\n+import json\n*** End Patch"
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": f"apply_patch <<'PATCH'\n{patch}\nPATCH\npython3 -m unittest discover -s tests"}),
        True,
    )
    data = json.loads(arguments)
    assert "*** Add File: api.py" in data["cmd"]
    assert data["cmd"].endswith("python3 -m unittest discover -s tests")


if __name__ == "__main__":
    for name, check in sorted(globals().items()):
        if name.startswith("test_") and callable(check):
            check()
    print('shell guard tests passed')


def test_allows_python_read_but_rejects_python_write():
    read_args = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "python3 -c \"print(repr(open('api.py').read()))\""}),
        True,
    )
    assert json.loads(read_args)["cmd"].startswith("python3 -c")

    write_args = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "python3 -c \"open('api.py','w').write('x')\""}),
        True,
    )
    assert "proxy rejected this edit command" in json.loads(write_args)["cmd"]


def test_apply_patch_after_cd_prefix_is_not_scanned_as_shell():
    # An HTML patch body contains lines like ">Notes", which the shell-write scan reads as
    # a redirect when the command is not recognized as apply_patch. With a `cd x &&`
    # prefix the command was rejected and the model's edit was lost.
    patch = "*** Begin Patch\n*** Add File: app.py\n+<!DOCTYPE html>\n+<html>\n*** End Patch"
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": f"cd /tmp/demo && apply_patch <<'PATCH'\n{patch}\nPATCH"}),
        True,
    )
    data = json.loads(arguments)
    assert "proxy rejected" not in data["cmd"]
    assert "cd /tmp/demo &&" in data["cmd"]
    assert "+<!DOCTYPE html>" in data["cmd"]


def test_cd_prefix_patch_is_repaired_and_prefix_kept():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "cd /tmp/demo && apply_patch <<'PATCH'\n*** Add File: app.py\n+import json\n*** End Patch\nPATCH"}),
        True,
    )
    data = json.loads(arguments)
    assert data["cmd"].startswith("cd /tmp/demo && apply_patch <<'")
    assert "*** Begin Patch" in data["cmd"]


def test_rewrites_cat_heredoc_after_a_leading_cd_line():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "cd /tmp/demo\ncat > app.py <<'PYEOF'\nimport json\nPYEOF"}),
        True,
    )
    data = json.loads(arguments)
    assert "proxy rejected" not in data["cmd"]
    assert data["cmd"].startswith("cd /tmp/demo\n")
    assert "*** Add File: app.py" in data["cmd"]


def test_forbidden_prefix_still_rejects_the_rewritten_heredoc():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "rm -rf src && cat > app.py <<'PYEOF'\nimport json\nPYEOF"}),
        True,
    )
    data = json.loads(arguments)
    assert "proxy rejected this edit command" in data["cmd"]


def test_allows_reads_that_redirect_stderr_to_devnull():
    for cmd in (
        'cat vitest.config.ts 2>/dev/null || ls | grep -i vitest',
        'rg -n "environment" vitest.config.* 2>/dev/null; head -80 specs/net.spec.ts',
        'cat packages/core/package.json >/dev/null',
    ):
        data = json.loads(proxy.apply_exec_guard("exec_command", json.dumps({"cmd": cmd}), True))
        assert "rejected" not in data["cmd"], cmd


def test_still_rejects_a_redirect_into_a_source_file():
    data = json.loads(proxy.apply_exec_guard(
        "exec_command", json.dumps({"cmd": "printf 'x' > src/app.ts"}), True))
    assert "proxy rejected this edit command" in data["cmd"]


def test_rewrites_mv_of_a_scratch_file_into_a_patch():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".spec.ts", delete=False) as handle:
        handle.write("import { describe, it } from 'vitest';\n")
        scratch = handle.name
    try:
        arguments = proxy.apply_exec_guard(
            "exec_command",
            json.dumps({"cmd": f"mv {scratch} packages/core/__tests__/x.spec.ts && wc -l packages/core/__tests__/x.spec.ts"}),
            True,
        )
        data = json.loads(arguments)
        assert "proxy rejected" not in data["cmd"]
        assert "*** Add File: packages/core/__tests__/x.spec.ts" in data["cmd"]
        assert "+import { describe, it } from 'vitest';" in data["cmd"]
        assert data["cmd"].endswith("wc -l packages/core/__tests__/x.spec.ts")
    finally:
        import os
        os.unlink(scratch)


def test_mv_of_an_unreadable_source_still_rejected():
    arguments = proxy.apply_exec_guard(
        "exec_command",
        json.dumps({"cmd": "mv /nope/missing.ts packages/core/__tests__/x.spec.ts"}),
        True,
    )
    assert "proxy rejected this edit command" in json.loads(arguments)["cmd"]


def test_splits_a_body_that_closes_one_patch_and_opens_another():
    # Observed on the medium fixture: the model deleted a file, wrote '*** End Patch', then
    # added it back. apply_patch honours the first End marker, so the file was deleted and
    # never rewritten. Each section now runs as its own invocation.
    cmd = (
        "apply_patch <<'PATCH'\n"
        "*** Begin Patch\n"
        "*** Delete File: tasklib/repository.py\n"
        "*** End Patch\n"
        "*** Add File: tasklib/repository.py\n"
        "+import json\n"
        "*** End Patch\n"
        "PATCH"
    )
    data = json.loads(proxy.apply_exec_guard("exec_command", json.dumps({"cmd": cmd}), True))
    out = data["cmd"]
    assert out.count("apply_patch <<") == 2
    assert "*** Delete File: tasklib/repository.py" in out
    assert "*** Add File: tasklib/repository.py" in out
    assert "+import json" in out
    assert out.index("*** Delete File") < out.index("*** Add File")


def test_single_section_body_still_rewritten_once():
    cmd = (
        "apply_patch <<'PATCH'\n"
        "*** Begin Patch\n"
        "*** Add File: api.py\n"
        "+import json\n"
        "*** End Patch\n"
        "PATCH"
    )
    data = json.loads(proxy.apply_exec_guard("exec_command", json.dumps({"cmd": cmd}), True))
    assert data["cmd"].count("apply_patch <<") == 1


def test_generated_block_survives_a_second_guard_pass():
    # The proxy rewrites a write into a conditional apply_patch block, then the same pipeline
    # runs the guard over that block again. HTML in the patch body matched the redirect rule
    # (">Note" from "<strong>Note %d") and the generated command was rejected.
    cmd = "cat > app.py <<'EOF'\nhtml = '<li><strong>Note %d</strong></li>'\nEOF"
    first = proxy.apply_exec_guard("exec_command", json.dumps({"cmd": cmd}), True)
    generated = json.loads(first)["cmd"]
    assert proxy.DELIMITER_BASE in generated

    second = proxy.apply_exec_guard("exec_command", first, True)
    assert second == first, "second pass changed or rejected the generated block"
