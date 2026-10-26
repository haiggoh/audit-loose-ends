#!/usr/bin/env bash
# Tests for install/link-shortcuts.sh. Everything runs against a TEMP HOME, so the
# real ~/.claude/scripts links are never touched.
#
# The contract is the one cost-tracker's wire-statusline.sh established: the entry
# points become SHIMS that resolve per call, so a plugin update lands with no
# re-wiring. These tests are deliberately near-identical to that repo's, because a
# shim contract that differs per plugin is not a contract.
set -uo pipefail
export LC_ALL=C

HERE="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN="$(cd -P "$HERE/.." && pwd)"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
is()  { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "$3" "$2"; fi; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
LINKS="redact-secret.py memory-index-audit.py"
WIRE="$PLUGIN/install/link-shortcuts.sh"

echo "link-shortcuts.sh"

# --- --help and a bad flag must do NO work -------------------------------------
H="$TMP/home"; mkdir -p "$H/.claude/scripts"
bash "$WIRE" --help > "$TMP/help.out" 2>&1
is "--help exits 0" "$?" "0"
is "--help prints usage" "$(grep -c '^Usage: link-shortcuts.sh' "$TMP/help.out")" "1"
is "--help documents --dry-run" "$(grep -c -- '--dry-run' "$TMP/help.out" | awk '{print ($1>0)?"yes":"no"}')" "yes"
bash "$WIRE" --bogus > /dev/null 2>&1
is "an unknown flag exits 2" "$?" "2"

# --- a fixture "installed plugin": registry-recorded, real scripts -------------
# TWO cache versions, with the registry naming the OLDER one: the shim must follow
# the registry, not the highest cache dir. With a single version those two orders
# agree and a mutation that deletes the registry step survives green.
PDIR="$TMP/plugins"
FA="$PDIR/cache/haiggoh/audit-loose-ends/0.12.2"
NEWER="$PDIR/cache/haiggoh/audit-loose-ends/0.13.0"
for _v in "$FA" "$NEWER"; do
    mkdir -p "$_v/scripts" "$_v/.claude-plugin"
    printf '%s\n' '{"name":"audit-loose-ends","version":"0.12.2"}' > "$_v/.claude-plugin/plugin.json"
    cp "$PLUGIN/scripts/"* "$_v/scripts/"
done
cp "$PLUGIN/install/shim-template.sh" "$FA/install/shim-template.sh" 2>/dev/null || { mkdir -p "$FA/install"; cp "$PLUGIN/install/shim-template.sh" "$FA/install/"; }
printf '%s' '{"plugins":{"audit-loose-ends@haiggoh":[{"scope":"user","installPath":"'"$FA"'"}]}}' \
    > "$PDIR/installed_plugins.json"

# --- dry run writes nothing ----------------------------------------------------
BEFORE="$(find "$H/.claude/scripts" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
HOME="$H" CLAUDE_PLUGINS_DIR="$PDIR" bash "$WIRE" --dry-run > "$TMP/dry.out" 2>&1
is "dry run exits 0" "$?" "0"
is "dry run says DRY RUN" "$(grep -c 'DRY RUN' "$TMP/dry.out")" "1"
is "dry run writes nothing" \
   "$(find "$H/.claude/scripts" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')" "$BEFORE"

# --- apply: shims, not symlinks ------------------------------------------------
HOME="$H" CLAUDE_PLUGINS_DIR="$PDIR" bash "$WIRE" > "$TMP/apply.out" 2>&1
is "apply exits 0" "$?" "0"
for f in $LINKS; do
    is "$f is a shim, not a symlink" \
       "$([ -L "$H/.claude/scripts/$f" ] && echo symlink || echo regular)" "regular"
    is "the $f shim carries the haiggoh-shim header" \
       "$(head -n 3 "$H/.claude/scripts/$f" | grep -c '^# haiggoh-shim v1 plugin=audit-loose-ends target=scripts/')" "1"
    is "the $f shim is executable" \
       "$([ -x "$H/.claude/scripts/$f" ] && echo yes || echo no)" "yes"
    is "the $f shim runs the installed copy's script" \
       "$(HOME="$H" CLAUDE_PLUGINS_DIR="$PDIR" /bin/sh "$H/.claude/scripts/$f" --help 2>&1 | head -1 | grep -c '.')" "1"
done
is "--which prints the resolved target" \
   "$(HOME="$H" CLAUDE_PLUGINS_DIR="$PDIR" /bin/sh "$H/.claude/scripts/redact-secret.py" --which)" \
   "$FA/scripts/redact-secret.py"

# --- THE UPDATE: repoint the registry, re-run nothing ---------------------------
printf '%s' '{"plugins":{"audit-loose-ends@haiggoh":[{"scope":"user","installPath":"'"$TMP/gone"'"}]}}' \
    > "$PDIR/installed_plugins.json"
printf '%s' '{"plugins":{"audit-loose-ends@haiggoh":[{"scope":"user","installPath":"'"$FA"'"},{"scope":"project","installPath":"'"$TMP/other"'"}]}}' \
    > "$PDIR/installed_plugins.json"
is "the shim resolves to the FIRST usable entry after a registry change" \
   "$(HOME="$H" CLAUDE_PLUGINS_DIR="$PDIR" /bin/sh "$H/.claude/scripts/redact-secret.py" --which)" \
   "$FA/scripts/redact-secret.py"

# --- a replaced symlink is backed up; a foreign file is refused -----------------
SL="$TMP/slink"; mkdir -p "$SL/.claude/scripts" "$SL/target/scripts"
printf '%s\n' 'OLD' > "$SL/target/scripts/redact-secret.py"
ln -s "$SL/target/scripts/redact-secret.py" "$SL/.claude/scripts/redact-secret.py"
HOME="$SL" CLAUDE_PLUGINS_DIR="$PDIR" bash "$WIRE" > /dev/null 2>&1
is "a replaced symlink exits 0" "$?" "0"
SBK="$(find "$SL/.claude/backups" -maxdepth 1 -name 'audit-loose-ends-link-*' 2>/dev/null | head -1)"
is "the replaced symlink is backed up" "$(grep -c OLD "$SBK/redact-secret.py" 2>/dev/null)" "1"
is "and the path now carries a shim" \
   "$([ -L "$SL/.claude/scripts/redact-secret.py" ] && echo symlink || echo regular)" "regular"

FH="$TMP/foreign"; mkdir -p "$FH/.claude/scripts"
printf 'echo mine\n' > "$FH/.claude/scripts/redact-secret.py"
HOME="$FH" CLAUDE_PLUGINS_DIR="$PDIR" bash "$WIRE" > "$TMP/foreign.out" 2>&1
is "a foreign file is refused (exit 1)" "$?" "1"
is "the refusal names the way out" "$(grep -c -- '--force' "$TMP/foreign.out")" "1"
is "the foreign file is left untouched" "$(cat "$FH/.claude/scripts/redact-secret.py")" "echo mine"
HOME="$FH" CLAUDE_PLUGINS_DIR="$PDIR" bash "$WIRE" --force > /dev/null 2>&1
is "--force replaces it" "$?" "0"

# --- a re-run is a no-op --------------------------------------------------------
HOME="$H" CLAUDE_PLUGINS_DIR="$PDIR" bash "$WIRE" > "$TMP/rerun.out" 2>&1
is "a re-run exits 0" "$?" "0"
is "a re-run reports nothing to do" "$(grep -c 'Nothing to do' "$TMP/rerun.out")" "1"

echo
printf 'passed %d, failed %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
