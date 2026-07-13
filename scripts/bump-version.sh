#!/usr/bin/env bash
# Version-drift tooling for the dev-workflow plugin. One source of truth for every
# file + field that carries the plugin version, declared in .version-bump.json at the
# repo root:
#
#   [{ "file": ".claude-plugin/plugin.json", "jq_path": ".version" }]   # JSON: edited with jq
#   [{ "file": "some.txt", "pattern": "^version = (.*)$" }]             # text: sed regex, \1 = version
#
# Modes:
#   bump-version.sh <new-version>   rewrite every declared spot to <new-version>
#   bump-version.sh --check         print each declared file's current version;
#                                   exit nonzero if they disagree (drift)
#   bump-version.sh --audit         --check, then grep the repo for the current version
#                                   string OUTSIDE the declared files (excluding .git and
#                                   docs/release-notes.md history) — catches spots that
#                                   should have been declared
#
# Portable to macOS bash 3.2 (no associative arrays). Requires jq.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPEC="$ROOT/.version-bump.json"
TAB="$(printf '\t')"

command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required" >&2; exit 2; }
[ -f "$SPEC" ] || { echo "ERROR: no version spec at $SPEC" >&2; exit 2; }

# Declared entries as file<TAB>jq_path<TAB>pattern, one per line.
ENTRIES="$(jq -r '.[] | [.file, (.jq_path // ""), (.pattern // "")] | @tsv' "$SPEC")"

read_one() {  # read_one <file> <jq_path> <pattern> -> prints current version
  local file="$1" jqp="$2" pat="$3"
  if [ -n "$jqp" ]; then
    jq -r "$jqp" "$ROOT/$file"
  else
    sed -nE "s/${pat}/\1/p" "$ROOT/$file" | head -1
  fi
}

write_one() {  # write_one <file> <jq_path> <pattern> <new> <current>
  local file="$1" jqp="$2" pat="$3" new="$4" cur="$5" tmp
  if [ -n "$jqp" ]; then
    tmp="$(mktemp)"
    jq --arg v "$new" "${jqp} = \$v" "$ROOT/$file" > "$tmp" && mv "$tmp" "$ROOT/$file"
  else
    sed -i.bak "s/${cur}/${new}/g" "$ROOT/$file" && rm -f "$ROOT/$file.bak"
  fi
}

CONSISTENT=""
check() {  # prints `file: version` per entry; sets CONSISTENT; returns 1 on drift
  local first="" have=0 drift=0 file jqp pat cur
  while IFS="$TAB" read -r file jqp pat; do
    [ -n "$file" ] || continue
    cur="$(read_one "$file" "$jqp" "$pat")"
    printf '%s: %s\n' "$file" "$cur"
    if [ "$have" -eq 0 ]; then first="$cur"; have=1
    elif [ "$cur" != "$first" ]; then drift=1; fi
  done <<EOF
$ENTRIES
EOF
  CONSISTENT="$first"
  return "$drift"
}

MODE="${1:-}"
[ -n "$MODE" ] || { echo "usage: bump-version.sh <new-version> | --check | --audit" >&2; exit 2; }

case "$MODE" in
  --check)
    if check; then exit 0; else echo "DRIFT: declared versions disagree" >&2; exit 1; fi
    ;;

  --audit)
    if check; then st=0; else st=1; fi
    ver="$CONSISTENT"
    echo "--- stray occurrences of '$ver' outside declared files ---"
    # Build an egrep exclusion: .git, the release-notes history, and every declared file.
    excl="/\.git/|docs/release-notes\.md"
    while IFS="$TAB" read -r file jqp pat; do
      [ -n "$file" ] || continue
      esc="$(printf '%s' "$file" | sed 's/[.[\*^$/]/\\&/g')"
      excl="$excl|$esc"
    done <<EOF
$ENTRIES
EOF
    hits="$(grep -rn --fixed-strings --exclude-dir=.git "$ver" "$ROOT" 2>/dev/null | grep -Ev "$excl" || true)"
    if [ -n "$hits" ]; then
      printf '%s\n' "$hits"
      echo "--- ^ these carry the version but are not declared in .version-bump.json ---"
    else
      echo "(none)"
    fi
    exit "$st"
    ;;

  --*)
    echo "ERROR: unknown option: $MODE" >&2; exit 2
    ;;

  *)
    new="$MODE"
    case "$new" in
      [0-9]*.[0-9]*.[0-9]*) : ;;
      *) echo "ERROR: <new-version> should look like X.Y.Z (got '$new')" >&2; exit 2 ;;
    esac
    while IFS="$TAB" read -r file jqp pat; do
      [ -n "$file" ] || continue
      cur="$(read_one "$file" "$jqp" "$pat")"
      write_one "$file" "$jqp" "$pat" "$new" "$cur"
      printf 'bumped %s: %s -> %s\n' "$file" "$cur" "$new"
    done <<EOF
$ENTRIES
EOF
    ;;
esac
