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

# ---- Step 3: G1-G7 repo checks (failing tests) ----

echo "== G1-G7 repo checks =="

# Helper to create a throwaway repo with remote
# Returns: repo_path remote_path temp_dir (only these three lines on stdout)
make_repo_with_remote() {
    local T=$(mktemp -d)
    local R="$T/repo"
    local REMOTE="$T/remote.git"
    mkdir -p "$R" "$REMOTE"
    cd "$R" || exit 1
    git init -q
    git config user.email "test@test"
    git config user.name "Test"
    git remote add origin "$REMOTE"
    git init --bare -q "$REMOTE"
    # Create initial commit and push to establish upstream
    echo "init" > "$R/init.txt"
    git add init.txt
    git commit -q -m "init"
    git push -u -q origin master 2>/dev/null
    # Return ONLY repo path, remote path, and temp dir (separated by newlines)
    echo "$R"
    echo "$REMOTE"
    echo "$T"
} 2>/dev/null

# G1: conflict markers
echo "Testing G1 (conflict markers)..."
read -r R REMOTE T < <(make_repo_with_remote)
echo "<<<<<<< HEAD" > "$R/f.md"
echo "ours" >> "$R/f.md"
echo "=======" >> "$R/f.md"
echo "theirs" >> "$R/f.md"
echo ">>>>>>> abc" >> "$R/f.md"
git -C "$R" add f.md
git -C "$R" commit -q -m "add conflict"
$SCRIPT --repo "$R" > /tmp/g1.out 2>&1
grep -q "FAIL G1 conflict markers: f.md" /tmp/g1.out
check "$?" "0" "G1: conflict markers detected"

# G1/RF3: allow-markers flag
$SCRIPT --repo "$R" --allow-markers "$R/f.md" > /tmp/g1_allow.out 2>&1
grep -q "WARN G1 markers allowed by flag: f.md" /tmp/g1_allow.out
check "$?" "0" "G1/RF3: --allow-markers shows WARN not silent PASS"

# G2: dirty working tree
echo "Testing G2 (dirty working tree)..."
read -r R REMOTE T < <(make_repo_with_remote)
echo "x" > "$R/new.txt"
$SCRIPT --repo "$R" > /tmp/g2.out 2>&1
grep -q "FAIL G2 dirty" /tmp/g2.out
check "$?" "0" "G2: dirty working tree detected"
rm -rf "$(dirname "$R")"

# G3: ahead of upstream (local commit NOT pushed)
echo "Testing G3 (ahead/diverged/no upstream)..."
read -r R REMOTE T < <(make_repo_with_remote)
echo "y" > "$R/y.txt"
git -C "$R" add y.txt
git -C "$R" commit -q -m "local commit"
# Do NOT push - local is now ahead of origin/master
$SCRIPT --repo "$R" > /tmp/g3a.out 2>&1
grep -q "FAIL G3 ahead of origin" /tmp/g3a.out
check "$?" "0" "G3: ahead of upstream detected"

# G3: diverged (both local and remote have different commits)
{ read -r R; read -r REMOTE; read -r TEMP_DIR; } < <(make_repo_with_remote)
echo "z" > "$R/z.txt"
git -C "$R" add z.txt
git -C "$R" commit -q -m "local"
git -C "$R" push -q origin master

# Create a second clone to make a remote commit
R2="$TEMP_DIR/repo2"
git clone -q "$REMOTE" "$R2"
cd "$R2" || exit 1
echo "remote" > "$R2/remote.txt"
git add remote.txt
git commit -q -m "remote commit"
git push -q origin master

cd "$R" || exit 1
git fetch -q origin
# Now local and remote have different commits - they diverge
echo "w" > "$R/w.txt"
git -C "$R" add w.txt
git -C "$R" commit -q -m "local diverged"
$SCRIPT --repo "$R" > /tmp/g3b.out 2>&1
grep -q "FAIL G3 diverged" /tmp/g3b.out
check "$?" "0" "G3: diverged detected"

# G3: detached HEAD
read -r R REMOTE T < <(make_repo_with_remote)
git -C "$R" checkout --detach -q
$SCRIPT --repo "$R" > /tmp/g3c.out 2>&1
grep -q "WARN G3 detached HEAD" /tmp/g3c.out
check "$?" "0" "G3: detached HEAD detected"

# G3: no upstream
read -r R REMOTE T < <(make_repo_with_remote)
git -C "$R" branch --unset-upstream
$SCRIPT --repo "$R" > /tmp/g3d.out 2>&1
grep -q "WARN G3 no upstream" /tmp/g3d.out
check "$?" "0" "G3: no upstream detected"

# G4: rebase in progress
echo "Testing G4 (rebase/merge/cherry-pick in progress)..."
read -r R REMOTE T < <(make_repo_with_remote)
mkdir -p "$R/.git/rebase-merge"
$SCRIPT --repo "$R" > /tmp/g4.out 2>&1
grep -q "FAIL G4 rebase in progress" /tmp/g4.out
check "$?" "0" "G4: rebase in progress detected"

# G5: version mismatch
echo "Testing G5 (version agreement)..."
read -r R REMOTE T < <(make_repo_with_remote)
mkdir -p "$R/.claude-plugin"
echo '{"version": "0.2.0"}' > "$R/.claude-plugin/plugin.json"
echo "## [0.1.0]" > "$R/CHANGELOG.md"
$SCRIPT --repo "$R" > /tmp/g5.out 2>&1
grep -q "FAIL G5 version mismatch: plugin.json 0.2.0, CHANGELOG 0.1.0" /tmp/g5.out
check "$?" "0" "G5: version mismatch detected"

# G6: gh unavailable
echo "Testing G6 (gh unavailable)..."
read -r R REMOTE T < <(make_repo_with_remote)
git -C "$R" tag v0.2.0
# Run with PATH without gh
PATH="/usr/bin:/bin" $SCRIPT --repo "$R" > /tmp/g6a.out 2>&1
grep -q "UNKNOWN G6 gh unavailable" /tmp/g6a.out
check "$?" "0" "G6: gh unavailable → UNKNOWN"

# G6: stub gh that exits 1
{ read -r R; read -r REMOTE; read -r TEMP_DIR; } < <(make_repo_with_remote)
git -C "$R" tag v0.2.0
mkdir -p "$TEMP_DIR/bin"
cat > "$TEMP_DIR/bin/gh" <<'EOF'
#!/bin/bash
if [[ "$1" = "release" && "$2" = "view" ]]; then
    exit 1
fi
# For other commands, just exit 0 (we only test the release view case)
exit 0
EOF
chmod +x "$TEMP_DIR/bin/gh"
PATH="$TEMP_DIR/bin:/usr/bin:/bin" $SCRIPT --repo "$R" > /tmp/g6b.out 2>&1
grep -q "WARN G6 tag v0.2.0 has no GitHub release" /tmp/g6b.out
check "$?" "0" "G6: stub gh exits 1 → WARN"

# G7: remote URL with credentials
echo "Testing G7 (remote URL embeds credentials)..."
read -r R REMOTE T < <(make_repo_with_remote)
git -C "$R" remote set-url origin "https://user:SYNTH_TOKEN_123@example.invalid/r.git"
$SCRIPT --repo "$R" > /tmp/g7.out 2>&1
grep -q "FAIL G7 remote URL embeds credentials" /tmp/g7.out
check "$?" "0" "G7: credentials in remote URL detected"
# Assert token NOT printed
! grep -q "SYNTH_TOKEN_123" /tmp/g7.out
check "$?" "0" "G7: credential value hidden from output"

rm -rf "$T"
echo "== G1-G7 tests added =="

# ---- Summary ----
if [ $FAIL -eq 0 ]; then
    echo "ALL PASS"
    exit 0
else
    echo "FAILURES: $FAIL"
    exit 1
fi
