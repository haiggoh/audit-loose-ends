#!/usr/bin/env bash
# Framework-free content test for skills/audit-loose-ends/SKILL.md.
#
# The skill is prose, so what it "does" is only whatever a reader can act on. These assertions
# pin the parts that are load-bearing INSTRUCTIONS rather than explanation -- specifically the
# `waiting`-release contract, whose whole point is that the CLI cannot do half of it. If someone
# trims the prose and drops the hand-judgement half, `resolve` alone silently leaves milestone-met
# items parked forever, and nothing else in the repo would notice.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL="$HERE/../skills/audit-loose-ends/SKILL.md"
fail=0
check() { if [ "$1" = 0 ]; then echo "  ok: $2"; else echo "  FAIL: $2"; fail=1; fi; }
has() { grep -qF -- "$2" "$SKILL"; check $? "$1"; }

[ -f "$SKILL" ]; check $? "SKILL.md exists"

# --- the release half of the waypoints step ---
has "names the resolve command"                  'waypoints.py resolve'
has "points at the waiting view"                 'waypoints.py list --waiting'
has "gives the manual release command"           'waypoints.py triage <id> --clear'
has "states the done -> resolve -> prune order"  '`done` → `resolve` → `prune`'

# `resolve` is target-done-driven, so the two things it CANNOT do must both be stated, or a reader
# reasonably assumes running it discharges the whole duty.
grep -qi 'milestone is descriptive' "$SKILL"; check $? "says the milestone is not evaluated by the CLI"
grep -qi 'dangling target' "$SKILL";          check $? "covers dangling/stale waiting targets"
grep -qF 'triage <id> --waiting-on' "$SKILL"; check $? "gives the repoint command for a dangling target"

# Releasing must be framed as the SAME defect class as a stale done-flag, not an optional extra --
# that framing is why it belongs in a reconciliation pass at all.
grep -qi 'hides work that is ready\|the other way' "$SKILL"; check $? "frames a false block as reconciliation drift"

# --- soft dependency must cover the NEWER subcommand too, not just the CLI's presence ---
grep -qF 'command -v waypoints.py' "$SKILL"; check $? "the CLI presence probe is still documented"
grep -qi 'unrecognised-command\|unrecognized-command' "$SKILL"
check $? "handles a waypoints too old to have resolve"

# --- step 0: scan the transcript rather than resuming the session ---
has "documents the transcript scanner"        'scripts/audit-scan.py'
has "shows the exclude-the-live-session form" '--exclude'
has "documents --quote for follow-ups"        '--quote'
grep -qi 'step 0' "$SKILL";               check $? "the scan is positioned as step zero"
grep -qi 'fresh' "$SKILL";                check $? "frames it as auditing from a FRESH session"
grep -qi 'compaction' "$SKILL";            check $? "gives the after-compaction reason for an ordinary wrap"
grep -qi 'cc-transcript' "$SKILL";         check $? "points at the distiller for the different question"
# The most dangerous misreading: treating "the scan found the file" as "the record is fine".
grep -qi 'not a substitute\|never whether the change is correct' "$SKILL"
check $? "states the scan locates drift without judging it"
grep -qi 'Steps 1.6 are still the looking\|still the looking' "$SKILL"
check $? "keeps the surface checks mandatory after the scan"

# --- the standing prune contract must survive this change ---
has "still documents prune"        'waypoints.py prune'
has "still documents the archive"  'waypoints.py archive list'
grep -qi 'never hand-edit\|Do NOT substitute a hand-edit' "$SKILL"
check $? "still forbids hand-editing the store"

[ "$fail" = 0 ] && echo "ALL PASS" || { echo "FAILURES"; exit 1; }
