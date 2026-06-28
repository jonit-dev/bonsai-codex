import io
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ollama_codex_proxy as proxy


def test_should_import_proxy_handler_from_facade_when_script_module_loaded():
    spec = importlib.util.spec_from_file_location("proxy_facade", ROOT / "src" / "ollama_codex_proxy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.Proxy is proxy.Proxy
    assert module.main is proxy.main


def test_should_show_help_when_cli_invoked():
    result = subprocess.run(
        [sys.executable, str(ROOT / "src" / "ollama_codex_proxy.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--model" in result.stdout


class CaptureProxy(proxy.Proxy):
    def forward(self, *args, **kwargs):
        self.forward_args = args
        self.forward_kwargs = kwargs


class Server:
    model = "configured-model"
    context_window = 65536
    max_output_tokens = 2048
    deny_tool_pattern = r"^denied$"
    reject_shell_writes = True


def make_handler(payload):
    handler = CaptureProxy.__new__(CaptureProxy)
    handler.path = "/v1/responses"
    handler.command = "POST"
    body = json.dumps(payload).encode("utf-8")
    handler.headers = {"content-length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.server = Server()
    return handler


def test_should_prepare_responses_payload_without_streaming_upstream():
    handler = make_handler(
        {
            "model": "requested-model",
            "stream": True,
            "max_output_tokens": 999999,
            "tools": [
                {"type": "function", "name": "exec_command"},
                {"type": "function", "name": "denied"},
                {"type": "web_search_preview"},
            ],
        }
    )

    handler.do_POST()

    (payload,) = handler.forward_args
    assert payload["model"] == "configured-model"
    assert payload["stream"] is False
    assert payload["max_output_tokens"] == 2048
    assert payload["max_tokens"] == 2048
    assert payload["options"]["num_predict"] == 2048
    assert payload["tools"] == [{"type": "function", "name": "exec_command"}]
    assert handler.forward_kwargs["allowed_tool_names"] == {"exec_command"}
    assert handler.forward_kwargs["stream_response"] is True


def test_should_forward_non_responses_post_with_json_body():
    handler = make_handler({"prompt": "hello"})
    handler.path = "/api/generate"

    handler.do_POST()

    assert handler.forward_args == ({"prompt": "hello"},)
    assert handler.forward_kwargs == {}


if __name__ == "__main__":
    test_should_import_proxy_handler_from_facade_when_script_module_loaded()
    test_should_show_help_when_cli_invoked()
    test_should_prepare_responses_payload_without_streaming_upstream()
    test_should_forward_non_responses_post_with_json_body()
    print("http proxy tests passed")
