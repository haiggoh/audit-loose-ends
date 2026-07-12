#!/usr/bin/env bash
# Framework-free test for hooks/nudge.sh: it must emit ONE valid JSON object whose
# additionalContext carries the audit reminder. Requires bash + python3 (test-only, for JSON parse).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NUDGE="$HERE/../hooks/nudge.sh"
fail=0
check() { if [ "$1" = 0 ]; then echo "  ok: $2"; else echo "  FAIL: $2"; fail=1; fi; }

OUT="$(bash "$NUDGE")"

# 1) valid JSON + correct shape; extract additionalContext
CTX="$(printf '%s' "$OUT" | python3 -c 'import json,sys
d=json.load(sys.stdin)
assert d["hookSpecificOutput"]["hookEventName"]=="SessionStart"
print(d["hookSpecificOutput"]["additionalContext"])')"
check $? "emits valid SessionStart additionalContext JSON"

# 2) no user-visible banner (model-only nudge)
case "$OUT" in *systemMessage*) check 1 "no systemMessage (model-only)";; *) check 0 "no systemMessage (model-only)";; esac

# 3) key content present
case "$CTX" in *"audit-loose-ends:"*) check 0 "labelled 'audit-loose-ends:'";; *) check 1 "labelled 'audit-loose-ends:'";; esac
LC="$(printf '%s' "$CTX" | tr 'A-Z' 'a-z')"
case "$LC" in *redundant*orphaned*) check 0 "names redundant/orphaned drift";; *) check 1 "names redundant/orphaned drift";; esac
case "$CTX" in *"waypoints done <id>"*) check 0 "references the waypoints CLI";; *) check 1 "references the waypoints CLI";; esac
case "$CTX" in *"NOT length-based"*) check 0 "states the non-length trigger";; *) check 1 "states the non-length trigger";; esac

[ "$fail" = 0 ] && echo "ALL PASS" || { echo "FAILURES"; exit 1; }
