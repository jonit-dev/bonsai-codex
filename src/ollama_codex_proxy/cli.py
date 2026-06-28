import argparse
import os
from http.server import ThreadingHTTPServer

from .http_server import Proxy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument("--backend", default="http://127.0.0.1:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--context-window", type=int, default=32768)
    parser.add_argument("--max-output-tokens", type=int, default=int(os.environ.get("LLAMA_CODEX_MAX_OUTPUT_TOKENS", "2048")))
    parser.add_argument("--deny-tool-pattern", default=os.environ.get("LLAMA_CODEX_DENY_TOOL_PATTERN", ""))
    parser.add_argument(
        "--reject-shell-writes",
        action="store_true",
        default=os.environ.get("LLAMA_CODEX_REJECT_SHELL_WRITES", "").lower() in {"1", "true", "yes"},
    )
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Proxy)
    server.backend = args.backend
    server.model = args.model
    server.context_window = args.context_window
    server.max_output_tokens = args.max_output_tokens
    server.deny_tool_pattern = args.deny_tool_pattern
    server.reject_shell_writes = args.reject_shell_writes
    print(f"ollama-codex-proxy listening on http://{args.host}:{args.port} -> {args.backend}", flush=True)
    server.serve_forever()
