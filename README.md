# llama-codex

Use Codex normally, but route model calls to a local Ollama model.

Day to day, run it exactly like `codex`:

```sh
llama-codex --yolo
```

Everything else is still the Codex interface:

```sh
llama-codex
llama-codex --yolo
llama-codex exec "Fix the failing tests"
llama-codex -a never exec "Fix the failing tests"
```

Behind the scenes, `llama-codex` starts Ollama when needed, starts a small compatibility proxy, writes a temporary model catalog, and delegates to the real `codex` binary.

## Why this exists

Codex has built-in open-source provider support:

```sh
codex --oss --local-provider ollama
```

Use the built-in path first when it works for your model. `llama-codex` is valuable when the stock local-provider path is not enough for agentic coding with Ollama models, especially when a model cannot emit tool calls in the exact format Codex expects.

The main value is tool compatibility. Many local models can reason about a tool call but emit it as plain JSON, fenced JSON, XML-style tags, or mixed prose plus JSON. `llama-codex` translates those common shapes into executable Codex function calls, and it can hide high-noise tools that confuse weaker local models.

The rest of the project supports that goal:

- Local setup: start Ollama, create a known-good model alias, and keep one model loaded for predictable memory use.
- Model metadata: advertise a usable context window and model catalog to the Codex CLI.
- Empirical quality gates: test models against repeatable fixtures, require real file edits, run unit tests, and record whether failures are model-side or wrapper-side.

If `codex --oss --local-provider ollama` passes the same benchmarks for a model, prefer the built-in path. Keep `llama-codex` for models that need tool-call translation, constrained tool surfaces, repeatable setup, or benchmark evidence.

## Setup

```sh
/Users/jsilva3/projects/llama-codex/install.sh
llama-codex init
```

`install.sh` creates:

```sh
~/.local/bin/llama-codex
```

`llama-codex init` verifies required commands, starts Ollama, pulls the default model if missing, writes the temporary model catalog, starts the compatibility proxy, and runs `doctor`.

Optional local config can live in `.env`:

```sh
cp .env.example .env
```

The `.env` file is ignored by git. Set `LLAMA_CODEX_ENV_FILE=/path/to/file` to load a different config file.

Before `init`, make sure these are installed:

```text
codex
ollama
python3
curl
```

If a dependency is missing, `init` offers to install supported dependencies:

```sh
llama-codex init
```

For unattended setup:

```sh
llama-codex init --yes
```

Supported installers:

```text
codex   npm install -g @openai/codex
ollama  brew install ollama
python3 brew install python
curl    brew install curl
```

## Default Model

By default, `llama-codex` uses:

```text
qwen3-coder-30b-65k
```

That alias is created from:

```text
hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:UD-Q4_K_XL
```

with Ollama `num_ctx` set to `65536`. The alias matters because Ollama's OpenAI-compatible `/v1/responses` path does not reliably honor request-level context overrides.

So this is enough:

```sh
cd /path/to/project
llama-codex --yolo
```

## Advanced

Use any Ollama model name that supports the API shape Codex needs:

```sh
llama-codex --yolo -m hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:UD-Q4_K_XL
```

Or use environment variables:

```sh
LLAMA_CODEX_MODEL='qwen3-coder-30b-65k' \
LLAMA_CODEX_CONTEXT_WINDOW=65536 \
llama-codex --yolo
```

The default context window is `65536` tokens.

Set a larger context for the proxy/model catalog when needed:

```sh
llama-codex --llama-context 32768 --yolo
```

On memory-constrained machines, lower it again if the desktop becomes sluggish or unstable:

```sh
llama-codex --llama-context 8192 --yolo
```

`llama-codex` defaults to a lean tool profile for local models. Lean mode keeps command execution available while hiding bulky non-coding tools such as MCP/resource discovery, plugin installation, planning UI, image inspection, and goal-management helpers. It also hides `write_stdin`, because local models often call it with invalid session IDs on long runs.

The wrapper also adds short local-agent steering instructions through the model catalog. They bias the model toward reading relevant files, making targeted edits, using complete test output for conclusions, repairing failures minimally, and reporting the exact verification command. The default steering also asks for compact action output: avoid filler, avoid obvious tool-use narration, quote concise errors, and do not restate the task after reading it. For PRDs, the default steering tells the model to treat acceptance criteria as requirements, avoid stopping after restating the PRD, work in verified slices, and report completed changes plus remaining risks. Override this with `LLAMA_CODEX_BASE_INSTRUCTIONS` if a model needs different behavior.

Use a different tool profile when needed:

```sh
llama-codex --llama-tools full --yolo
llama-codex --llama-tools tiny --llama-context 8192 --yolo
```

Available profiles:

```text
lean      default; hides bulky non-coding tools and write_stdin
standard  hides bulky non-coding tools but keeps write_stdin
full      exposes all tools sent by Codex
tiny      strict benchmark mode; exposes only command execution
```

When `llama-codex` starts Ollama, it uses conservative Ollama settings by default:

```text
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
```

Override those with wrapper-specific environment variables:

```sh
LLAMA_CODEX_OLLAMA_NUM_PARALLEL=1 \
LLAMA_CODEX_OLLAMA_MAX_LOADED_MODELS=1 \
llama-codex --yolo
```

## Extra Wrapper Flags

These flags are consumed by `llama-codex` and are not passed to Codex:

```sh
--llama-model MODEL
--llama-context TOKENS
--llama-tools PROFILE
--llama-lean
--llama-tiny
--llama-status
--llama-restart
--llama-stop
--llama-help
```

Everything else is passed through to `codex`.

Check resolved wrapper config:

```sh
llama-codex --llama-status
```

Verify setup:

```sh
llama-codex doctor
```

Stop the compatibility proxy:

```sh
llama-codex --llama-stop
```

Run local project checks:

```sh
make test
```

## Current Limitations

- This is a compatibility shim, not a quality guarantee.
- Qwen3-Coder can run at 65k context on the M1 Pro 32 GB machine, but that setting puts heavy pressure on local memory and GPU resources. Drop to 8k or 32k if the desktop becomes sluggish or unstable.
- Qwen2.5-Coder 14B, Seed-Coder 8B, and Ornith 9B were removed after failing the local Codex workflow.
- The proxy rewrites some model-emitted JSON tool text into Codex function calls.
- Model support is empirical. Some Ollama models do not support tools, and some emit tool-call text Codex cannot execute without parser support.

## Files

```text
bin/llama-codex              wrapper CLI
src/ollama_codex_proxy.py    compatibility proxy
install.sh                   symlink installer
tests/test_*.py              focused proxy behavior tests
```
