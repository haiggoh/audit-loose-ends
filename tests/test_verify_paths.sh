#!/usr/bin/env bash
# tests/test_verify_paths.sh — tests for scripts/verify-paths.sh. Both directions: the guard must pass an all-exist list and FAIL
# naming every missing path. A guard that has never been seen to fail is indistinguishable from
# one that cannot.
set -uo pipefail
HERE="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V="$HERE/../scripts/verify-paths.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf '  FAIL %s (expected %s, got %s)\n' "$1" "$2" "$3"; }
is()  { [ "$2" = "$3" ] && ok "$1" || bad "$1" "$2" "$3"; }

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/with space"; touch "$TMP/a.md" "$TMP/with space/b c.md"

is "--help exits 0 and prints usage" "$("$V" --help >/dev/null 2>&1; echo $?)" "0"
is "usage names --null" "$("$V" --help 2>&1 | grep -c -- --null)" "2"
is "an unknown flag exits 2" "$("$V" --bogus >/dev/null 2>&1; echo $?)" "2"
is "no arguments exits 2" "$("$V" >/dev/null 2>&1; echo $?)" "2"

is "all-exist passes" "$("$V" "$TMP/a.md" "$TMP/with space/b c.md" >/dev/null 2>&1; echo $?)" "0"
is "and reports the count" "$("$V" "$TMP/a.md" 2>/dev/null)" "verify-paths.sh: all 1 path(s) exist"
"$V" "$TMP/a.md" "$TMP/gone.md" >/dev/null 2>&1
is "a missing path fails" "$?" "1"
is "and names it" "$("$V" "$TMP/a.md" "$TMP/gone.md" 2>&1 | grep -c "missing: $TMP/gone.md")" "1"
is "and states the count" "$("$V" "$TMP/a.md" "$TMP/gone.md" 2>&1 | grep -c "1 of 2")" "1"
is "--quiet reports the count without the listing" \
   "$("$V" -q "$TMP/gone.md" 2>&1 | grep -c "missing:")" "0"

# --null is the whole point: a path with a space must not be split.
out=$(printf '%s\0' "$TMP/with space/b c.md" "$TMP/gone.md" | "$V" --null 2>&1)
is "--null reads NUL-delimited paths unsplit" "$(printf '%s' "$out" | grep -c "1 of 2")" "1"
is "--null names the missing one intact" "$(printf '%s' "$out" | grep -c "missing: $TMP/gone.md")" "1"
is "--null does not report a split fragment" "$(printf '%s' "$out" | grep -c "missing: c.md")" "0"

printf '\npassed %d, failed %d\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
