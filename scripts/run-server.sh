#!/usr/bin/env bash
# llama-server for Bonsai 2 27B PTQ1_0 on an 8 GB Turing card.
#
# The flags are the ones that fit in 8 GB. Do not raise -c without also checking the
# rs-cache allocation, and do not drop -np 1: the server default of 4 slots multiplies
# the rs cache and OOMs at 32k.
#
# Context is 24576, which ran 3h50m without a failure; 32768 hit "CUDA error: out of memory"
# inside CUDA graph capture and killed the server mid-run. It is deliberately *not* raised: a
# write-heavy run reached 24700 tokens and llama-server answered 400, so the proxy now keeps
# each request under LLAMA_CODEX_PROMPT_BUDGET (0.75) of this number instead of relying on a
# bigger window.
#
# --reasoning-budget closes the thinking block once the budget is spent. Without it this
# model can spend a whole max_output_tokens budget reasoning and emit no tool call at all,
# which Codex reports as an empty turn; 1024 leaves room for a large file write.
set -euo pipefail

FORK="${FORK:-$HOME/projects/bonsai2-cuda/fork}"
MODEL="${MODEL:-$HOME/projects/bonsai2-cuda/models/Ternary-Bonsai-2-27B-PTQ1_0.gguf}"
PORT="${PORT:-8080}"
CONTEXT="${CONTEXT:-24576}"
REASONING_BUDGET="${REASONING_BUDGET:-1024}"

[ -x "$FORK/build/bin/llama-server" ] || { echo "no llama-server at $FORK/build/bin" >&2; exit 1; }
[ -f "$MODEL" ] || { echo "no model at $MODEL" >&2; exit 1; }

# llama.cpp's own bind error arrives as "couldn't bind HTTP server socket" after the model
# header is parsed, which reads like a model problem. Say what actually holds the port, and
# how to move: PORT=8081 scripts/run-server.sh.
if command -v ss >/dev/null 2>&1; then
  holder="$(ss -ltnp 2>/dev/null | awk -v port=":$PORT" '$4 ~ port"$" {print $6; exit}')"
  if [ -n "$holder" ]; then
    echo "port $PORT is already in use ($holder)" >&2
    echo "pick another one:  PORT=8081 $0" >&2
    exit 1
  fi
fi

exec "$FORK/build/bin/llama-server" \
  -m "$MODEL" \
  -ngl 99 \
  -c "$CONTEXT" \
  -ctk q4_0 -ctv q4_0 \
  -ub 128 -b 256 \
  -np 1 \
  -fa on \
  --jinja \
  --reasoning-budget "$REASONING_BUDGET" \
  --host 127.0.0.1 --port "$PORT"
