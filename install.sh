#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install_dir="${HOME}/.local/bin"
mkdir -p "${install_dir}"
chmod +x "${project_root}/bin/llama-codex" "${project_root}/bin/bonsai-codex" "${project_root}/src/ollama_codex_proxy.py"
ln -sf "${project_root}/bin/llama-codex" "${install_dir}/llama-codex"
ln -sf "${project_root}/bin/bonsai-codex" "${install_dir}/bonsai-codex"
echo "Installed ${install_dir}/llama-codex -> ${project_root}/bin/llama-codex"
echo "Installed ${install_dir}/bonsai-codex -> ${project_root}/bin/bonsai-codex"

