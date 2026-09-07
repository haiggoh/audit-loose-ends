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
# The CLI is `waypoints.py` (note the .py) -- the bare name is a different, extensionless
# launcher that is NOT what the plugin puts on the Bash-tool PATH under that name.
case "$CTX" in *"waypoints.py done <id>"*) check 0 "references the waypoints CLI";; *) check 1 "references the waypoints CLI";; esac
case "$CTX" in *"waypoints.py prune"*) check 0 "names prune as part of the routine";; *) check 1 "names prune as part of the routine";; esac
# Releasing a falsely-parked `waiting` item is the mirror of pruning a done one, so the nudge must
# name `resolve` -- and must not stop there: `resolve` keys only on the target's done flag, so the
# reader has to be told to judge the MILESTONE by hand and how to release it when it has landed.
case "$CTX" in *"waypoints.py resolve"*) check 0 "names resolve as part of the routine";; *) check 1 "names resolve as part of the routine";; esac
case "$CTX" in *"list --waiting"*) check 0 "points at the waiting view for hand-judgement";; *) check 1 "points at the waiting view for hand-judgement";; esac
case "$CTX" in *"triage <id> --clear"*) check 0 "gives the manual release command";; *) check 1 "gives the manual release command";; esac
case "$CTX" in *MILESTONE*|*milestone*) check 0 "says the milestone is judged by the reader";; *) check 1 "says the milestone is judged by the reader";; esac
# Soft dependency: the nudge must tell the reader to PROBE, so a machine without waypoints is
# unaffected rather than being told to run a command it does not have.
case "$CTX" in *"command -v waypoints.py"*) check 0 "prune is gated on a probe";; *) check 1 "prune is gated on a probe";; esac
case "$CTX" in *"NOT length-based"*) check 0 "states the non-length trigger";; *) check 1 "states the non-length trigger";; esac

# the secret-sweep pointer must carry a RESOLVED absolute path (not the literal
# variable name) and must reach a file that actually exists
case "$CTX" in *'$PLUGIN_ROOT'*) check 1 "pointer path is resolved, not literal";; *) check 0 "pointer path is resolved, not literal";; esac
SCANPATH="$(printf '%s' "$CTX" | sed -n 's|.*`\(/[^`]*redact-secret.py\) --scan-only.*|\1|p')"
[ -n "$SCANPATH" ] && [ -f "$SCANPATH" ]
check $? "pointer names an existing redact-secret.py ($SCANPATH)"
case "$CTX" in *"hand-roll"*) check 0 "warns against hand-rolling a grep";; *) check 1 "warns against hand-rolling a grep";; esac

[ "$fail" = 0 ] && echo "ALL PASS" || { echo "FAILURES"; exit 1; }
