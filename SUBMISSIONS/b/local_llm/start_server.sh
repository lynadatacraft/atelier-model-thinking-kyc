#!/usr/bin/env bash
# Serve Qwen3.5-4B Q4_K_M (+ vision encoder) locally with llama.cpp, OpenAI-compatible API on :8080.
#   our_work/local_llm/start_server.sh            # all layers on the Radeon iGPU (Vulkan)
#   NGL=0 our_work/local_llm/start_server.sh      # CPU only
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$HERE/llama.cpp/llama-b11412/llama-server" \
  -m "$HERE/models/Qwen3.5-4B-Q4_K_M.gguf" \
  --mmproj "$HERE/models/mmproj-F16.gguf" \
  -ngl "${NGL:-99}" \
  -c "${CTX:-16384}" \
  --host 127.0.0.1 --port 8080
