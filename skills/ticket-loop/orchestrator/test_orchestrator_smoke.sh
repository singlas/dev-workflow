#!/bin/bash
# Offline end-to-end smoke test for orchestrator.sh: one full turn against a
# stub runner — no network, no docker, no claude. Uses fixed cadence so the
# pre-check (which would need Linear/Telegram) is skipped.
#
# Run: bash skills/ticket-loop/orchestrator/test_orchestrator_smoke.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/root/proj" "$TMP/orch"
touch "$TMP/root/proj/.dw-agent-clone"
: > "$TMP/agent.env"

cat > "$TMP/root/roster.yml" <<EOF
root: $TMP/root
cadence: fixed
interval: 30m
projects:
  - name: proj
    work_tree: $TMP/root/proj
    env_file: $TMP/agent.env
    state_dir: $TMP/state
EOF

# Stub runner: pretends one pass opened a PR, via the outcome.json contract.
cat > "$TMP/stub-pass.sh" <<'EOF'
#!/bin/bash
mkdir -p "$TICKET_LOOP_STATE_DIR"
printf '{"picked":1,"pr_opened":1,"asked":0,"blocked":0,"progressed":true,"error":null}\n' \
  > "$TICKET_LOOP_STATE_DIR/outcome.json"
EOF
chmod +x "$TMP/stub-pass.sh"

ORCH_ROSTER="$TMP/root/roster.yml" ORCH_STATE_DIR="$TMP/orch" \
ORCH_RUN_PASS="$TMP/stub-pass.sh" ORCH_MAX_TURNS=1 \
  bash "$HERE/orchestrator.sh"

python3 - "$TMP/orch/orch-state.json" <<'PY'
import json, sys
st = json.load(open(sys.argv[1]))
ps = st["projects"]["proj"]
assert ps["last_outcome"] == "productive", ps
assert ps["next_eligible"], ps
assert "pass_started" not in st, st        # write-ahead consumed by record
print("smoke OK — outcome:", ps["last_outcome"], "next:", ps["next_eligible"])
PY
echo PASS
