#!/usr/bin/env bash
# changelog.sh — regenerate the changelog view from commits (`version.changelog`).
#
# Prints a markdown section for everything since the last release tag (or a given
# ref), grouped by conventional-commit type. The committed docs/release-notes.md
# stays curated prose — this output is the raw material for its next section and
# the view the release skill reads. Never writes files, never commits.
#
#   scripts/changelog.sh            # since the last v* tag → HEAD
#   scripts/changelog.sh v0.6.2     # since a specific tag
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SINCE="${1:-$(git describe --tags --abbrev=0 --match 'v*' 2>/dev/null || true)}"
RANGE="HEAD"
[ -n "$SINCE" ] && RANGE="$SINCE..HEAD"

VERSION="$(jq -r .version .claude-plugin/plugin.json 2>/dev/null || echo unknown)"
echo "## v$VERSION (draft — generated from ${SINCE:-repo start}..HEAD)"
echo

section() {  # section <title> <grep-pattern>
  local title="$1" pat="$2" lines
  lines="$(git log --no-merges --format='%s' "$RANGE" | grep -E "$pat" || true)"
  [ -z "$lines" ] && return 0
  echo "### $title"
  echo "$lines" | sed -E 's/^[a-z]+(\([^)]*\))?!?: /- /'
  echo
}

section "Features"  '^feat(\(|:|!)'
section "Fixes"     '^fix(\(|:|!)'
section "Docs"      '^docs(\(|:|!)'
section "Internal"  '^(chore|refactor|test|ci|build|perf)(\(|:|!)'

# Anything that doesn't follow conventional commits still shows up.
OTHER="$(git log --no-merges --format='%s' "$RANGE" \
  | grep -Ev '^(feat|fix|docs|chore|refactor|test|ci|build|perf|release)(\(|:|!)' || true)"
if [ -n "$OTHER" ]; then
  echo "### Other"
  echo "$OTHER" | sed 's/^/- /'
  echo
fi
