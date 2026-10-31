#!/usr/bin/env bash
# tests/test_memory_index_audit.sh — pins the read limit memory-index-audit.py measures against.
# The harness cap is 25,000 BYTES (it prints that as "24.4KB" = KiB). An index of 24,700 bytes is
# UNDER the real cap, so the default must not flag it; 25,100 is over and must. Both directions:
# a guard that has never been seen to fail is indistinguishable from one that cannot.
set -uo pipefail
HERE="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
A="$HERE/../scripts/memory-index-audit.py"
pass=0; fail=0
ok()  { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf '  FAIL %s (expected %s, got %s)\n' "$1" "$2" "$3"; }
is()  { [ "$2" = "$3" ] && ok "$1" || bad "$1" "$2" "$3"; }

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# A MEMORY.md of exactly N bytes made of plain (non-link) lines: no orphans, nothing else to flag.
mkindex() {  # dir bytes
  mkdir -p "$1"
  python3 - "$1/MEMORY.md" "$2" <<'PY'
import sys
path, n = sys.argv[1], int(sys.argv[2])
line = "x" * 99 + "\n"
body = (line * (n // 100 + 1))[:n]
open(path, "w").write(body)
PY
}

mkindex "$TMP/under" 24700
mkindex "$TMP/over" 25100
is "fixture sizes are exact" "$(wc -c <"$TMP/under/MEMORY.md" | tr -d ' ')/$(wc -c <"$TMP/over/MEMORY.md" | tr -d ' ')" "24700/25100"

is "24,700 bytes is under the real 25,000 cap (default limit)" "$("$A" --dir "$TMP/under" >/dev/null 2>&1; echo $?)" "0"
is "25,100 bytes is over the cap (default limit)" "$("$A" --dir "$TMP/over" >/dev/null 2>&1; echo $?)" "1"
is "--help states the 25000 default" "$("$A" --help 2>&1 | grep -c 'default: 25000')" "1"
is "--help no longer states the stale 24400" "$("$A" --help 2>&1 | grep -c '24400')" "0"
is "an explicit --limit still overrides" "$("$A" --dir "$TMP/under" --limit 24000 >/dev/null 2>&1; echo $?)" "1"

printf '\npassed %d, failed %d\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
