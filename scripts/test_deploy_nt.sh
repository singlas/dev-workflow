#!/usr/bin/env bash
# Tests deploy-nt.sh's manifest walk.
#
# Regression guarded here: env_sync() reads the manifest on the loop's stdin
# (`done < "$MANIFEST"`). ssh reads stdin by default, so an ssh inside the loop
# without -n swallows the rest of the manifest and the loop ends after the
# FIRST entry. Shipped behaviour was a clean-looking:
#     OK   orch.env — identical on box
#     done.
# ...with the other eight files never examined, and a credential silently not
# pushed. These tests run the real loop against a fake `ssh` on PATH.
#
# Run: bash scripts/test_deploy_nt.sh
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/deploy-nt.sh"
FAIL=0
fail() { printf 'FAIL: %s\n' "$1"; FAIL=1; }
pass() { printf 'ok: %s\n' "$1"; }

# --- static: every ssh inside env_sync must carry -n -----------------------
# push_file's first ssh is the deliberate exception: stdin there IS the payload.
loop_body="$(awk '/^env_sync\(\)/{f=1} f{print; if (/^}/ && f) exit}' "$SCRIPT")"
bad="$(printf '%s\n' "$loop_body" | grep -n '[^-]ssh "' | grep -v 'ssh -n' || true)"
if [ -z "$bad" ]; then
  pass "every ssh inside env_sync carries -n"
else
  fail "env_sync has an ssh without -n (it will eat the manifest): $bad"
fi

if grep -q 'ssh "$HOST" "cat > $tmp" < "$src"' "$SCRIPT"; then
  pass "push_file keeps its stdin-as-payload ssh (the deliberate exception)"
else
  fail "push_file's payload ssh changed shape — re-check the stdin contract"
fi

# --- behavioural: run the real loop with a stdin-eating fake ssh -----------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/local"

# A fake ssh that behaves like the real one: with no -n it DRAINS stdin.
cat > "$TMP/bin/ssh" <<'FAKE'
#!/usr/bin/env bash
eat=1
while [ $# -gt 0 ]; do
  case "$1" in
    -n) eat=0; shift ;;
    -o) shift 2 ;;
    *) break ;;
  esac
done
[ "$eat" = 1 ] && cat >/dev/null 2>&1   # the stdin theft being guarded against
echo "deadbeef"                          # a sha that never matches -> "missing"
FAKE
chmod +x "$TMP/bin/ssh"

# Three manifest entries, all present in .local/, none matching the box sha.
for f in alpha.env bravo.env charlie.env; do echo "KEY_$f=x" > "$TMP/local/$f"; done
cat > "$TMP/local/deploy-manifest" <<'MAN'
# comment line
alpha.env    /home/agent/alpha.env    600
bravo.env    /home/agent/bravo.env    600
charlie.env  /home/agent/charlie.env  600
MAN

# Extract the real functions into a harness file and source them, so the loop
# under test is the one that ships, not a copy.
sed -n '/^key_names()/,/^}/p;/^push_file()/,/^}/p;/^env_sync()/,/^}/p' "$SCRIPT" > "$TMP/funcs.sh"
cat > "$TMP/harness.sh" <<HARNESS
LOCAL_DIR="$TMP/local"
MANIFEST="$TMP/local/deploy-manifest"
HOST=fakehost
MOUNT=/mnt/fake
CONTAINER=fake-container
. "$TMP/funcs.sh"
env_sync
HARNESS

# Answer NO to every push prompt: we are testing the WALK, not the push.
# env_sync reads the prompt from /dev/tty, so feed one that always says no.
out="$(cd "$TMP" && PATH="$TMP/bin:$PATH" bash "$TMP/harness.sh" 2>&1 </dev/null)"

for f in alpha.env bravo.env charlie.env; do
  if printf '%s' "$out" | grep -q "$f"; then
    pass "manifest walk reached $f"
  else
    fail "manifest walk never reached $f — stdin was eaten. Output: $out"
  fi
done

if printf '%s' "$out" | grep -q "considered 3 of 3"; then
  pass "walk reports considered 3 of 3"
else
  fail "expected 'considered 3 of 3' in output: $out"
fi

[ "$FAIL" = 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED"; exit 1; }
