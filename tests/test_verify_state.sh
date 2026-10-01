#!/bin/bash
# Framework-free tests for scripts/verify-state.py
# Run: bash tests/test_verify_state.sh

set -uo pipefail

SCRIPT="$HOME/ClaudeWorkspace/audit-loose-ends/scripts/verify-state.py"
FAIL=0

check() {
    if [ "$1" = "$2" ]; then
        echo "  ok: $3"
    else
        echo "  FAIL: $3 (got '$1', want '$2')"
        FAIL=1
    fi
}

eq() {
    if [ "$1" = "$2" ]; then
        echo "  ok: $3"
    else
        echo "  FAIL: $3 (got '$1', want '$2')"
        FAIL=1
    fi
}

# ---- Step 1: failing tests for CLI contract ----

echo "== CLI contract =="

# --help exits 0 and mentions VERDICT
$SCRIPT --help > /tmp/help.out 2>&1
check "$?" "0" "--help exits 0"
grep -q "VERDICT" /tmp/help.out
check "$?" "0" "--help mentions VERDICT"

# --bogus exits 2 with usage on stderr
$SCRIPT --bogus > /tmp/bogus.out 2>&1; rc=$?
check "$rc" "2" "--bogus exits 2"
grep -q "usage:" /tmp/bogus.out
check "$?" "0" "--bogus prints usage on stderr"

# no args and no repos → prints VERDICT: CLEAN — 0 FAIL and exit 0
$SCRIPT > /tmp/clean.out 2>&1
check "$?" "0" "no args exits 0"
grep -q "VERDICT: CLEAN — 0 FAIL" /tmp/clean.out
check "$?" "0" "empty audit prints VERDICT: CLEAN — 0 FAIL"

echo "== CLI contract tests done =="

# ---- Step 2: read-only discriminant ----

echo "== read-only discriminant =="

# Create a throwaway repo
T=$(mktemp -d)
R="$T/repo"
mkdir -p "$R"
cd "$R" || exit 1
git init -q
git config user.email "test@test"
git config user.name "Test"
echo "x" > file.txt
git add file.txt
git commit -q -m "init"

# Record state before run
STAMP=$(mktemp)
touch "$STAMP"
sleep 0.1
before_write=$(find "$R" -newer "$STAMP" | wc -l)
before_stash=$(git -C "$R" stash list)
before_mtime=$(stat -f %m "$R/.git/index")

# Run verify-state.py (should make no changes)
$SCRIPT --repo "$R" > /dev/null 2>&1

# Check after run (stamp still before script run)
after_write=$(find "$R" -newer "$STAMP" | wc -l)
after_stash=$(git -C "$R" stash list)
after_mtime=$(stat -f %m "$R/.git/index")

check "$before_write" "$after_write" "no new files created"
check "$before_stash" "$after_stash" "no stash changes"
check "$before_mtime" "$after_mtime" "index mtime unchanged"

# Plant a write and show test catches it (using new stamp after script)
STAMP2=$(mktemp)
touch "$STAMP2"
sleep 0.1
python3 -c "
import os, time
os.utime('$R/file.txt', (time.time(), time.time()))
" 2>&1

planted_write=$(find "$R" -newer "$STAMP2" | wc -l)
if [ "$planted_write" -gt 0 ]; then
    echo "  ok: planted write detected (write count > 0)"
else
    echo "  FAIL: planted write not detected"
    FAIL=1
fi

# Restore and verify it goes back to clean
git -C "$R" checkout -- file.txt
STAMP3=$(mktemp)
touch "$STAMP3"
sleep 0.1
restored_write=$(find "$R" -newer "$STAMP3" | wc -l)
if [ "$restored_write" -eq 0 ]; then
    echo "  ok: restored repo passes read-only check"
else
    echo "  FAIL: restored repo fails read-only check"
    FAIL=1
fi

rm -rf "$T" "$STAMP" "$STAMP2" "$STAMP3"
echo "== read-only discriminant tests done =="

# ---- Summary ----
if [ $FAIL -eq 0 ]; then
    echo "ALL PASS"
    exit 0
else
    echo "FAILURES: $FAIL"
    exit 1
fi
