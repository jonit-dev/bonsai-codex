#!/usr/bin/env bash
# Run one bench task end to end: fresh copy of the fixture, Codex driving Bonsai, verify.
#
#   usage: run-task.sh <task-dir|benchmark-dir> "<task prompt>" [run-name]
#
# Prints wall time, window/peak context for the run, the session log path, and the
# verification result, then appends a row to the results ledger.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_DIR="${1:?usage: run-task.sh <task-dir> \"<task prompt>\" [run-name]}"
PROMPT="${2:?usage: run-task.sh <task-dir> \"<task prompt>\" [run-name]}"
RUN_NAME="${3:-$(basename "$TASK_DIR")}"
STATE_DIR="${STATE_DIR:-$HOME/.local/state/bonsai-codex}"
RUNS_DIR="${RUNS_DIR:-$STATE_DIR/runs}"
LEDGER="${LEDGER:-$STATE_DIR/results.tsv}"
RUN_DIR="$RUNS_DIR/$RUN_NAME"

[ -d "$TASK_DIR" ] || { echo "no task dir at $TASK_DIR" >&2; exit 1; }
mkdir -p "$RUNS_DIR"
rm -rf "$RUN_DIR"
cp -r "$TASK_DIR" "$RUN_DIR"
chmod -R u+w "$RUN_DIR"

SESSION_DIR="${CODEX_HOME:-$STATE_DIR/codex-home}/sessions"

echo "run dir: $RUN_DIR"
started="$(date +%s)"
agent_status="n/a"
SESSION=""

record() {
  printf '%s\t%s\t%ss\t%s\t%s\t%s\n' \
    "$(date -Is)" "$RUN_NAME" "$(( $(date +%s) - started ))" "$1" \
    "${SESSION:-none}" "agent_exit=$agent_status" >> "$LEDGER"
}
# A killed run must still appear: without this the ledger reads as an all-pass history while
# cancelled attempts leave no trace.
trap 'record cancelled; exit 143' TERM INT
# A run that dies (context exceeded, server crash) must still be verified and recorded, so
# the ledger shows the failure instead of losing it to set -e.
set +e
"$HERE/scripts/run-codex.sh" "$RUN_DIR" "$PROMPT"
agent_status=$?
set -e
elapsed=$(( $(date +%s) - started ))
echo "wall time: ${elapsed}s (agent exit ${agent_status})"

SESSION="$(find "$SESSION_DIR" -name 'rollout-*.jsonl' -newermt "@$started" 2>/dev/null | sort | tail -1)"
if [ -n "$SESSION" ]; then
  python3 "$HERE/tools/session_report.py" "$SESSION"
else
  echo "no session log found under $SESSION_DIR"
fi

echo "=== verification ==="
cd "$RUN_DIR"
status="pass"
if [ -f verify.sh ]; then
  bash verify.sh || status="fail"
elif [ -d tests ]; then
  python3 -m unittest discover -s tests -v || status="fail"
else
  status="skipped"
fi

record "$status"
echo "ledger: $LEDGER -> $status ${elapsed}s (agent exit ${agent_status})"
