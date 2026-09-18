#!/usr/bin/env bash
# Check (and optionally fetch) everything this setup needs, then say what to run next.
#
#   usage: ./setup.sh            check, and print the exact command for anything missing
#          ./setup.sh --clone    also clone the PrismML llama.cpp fork if absent
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FORK="${FORK:-$HOME/projects/bonsai2-cuda/fork}"
MODEL="${MODEL:-$HOME/projects/bonsai2-cuda/models/Ternary-Bonsai-2-27B-PTQ1_0.gguf}"
CLONE=0
[ "${1:-}" = "--clone" ] && CLONE=1

missing=0
ok() { printf '  ok      %s\n' "$1"; }
bad() { printf '  MISSING %s\n' "$1"; missing=$((missing + 1)); }

echo "bonsai-codex setup check"
echo

echo "runtime"
command -v python3 >/dev/null 2>&1 && ok "python3 $(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')" \
  || bad "python3 - needed by the proxy and the harness"
command -v codex >/dev/null 2>&1 && ok "codex $(codex --version 2>/dev/null | head -1)" \
  || bad "codex CLI - the agent that drives the model (npm i -g @openai/codex)"
if [ -x "$FORK/build/bin/llama-server" ]; then
  ok "llama-server $FORK/build/bin/llama-server"
else
  bad "llama-server at $FORK/build/bin - stock llama.cpp and Ollama cannot read PTQ1_0"
fi

echo
echo "model"
if [ -f "$MODEL" ]; then
  ok "$(basename "$MODEL") ($(du -h "$MODEL" | cut -f1))"
else
  bad "model weights at $MODEL"
fi

echo
echo "gpu"
if command -v nvidia-smi >/dev/null 2>&1; then
  ok "$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
  free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)"
  if [ "$free_mib" -lt 6500 ]; then
    printf '  note    only %s MiB free - the 27B at 24k context wants ~6.3 GB; close desktop apps\n' "$free_mib"
  fi
else
  bad "nvidia-smi - a CUDA GPU is required"
fi

echo
echo "port"
if command -v ss >/dev/null 2>&1; then
  holder="$(ss -ltnp 2>/dev/null | awk '$4 ~ /:8080$/ {print $6; exit}')"
  if [ -n "$holder" ]; then
    printf '  note    :8080 is taken (%s) - start the server with PORT=8081 and pass PORT=8081 to run-task.sh\n' "$holder"
  else
    ok ":8080 free"
  fi
fi

echo
if [ "$missing" -eq 0 ]; then
  cat <<'NEXT'
all set. run:
  scripts/run-server.sh                                   # serves on http://127.0.0.1:8080
  scripts/run-task.sh tasks/easy-api "Implement create_app() in api.py so the tests pass."
NEXT
  exit 0
fi

echo "$missing item(s) missing."
if [ ! -x "$FORK/build/bin/llama-server" ]; then
  cat <<FORKHELP

llama.cpp fork, built for this GPU:
  git clone --depth 1 --branch prism-b10685-7dffb15 https://github.com/PrismML-Eng/llama.cpp "$FORK"
  cmake -B "$FORK/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DGGML_NATIVE=OFF \\
    -DCMAKE_CUDA_ARCHITECTURES=75-real -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-15 \\
    -DCUDAToolkit_ROOT=/opt/cuda -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF
  cmake --build "$FORK/build" -j 16 --target llama-server llama-bench llama-cli
  # 75-real is Turing (sm_75); change it to your compute capability.
FORKHELP
  [ "$CLONE" = "1" ] && [ ! -d "$FORK" ] && git clone --depth 1 --branch prism-b10685-7dffb15 \
    https://github.com/PrismML-Eng/llama.cpp "$FORK"
fi
if [ ! -f "$MODEL" ]; then
  cat <<MODELHELP

model weights (5.95 GB, PTQ1_0 is a PrismML quant - do not substitute a stock Q4/Q2 build):
  huggingface-cli download prism-ml/Ternary-Bonsai-2-27B-gguf \\
    Ternary-Bonsai-2-27B-PTQ1_0.gguf --local-dir "$(dirname "$MODEL")"
MODELHELP
fi
echo
echo "paths are overridable: FORK=... MODEL=... scripts/run-server.sh"
exit 1
