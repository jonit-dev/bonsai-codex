#!/usr/bin/env python3
"""Summarise a Codex rollout JSONL: turns, tool calls, stalls, verification outcome.

usage: session_report.py <rollout.jsonl> [more.jsonl ...]
"""
import json, os, sys, datetime

def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))

def report(path):
    rows = []
    for line in open(path):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    print(f"\n=== {path}")
    if not rows:
        print("  (empty)")
        return
    t0 = ts(rows[0]["timestamp"])
    t1 = ts(rows[-1]["timestamp"])
    calls = 0
    stalls = []
    last = t0
    for r in rows:
        t = ts(r["timestamp"])
        gap = (t - last).total_seconds()
        pl = r.get("payload") or {}
        kind = pl.get("type")
        if kind == "function_call":
            calls += 1
        if gap > 30:
            stalls.append((gap, last, kind, (pl.get("name") or "")[:40]))
        last = t
    usage = [r["payload"] for r in rows if r.get("type") == "token_usage_record"]
    answers = [r for r in rows if (r.get("payload") or {}).get("type") == "message"
               and (r.get("payload") or {}).get("role") == "assistant"]
    # usage.input_tokens is the real context window for that request; turn/thread counters sum
    # the whole session and say nothing about how close the model is to the window.
    windows = [(u.get("usage") or {}).get("input_tokens", 0) for u in usage]
    outputs = [(u.get("usage") or {}).get("output_tokens", 0) for u in usage]
    cap = int(os.environ.get("LLAMA_CODEX_MAX_OUTPUT_TOKENS", "8192"))
    cut_off = [n for n in outputs if n >= cap]
    if cut_off:
        print(f"  TRUNCATED: {len(cut_off)} turn(s) reached the {cap} output cap - the model "
              f"was cut off before it could emit a tool call")
    if usage and not answers:
        print("  NO ANSWER: agent stopped without a final message")
    print(f"  span {t0.time()}..{t1.time()} = {(t1-t0).total_seconds():.0f}s, "
          f"{len(rows)} rows, {calls} tool calls")
    if windows:
        print(f"  window: first {windows[0]} -> peak {max(windows)} tokens "
              f"over {len(windows)} requests")
    for gap, when, kind, name in stalls:
        print(f"  STALL {gap:7.0f}s before {when.time()} {kind} {name}")

for p in sys.argv[1:]:
    report(p)
