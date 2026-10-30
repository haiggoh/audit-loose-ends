#!/usr/bin/env bash
# Static-surface branding pins (plan 2026-10-28, §Wave 2 Task 5): the mark is the repo's
# GitHub About emoji — verbatim — on the identity surfaces. R2: exact strings, never loosened.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
fail=0
check() { if [ "$1" = 0 ]; then echo "  ok: $2"; else echo "  FAIL: $2"; fail=1; fi; }

# plugin.json description leads with the mark (R6)
DESC="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["description"])' "$ROOT/.claude-plugin/plugin.json")" \
  || { echo "  FAIL: plugin.json unreadable"; exit 1; }
case "$DESC" in "✍️ "*) check 0 "plugin.json description leads with ✍️";; *) check 1 "plugin.json description leads with ✍️ (got: ${DESC:0:40})";; esac

# README h1 (R6): exact
H1="$(head -1 "$ROOT/README.md")"
[ "$H1" = "# ✍️ audit-loose-ends" ]
check $? "README h1 is '# ✍️ audit-loose-ends' (got: $H1)"

# R5: a <=3-line Branding section in BOTH skill files
for f in "$ROOT/skills/audit-loose-ends/SKILL.md" "$ROOT/skills/harvest-lessons/SKILL.md"; do
  /usr/bin/grep -q '^## Branding (✍️)$' "$f"
  check $? "$(basename "$(dirname "$f")")/SKILL.md carries '## Branding (✍️)'"
done

[ "$fail" = 0 ] && echo "ALL PASS" || { echo "FAILURES"; exit 1; }
