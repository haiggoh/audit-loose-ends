#!/usr/bin/env bash
# audit-loose-ends: run-5 §C memory primers (plan 2026-11-25-memory-plugin-primer, Task 2).
# The SessionStart nudge must carry each migrated memory's literal trigger vocabulary in its
# additionalContext, on BOTH lanes (localhost proxy + gateway base URL). RED until the
# knowledge block lands in hooks/nudge.sh.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NUDGE="$HERE/../hooks/nudge.sh"
fail=0
check() { if [ "$1" = 0 ]; then echo "  ok: $2"; else echo "  FAIL: $2"; fail=1; fi; }

ctx_of() { printf '%s' "$1" | python3 -c 'import json,sys
d=json.load(sys.stdin)
print(d["hookSpecificOutput"]["additionalContext"])'; }

OUT="$(bash "$NUDGE")"
CTX="$(ctx_of "$OUT")"

# one check per primer line (token = literal trigger vocabulary of the memory)
case "$CTX" in *"deletion review"*) check 0 "doc-trim: deletion review";; *) check 1 "doc-trim: deletion review";; esac
case "$CTX" in *"word-diff"*) check 0 "doc-trim: word-diff the whole doc";; *) check 1 "doc-trim: word-diff the whole doc";; esac
case "$CTX" in *"allowlist"*) check 0 "redact: allowlist for values";; *) check 1 "redact: allowlist for values";; esac
case "$CTX" in *"denylist"*) check 0 "redact: denylist regex leaks";; *) check 1 "redact: denylist regex leaks";; esac
case "$CTX" in *"planted positive"*) check 0 "functional-verification: planted positive";; *) check 1 "functional-verification: planted positive";; esac
case "$CTX" in *"WORKS/PARTIAL/BROKEN"*) check 0 "functional-verification: verdict classes";; *) check 1 "functional-verification: verdict classes";; esac

# both lanes must carry the tokens: gateway base URL, then explicit localhost proxy URL
OUT_GW="$(ANTHROPIC_BASE_URL=https://api.anthropic.com bash "$NUDGE")"
CTX_GW="$(ctx_of "$OUT_GW")"
for tok in "deletion review" "word-diff" "allowlist" "denylist" "planted positive" "WORKS/PARTIAL/BROKEN"; do
  case "$CTX_GW" in *"$tok"*) check 0 "gateway lane carries '$tok'";; *) check 1 "gateway lane carries '$tok'";; esac
done
OUT_LO="$(ANTHROPIC_BASE_URL=http://127.0.0.1:4147 bash "$NUDGE")"
CTX_LO="$(ctx_of "$OUT_LO")"
for tok in "deletion review" "allowlist" "planted positive"; do
  case "$CTX_LO" in *"$tok"*) check 0 "localhost lane carries '$tok'";; *) check 1 "localhost lane carries '$tok'";; esac
done

if [ "$fail" = 0 ]; then echo "ALL PASS"; else echo "FAILURES"; exit 1; fi
