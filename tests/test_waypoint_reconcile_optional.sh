#!/usr/bin/env bash
# tests/test_waypoint_reconcile_optional.sh — waypoint-reconcile.py works on a machine WITHOUT waypoints.
# waypoints is a SOFT dependency of this plugin: no store, no CLI and no waypoints checkout must never
# make a script error, fail or stall (user, 2026-10-31). The script used to import waypoints_core at load
# time from one machine's checkout path, so it crashed with ModuleNotFoundError — even on --help.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; S="$ROOT/scripts/waypoint-reconcile.py"
fail=0; check() { if [ "$1" = 0 ]; then echo "  ok: $2"; else echo "  FAIL: $2"; fail=1; fi; }
H=$(mktemp -d); trap 'rm -rf "$H"' EXIT
run() { env -i HOME="$H" PATH=/usr/bin:/bin:/opt/homebrew/bin PYTHONDONTWRITEBYTECODE=1 "$@"; }

out=$(run python3 "$S" --help 2>&1); rc=$?
check $rc "--help works with no waypoints installed"
case "$out" in *usage:*) check 0 "  and prints usage";; *) check 1 "  and prints usage (got: ${out:0:80})";; esac

out=$(run python3 "$S" --repo "$H" 2>&1); rc=$?
check $rc "a reconcile with no waypoints installed exits 0"
case "$out" in *"waypoints is not installed"*) check 0 "  and says so";; *) check 1 "  and says so (got: ${out:0:80})";; esac

out=$(run env WAYPOINTS_CORE_DIR="$H/nope" python3 "$S" --repo "$H" 2>&1); rc=$?
r=0; [ "$rc" = 2 ] || r=1; check $r "a set-but-invalid WAYPOINTS_CORE_DIR fails loudly (exit 2, got $rc)"
case "$out" in *WAYPOINTS_CORE_DIR*) check 0 "  naming it";; *) check 1 "  naming it";; esac

# Installed (a stub core in the plugin cache layout, NEWEST version wins) but no store yet: exit 0.
for v in 0.9.0 0.14.0; do mkdir -p "$H/.claude/plugins/cache/haiggoh/waypoints/$v"; done
printf 'raise SystemExit("the OLD core was imported")\n' > "$H/.claude/plugins/cache/haiggoh/waypoints/0.9.0/waypoints_core.py"
cat > "$H/.claude/plugins/cache/haiggoh/waypoints/0.14.0/waypoints_core.py" <<'PY'
def load_store(p): return {"version": 1, "items": []}
def save_store(s): pass
def load_archive(p): return {"items": []}
def save_archive(a): pass
def promote_landed_waiting(items, archived): return []
def stale_waiting(items, archived): return []
def prune(items): return items, []
PY
out=$(run python3 "$S" --repo "$H" 2>&1); rc=$?
check $rc "installed but no store: exits 0"
case "$out" in *"no waypoints store"*) check 0 "  and says so";; *) check 1 "  and says so (got: ${out:0:80})";; esac

: > "$H/.claude/waypoints.json"; echo '{"version": 1, "items": []}' > "$H/.claude/waypoints.json"
out=$(run python3 "$S" --repo "$H" 2>&1); rc=$?
check $rc "installed with a store: reconciles through the NEWEST core (got: ${out:0:80})"

if [ "$fail" = 0 ]; then echo "ALL PASS"; else echo "FAILURES"; exit 1; fi
