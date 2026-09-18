#!/usr/bin/env python3
"""Compact, greppable dump of a Codex rollout: turn-by-turn tool calls + results."""
import json, sys

for path in sys.argv[1:]:
    print(f"=== {path}")
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        pl = d.get("payload") or {}
        kind = pl.get("type")
        ts = d.get("timestamp", "")[11:19]
        if kind == "function_call":
            args = pl.get("arguments", "")
            print(f"{ts} CALL {pl.get('name')} {args[:400]}")
        elif kind == "function_call_output":
            out = str(pl.get("output", ""))
            print(f"{ts} OUT  {out[:400]}")
        elif kind == "message" and pl.get("role") == "assistant":
            txt = str(pl.get("content"))[:600]
            print(f"{ts} SAY  {txt}")
        elif kind == "reasoning":
            s = str(pl.get("summary") or pl.get("content") or "")
            print(f"{ts} think {s[:200]}")
        elif d.get("type") == "token_usage_record":
            u = pl.get("turn_token_usage") or pl.get("usage") or {}
            print(f"{ts} usage {u}")
