#!/usr/bin/env bash
# Tests for scripts/observation-log.py — the resolver that lets the audit and harvest-lessons steps
# find a task-observer log WITHOUT hardcoding this machine's path (task-observer is a soft
# dependency: another user may keep it elsewhere, on an older layout, or not have it at all).
# Every case runs against a throwaway HOME; nothing reads the real ~/.claude.
# Written for bash 3.2 (/bin/bash on macOS).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
RES="$HERE/../scripts/observation-log.py"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
has() { case "$2" in *"$3"*) ok "$1" ;; *) bad "$1" "$3" "$2" ;; esac; }
hasnt() { case "$2" in *"$3"*) bad "$1" "no $3" "$2" ;; *) ok "$1" ;; esac; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
run() { HOME="$1" TASK_OBSERVER_WORKSPACE="${2:-}" python3 "$RES" ${3:+"$3"} 2>&1; }
[ -n "${TASK_OBSERVER_WORKSPACE:-}" ] && unset TASK_OBSERVER_WORKSPACE

# 1. No task-observer at all: "none", exit 0 — the caller skips silently.
mkdir -p "$T/empty"
out="$(HOME="$T/empty" python3 "$RES")"; rc=$?
has "no workspace prints none" "$out" "none"
[ "$rc" -eq 0 ] && ok "no workspace exits 0" || bad "no workspace exits 0" "0" "$rc"

# 2. Legacy per-project log.md (pre-3.x): found, OPEN parsed, ACTIONED skipped.
L="$T/legacy/.claude/projects/-Users-x/skill-observations"; mkdir -p "$L"
printf '### Observation 4: Legacy open\n**Status:** OPEN\n\n### Observation 5: Legacy done\n**Status:** ACTIONED (2026-01-01)\n' > "$L/log.md"
out="$(run "$T/legacy" "" --open)"
has   "legacy layout is reported"      "$out" "legacy	$L/log.md"
has   "legacy OPEN entry listed"       "$out" "open	4	Legacy open"
hasnt "legacy ACTIONED entry skipped"  "$out" "Legacy done"

# 3. User-scope per-file log (3.x) beats a leftover legacy copy.
U="$T/legacy/.claude/skill-observations/observation-log"; mkdir -p "$U"
printf -- '---\nid: 7\ntitle: "Per-file open"\nstatus: open\n---\nbody\n' > "$U/0007-per-file-open.md"
printf -- '---\nid: 8\ntitle: "Per-file done"\nstatus: actioned\n---\n' > "$U/0008-per-file-done.md"
printf -- '---\nid: 9\ntitle: "No status field"\n---\n' > "$U/0009-no-status.md"
out="$(run "$T/legacy" "" --open)"
has   "user-scope per-file wins over legacy" "$out" "per-file	$U"
has   "per-file OPEN listed"                 "$out" "open	7	Per-file open"
has   "missing status counts as OPEN"        "$out" "open	9	No status field"
hasnt "per-file actioned skipped"            "$out" "Per-file done"
hasnt "legacy copy not used when per-file exists" "$out" "open	4"
has   "leftover legacy log reported as a shard"   "$out" "shard	$L/log.md"

# 4. TASK_OBSERVER_WORKSPACE pins a custom location and wins over both defaults.
C="$T/custom/place with space/skill-observations/observation-log"; mkdir -p "$C"
out="$(run "$T/legacy" "$T/custom/place with space")"
has "pinned workspace (with a space) wins" "$out" "per-file	$C"

# 5. Never RUNS on --help; unknown flags exit 2.
out="$(python3 "$RES" --help)"
has "--help explains the purpose" "$out" "locate the task-observer observation log"
has "--help documents TASK_OBSERVER_WORKSPACE" "$out" "TASK_OBSERVER_WORKSPACE"
python3 "$RES" --nope >/dev/null 2>&1; rc=$?
[ "$rc" -eq 2 ] && ok "unknown option exits 2" || bad "unknown option exits 2" "2" "$rc"

# 6. Portability: the shipped skills name the resolver, never one machine's project path.
for s in "$HERE/../skills/audit-loose-ends/SKILL.md" "$HERE/../skills/harvest-lessons/SKILL.md"; do
  grep -q 'scripts/observation-log.py' "$s" && ok "$(basename "$(dirname "$s")") uses the resolver" \
    || bad "$(basename "$(dirname "$s")") uses the resolver" "observation-log.py" "absent"
  grep -q 'projects/<project>/skill-observations\|write to its `log.md`' "$s" \
    && bad "$(basename "$(dirname "$s")") has no hardcoded observation path" "none" "found" \
    || ok "$(basename "$(dirname "$s")") has no hardcoded observation path"
done

echo
printf 'passed %s, failed %s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
