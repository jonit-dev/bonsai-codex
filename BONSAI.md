# bonsai-codex

A plug-and-play local coding setup: **Bonsai 2 27B** (a ternary 27B, 5.95 GB) served by a
PrismML llama.cpp build, driven by the **Codex CLI** through the compatibility proxy in this
repository. Codex 0.154 speaks the Responses API and llama.cpp speaks chat completions; the
proxy in `src/` bridges the two, and everything the model needs to edit files reliably is in
here already — there is nothing to patch and no second checkout to keep in sync.

    ./setup.sh                     # check (and say how to fix) everything that is missing
    scripts/run-server.sh          # serve the model on http://127.0.0.1:8080
    scripts/run-task.sh tasks/easy-api "Implement create_app() in api.py so the tests pass."

What is in the repository:

| | |
|---|---|
| `src/`, `bin/`, `tests/` | the proxy and wrapper (`make test`) — the upstream llama-codex project |
| `scripts/` | `run-server.sh` (llama-server flags that fit 8 GB), `run-codex.sh` (one task), `run-task.sh` (fixture → agent → verify → ledger) |
| `tasks/` | three fixtures: single-file API, multi-file package, server-rendered web app |
| `tools/` | `session_report.py` (what happened in a run), `session_dump.py` (turn by turn) |
| `setup.sh` | prerequisite check with the exact command for anything missing |

Sections below are the measured notes: what the hardware does, the fixes this needs, what the
model is actually good at, and where it stops being useful. Numbers are real runs, not estimates.

## Upstream

This repository is a standalone copy of [llama-codex](https://github.com/jonit-dev/llama-codex)
plus the local Bonsai harness. It is not a GitHub fork: a single account cannot own both a
parent and its fork, so the relationship is recorded here instead. To pick up upstream proxy
changes:

```sh
git remote add upstream git@github.com:jonit-dev/llama-codex.git
git fetch upstream && git merge upstream/main
```

The runtime fixes listed further down are already on `main` here; upstream carries them on
`fix/bonsai-live-runtime`.

## Hardware and software

| | |
|---|---|
| GPU | NVIDIA RTX 2080 (Turing, sm_75, 8 GB) |
| CPU / RAM | Ryzen 9 5900X / 62 GB |
| OS | Arch Linux, driver 610.57 |
| CUDA | 13.3.1 (`pacman -S cuda`, brings `gcc15` — nvcc rejects GCC 16) |
| Model | `prism-ml/Ternary-Bonsai-2-27B-gguf`, `Ternary-Bonsai-2-27B-PTQ1_0.gguf` (5.95 GB) |
| Runtime | [PrismML llama.cpp fork](https://github.com/PrismML-Eng/llama.cpp) — stock llama.cpp and Ollama **cannot** read PTQ1_0 |

## Why the PrismML fork is mandatory

`PTQ1_0` and `PQ2_0` are unknown types to stock llama.cpp, which refuses them. The
`Q2_0` band is worse: it loads without a warning and produces gibberish, because there is
no Hadamard activation runtime. Ollama has the same problem, so this model cannot be served
through it at all.

## Prebuilt binaries do work on Turing (via PTX JIT)

The released Linux CUDA binaries ship cubins only for `sm_86/89` (+`120a/121a`) but **PTX for
`sm_50/61/70/75/80/90`**, so a 20-series card JIT-compiles on first run. Check with
`cuobjdump --list-ptx` — `--list-elf` lists cubins only and makes a Turing-capable binary
look unsupported. The asset also needs the matching CUDA runtime (`libcudart.so.13` for the
13.3 asset), not just the driver.

A source build for `sm_75` is equal within noise (25.69 vs 25.31 t/s) and skips the JIT cost:

```sh
git clone --depth 1 --branch prism-b10685-7dffb15 https://github.com/PrismML-Eng/llama.cpp fork
cmake -B fork/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DGGML_NATIVE=OFF \
  -DCMAKE_CUDA_ARCHITECTURES=75-real -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-15 \
  -DCUDAToolkit_ROOT=/opt/cuda -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF
cmake --build fork/build -j 16 --target llama-server llama-bench llama-cli
```

## Running it

```sh
scripts/run-server.sh          # 24k context, http://127.0.0.1:8080
```

Measured: **PP256 295.8 t/s, TG64 25.69 t/s**. Decode settles to ~20 t/s once the context
is deep, and prefill stays ~250 t/s. Turn latency is decode-bound: 4k generated tokens is
~3.5 minutes.

### 8 GB is the binding constraint, not speed

| Context | Result |
|---|---|
| 16384, FP16 KV | **OOM** — the ~150 MiB rs-cache buffer has no room left |
| 32768, `-ctk q4_0 -ctv q4_0 -ub 128 -b 256 -np 1` | loads, but **crashes the server** once a request pushes the context past ~12k: `CUDA error: out of memory` inside `ggml_cuda_graph_evaluate_and_capture`, which kills llama-server mid-run |
| 24576, same flags (**current default**) | works; measured peak 7216/8192 MiB during a live run |
| 65536, Q4 KV | OOM |
| 32768 with the server's default `-np 4` | **OOM** — slots multiply the rs cache |

`--reasoning-budget 1024` is in `run-server.sh` for a different reason: without it the model
can spend an entire output budget inside its thinking channel and emit no tool call at all,
which Codex reports as an empty turn (`last_agent_message: null`). Measured on `tasks/web-app`:
8427 output tokens generated, zero tool calls, run over.

## Driving it with Codex

Codex CLI 0.154 is **Responses-API only** (`wire_api = "chat"` was removed), so it needs
[llama-codex](https://github.com/jonit-dev/llama-codex) as the compatibility proxy between
Codex and llama-server.

```sh
scripts/run-codex.sh /path/to/project "Implement create_app() so the tests pass."
```

`run-codex.sh` probes for a checkout that carries the runtime fixes and refuses a path
without them; it also replaces any proxy already on the port, because llama-codex happily
reuses a running proxy and will then serve code from a checkout you are not editing.

### Run a task end to end

```sh
scripts/run-task.sh tasks/easy-api "Implement create_app() in api.py so the tests pass."
scripts/run-task.sh tasks/web-app  "Implement create_app(store_path) in app.py so the tests pass."
```

Each run copies the fixture into `~/.local/state/bonsai-codex/runs/<name>`, drives Codex,
prints the per-turn timing report for the session log, runs the fixture's tests, then appends
a row to `~/.local/state/bonsai-codex/results.tsv`
(`timestamp`, `task`, `wall`, `pass|fail`, `session log`) so runs stay comparable.
`STATE_DIR`, `RUNS_DIR` and `LEDGER` override the locations.

Inspect any run afterwards:

```sh
tools/session_report.py ~/.local/state/bonsai-codex/codex-home/sessions/2026/09/17/rollout-*.jsonl
tools/session_dump.py   <same file>     # turn by turn: tool calls, outputs, usage
```

`session_report.py` flags the two failure shapes that look like "it just stopped":
`TRUNCATED` (a turn hit the output cap) and `NO ANSWER` (the agent yielded without a tool
call or message).

### The fixes the setup needs

They are already applied in this repository (branch `fix/bonsai-live-runtime`, merged to
`main`). Each was reproduced from a session log before being changed, and each has a test.

| # | Symptom | Cause |
|---|---|---|
| 1 | every request 500s | `instructions` + a leading developer message became two system messages; strict chat templates reject that |
| 2 | wrapper refuses to start | run path required the `ollama` binary; llama-server is not Ollama |
| 3 | write rejected, model loops | `cat > f <<'EOF' … EOF` followed by the model's own `cat f` failed to match the heredoc rewrite |
| 4 | `apply_patch verification failed: multiple operations target <path>` | overwrites were rewritten into one patch holding both `*** Delete File` and `*** Add File`; **this blocked every edit to an existing file** |
| 5 | heredoc write rejected after a `cd` | the rewrite only matched a command *starting* with `cat`/`apply_patch`; any prefix sent the patch body through the shell-write scan |
| 6 | `python3 -c "open(f).read()"` rejected | the Python rule matched reads as well as writes |
| 7 | `cat x 2>/dev/null \|\| ls` rejected | the redirect rule read `>/dev/null` as a write into a file. This rejected *ordinary reads* constantly |
| 8 | finished draft thrown away | `mv /tmp/spec.ts packages/…/spec.ts` (draft then move into place) was rejected with no rewrite; `mv`/`cp` of a readable file now applies as a patch for the destination |
| 9 | window filling with tool output | Codex appends every command's output verbatim; outputs are now capped at 3000 chars (`LLAMA_CODEX_TOOL_OUTPUT_CHARS`) with an explicit `[elided]` marker |
| 15 | guard hid script writes | stripping every heredoc body (fix 13 below) also hid a file write inside `python3 - <<EOF … Path(x).write_text(...)`, and the model switched to that. Only patch-shaped bodies are dropped now |
| 14 | `apply_patch verification failed: multiple operations target <path>` after following the prompt | Codex's apply_patch refuses two operations on one path, so a delete+add replace written in one section was rejected whole and the file stayed deleted. Each file operation now runs as its own invocation |
| 18 | a request grew past the window | a write-heavy run reached 24700 tokens against a 24576 limit and llama-server answered 400, ending the run. The proxy now keeps each request under `LLAMA_CODEX_PROMPT_BUDGET` (0.75) of the window, shrinking the oldest tool outputs first; measured holding a run at 17.0k after it had climbed to 17.6k |
| 17 | invented `*** Replace File:` header | the model dumped a whole old/new body under a header apply_patch does not know and the edit was rejected. The `+` lines are the new file, so it is rebuilt as a delete plus an add |
| 16 | `cat > /dev/null` rejected | the cat rule matched the `/dev/null` idiom as a write; only real file targets are edits |
| 15 | guard hid script writes | the shell-write scan reads `>Note` in `"<strong>Note %d"` as a redirect. Heredoc bodies that look like patch data are no longer scanned as shell |
| 12 | proxy rejects its own output | the guard runs twice per response. On the second pass it scanned a block the proxy itself had generated: an HTML patch body matched the redirect rule (`>Note`, from `"<strong>Note %d"`), and the compat block's own `cat >"$patch_file"` looked like a shell write, so the command was rewritten and Codex refused to spawn it. Generated blocks are now recognised before anything else runs |
| 11b | file deleted, add never ran | the anti-full-rewrite guard rejected any patch without an `*** Update File:` hunk once the workspace had changes — which is the shape of every delete+add replace. The add half was rejected and the delete ran alone; an explicit `*** Delete File:` now passes |
| 11 | file deleted and never rewritten | the model replaced a file with `*** Delete File` + `*** End Patch` + `*** Add File` in one heredoc. apply_patch honours the first End marker and drops the rest, and the proxy passed it through because a body containing an End marker short-circuited every repair. Sections of a multi-section body now run as separate invocations |
| 10 | turn produces nothing | the model answered a `web-app` turn with 6.9k tokens of prose, the whole implementation inside a ` ```python ` fence, then re-read the file. A tool call *was* parsed, so the prose was dropped silently. A message carrying a 12+-line code fence whose only call is a read now becomes a directive naming the file to patch |

Three settings that silently break the loop:

- **`LLAMA_CODEX_MAX_OUTPUT_TOKENS=8192`** (the proxy default of 2048 is not enough). A
  full-file rewrite plus thinking exceeds 4096: measured 4247 output tokens cut off
  mid-write, which Codex reports as an empty turn.
- **One file per patch.** A multi-file task stalled on a single generation that batched four
  files into one `apply_patch`: at 18 t/s that turn runs for minutes and is cut off before the
  patch lands, losing the whole turn. The prompt asks for one file per call.
- **`--reasoning-budget 1024`** on llama-server. Without a bound the model spent an entire
  8427-token budget inside its thinking channel and emitted no tool call at all.
- **Isolate `CODEX_HOME`, and keep it out of `/tmp`.** Codex otherwise loads `~/.codex`
  skills and hooks, which alone can exceed the context window. Under `/tmp` it also refuses
  to install its helper binaries (`Refusing to create helper binaries under temporary dir`).

### What it is actually good at

| Task | Result |
|---|---|
| Fix a function against failing unit tests | ✅ 6/6, 18 s |
| Implement from a clear spec **with examples** | ✅ 5/5, 78 s |
| `tasks/easy-api` — single-file stdlib HTTP API | ✅ **4/4**: 162 s on the first fixed engine (9.6k tokens), **552 s on the current one**, and every endpoint re-checked live after each run (before the fixes: never wrote the file) |
| Real monorepo (`threenative-engine`): add `packages/core/__tests__/replay-protocol.spec.ts` | ✅ **3/3, 373 s, 15 tool calls** (first two attempts died on guard rejections, see below) |
| `tasks/medium-task-library` — multi-file tasklib package (138 lines, 4 files) | ✅ **4/4, 280 s, 8 tool calls** on the current engine, peak window 10.0k; behaviour re-checked by hand (trimmed title, normalised tags, status and tag filters, `ValueError` on blank/bad priority, JSON persistence across reload) |
| `tasks/web-app` — server-rendered page + JSON API, ~150 lines | ✅ **5/5, 661 s** once, page verified in a browser (form, note list, POST round-trip). Five later attempts on newer engines produced no second pass while surfacing fixes 11–18. The last one got closest: a 147-line implementation that passes **3/5**, the other two failing on a request timeout in its own handler — the same hang it was chasing through `http.client`/`socketserver` source when the run was stopped. Treat this fixture as the boundary, not the norm |

#### On a large repo: context is fine, reconnaissance is not

Adding one spec file to `threenative-engine` (big TS monorepo, vitest) succeeded end to end.
Window usage, measured per request from llama-server (`usage.input_tokens`):

| | real window | turns | outcome |
|---|---|---|---|
| before the context fixes | 6.9k → 20.0k | 6 | ❌ write rejected, no file |
| with output cap + narrow-read rules | 7.0k → 13.3k | 8 | ❌ no write in 9 min |
| final run (after the guard fixes below) | 7.0k → **18.2k** | 10 | ✅ 3/3 tests |

Roughly **1.1k tokens/turn** on a repo of that size, so a 24k window is not the binding
constraint. Note that Codex's `turn_token_usage`/`thread_token_usage` are cumulative sums:
they read 90k on the first run and do not describe the window.

A run also *ends* on a hard error when the request outgrows the window, so the proxy bounds the
request rather than the window (fix 18), and `run-task.sh` records an agent exit code instead of
losing the run.

What actually blocks work on a large repo is *reconnaissance*: the first attempt spent 13
read-only commands and nine minutes without an edit, re-reading files it had already read.
Prompt rules fixed the *size* of reads (the trim below cut a 10,207-char output to +455
window tokens) but not the *number*; expect a 27B model to be over-cautious here.

Verify a finished run by hand rather than trusting the agent's summary — the absorbed spec
was accepted only after `npx vitest run packages/core/__tests__/replay-protocol.spec.ts`
passed in the target checkout.

Treat it as a **single-file / mechanical worker**, not a driver. A cold multi-constraint spec
is where it falls over; failing tests or worked examples in the prompt are what make it work.
Worked examples are not decoration: the model produced valid patch syntax only after the
system prompt showed the literal shape, and every prompt-level rule that stayed prose kept
being violated.

**Harness choice matters more than you would think.** omp's default tool set costs 18,688
tokens before the first user message — 57% of the window — and it never made an edit in 12
minutes. Codex with llama-codex's `lean` profile sends **one** tool (`exec_command`), and the
isolated home keeps the first turn at ~2.4k tokens.

If you want a *local driver* on this card rather than a worker, go smaller: an 8B ternary
model leaves VRAM for 100k+ context, and context is what is actually scarce here.
