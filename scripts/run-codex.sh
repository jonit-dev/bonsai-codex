#!/usr/bin/env bash
# Drive the local Bonsai model with Codex, through the proxy in this repository.
#
#   usage: scripts/run-codex.sh <project-dir> "<task>"
#
# Needs a llama-server already running; start one with scripts/run-server.sh.
set -euo pipefail

PORT="${PORT:-8080}"
PROXY_PORT="${PROXY_PORT:-11435}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PROJECT="${1:?usage: run-codex.sh <project-dir> \"<task>\"}"
TASK="${2:?usage: run-codex.sh <project-dir> \"<task>\"}"

# The proxy lives in this checkout. LLAMA_CODEX_DIR overrides it for people who keep the
# proxy elsewhere; the capability probe below stops a checkout that predates the fixes from
# being used silently (it would 500 on every request, or refuse to talk to llama-server).
LLAMA_CODEX_DIR="${LLAMA_CODEX_DIR:-$HERE}"

has_runtime_fixes() {
  local dir="$1"
  [ -f "$dir/bin/llama-codex" ] || return 1
  grep -rqs 'fold_instructions_into_leading_message' "$dir/src" || return 1
  grep -qs 'using_external_backend' "$dir/bin/llama-codex" || return 1
}

has_runtime_fixes "$LLAMA_CODEX_DIR" || {
  echo "$LLAMA_CODEX_DIR lacks the runtime fixes (see README.md); unset LLAMA_CODEX_DIR to use this checkout" >&2
  exit 1
}

curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null || {
  echo "no llama-server on :$PORT - run scripts/run-server.sh first" >&2
  exit 1
}

# llama-codex reuses whatever proxy already answers on the port, so a proxy left over from an
# earlier run keeps serving its own checkout. The proxy starts in well under a second, so
# always replace it rather than trusting the one that is there.
stop_stale_proxy() {
  local pid
  pid="$(pgrep -f "ollama_codex_proxy.*--port $PROXY_PORT" || true)"
  [ -n "$pid" ] || return 0
  echo "stopping proxy pid $pid to load the current checkout" >&2
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 40); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.25
  done
}
stop_stale_proxy

# Codex otherwise loads ~/.codex skills and hooks, which alone can exceed the context window.
# Keep it out of /tmp: Codex refuses to install its helper binaries under a temporary dir.
export CODEX_HOME="${CODEX_HOME:-$HOME/.local/state/bonsai-codex/codex-home}"
mkdir -p "$CODEX_HOME"

# 2048 (the proxy default) truncates the thinking trace before any tool call is emitted.
export LLAMA_CODEX_OLLAMA_URL="http://127.0.0.1:$PORT"
export LLAMA_CODEX_MODEL="${LLAMA_CODEX_MODEL:-bonsai}"
export LLAMA_CODEX_CONTEXT_WINDOW="${LLAMA_CODEX_CONTEXT_WINDOW:-24576}"
export LLAMA_CODEX_MAX_OUTPUT_TOKENS="${LLAMA_CODEX_MAX_OUTPUT_TOKENS:-12288}"

cd "$PROJECT"
exec "$LLAMA_CODEX_DIR/bin/llama-codex" exec \
  --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check \
  "$TASK"
