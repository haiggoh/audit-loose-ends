#!/usr/bin/env bash
# The version lives in more than one place, and it has drifted before. This asserts the manifest,
# the CHANGELOG's top released entry agree -- and that a bump without a changelog entry fails.
set -u

usage() {
  cat <<'EOF'
test_version_consistency.sh — assert this plugin's version is stated consistently.

The version lives in more than one place and has drifted before. Checks that:
  * .claude-plugin/plugin.json carries a version (the authoritative copy)
  * the CHANGELOG's newest released heading matches it
  * that heading has at least one bullet — a bump with no entry of its own is the
    specific failure mode this exists to catch

Usage:
  tests/test_version_consistency.sh        run the checks (exit 0 = all pass)
  tests/test_version_consistency.sh --help show this text

Takes no arguments and no environment variables. Reads only; writes nothing.
EOF
}
case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  "") ;;
  *) printf 'test_version_consistency.sh: unknown argument: %s\n' "$1" >&2
     printf 'usage: tests/test_version_consistency.sh [--help]\n' >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() { if [ "$1" -eq 0 ]; then echo "  ok: $2"; else echo "  FAIL: $2"; fails=$((fails+1)); fi; }

MANIFEST_V="$(sed -n 's/.*"version": "\([^"]*\)".*/\1/p' "$ROOT/.claude-plugin/plugin.json" | head -1)"
[ -n "$MANIFEST_V" ]; check $? "manifest carries a version ($MANIFEST_V)"

# The newest RELEASED heading, skipping an [Unreleased] placeholder.
CHANGELOG_V="$(grep -o '^## \[[0-9][^]]*\]' "$ROOT/CHANGELOG.md" | head -1 | tr -d '#[] ')"
[ "$CHANGELOG_V" = "$MANIFEST_V" ]
check $? "CHANGELOG's newest release ($CHANGELOG_V) == manifest ($MANIFEST_V)"

# A bump with no entry of its own is the specific failure mode: the heading must exist AND carry
# at least one bullet before the next heading.
BODY="$(awk -v v="## [$MANIFEST_V]" 'index($0,v)==1{f=1;next} f&&/^## /{exit} f' "$ROOT/CHANGELOG.md" | grep -c '^- ')"
[ "$BODY" -gt 0 ]
check $? "the $MANIFEST_V entry has content ($BODY bullets)"

if [ "$fails" -eq 0 ]; then echo "ALL PASS"; else echo "$fails FAILURE(S)"; exit 1; fi