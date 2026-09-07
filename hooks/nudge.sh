#!/usr/bin/env bash
# audit — SessionStart hook.
#
# Stateless: emits ONE JSON object carrying a one-line, MODEL-ONLY nudge
# (hookSpecificOutput.additionalContext). No user-visible banner and no marker —
# the rule is REACTIVE, meant to fire at end-of-task / when the user signals a
# wrap-up / when durable records changed. The full procedure lives in the audit skill.
#
# Pure bash (3.2-compatible); no jq/python dependency at runtime.

set -uo pipefail

# --- pure-bash JSON string escaper (bash 3.2 verified) ---
json_escape() {
  local s=$1
  s=${s//\\/\\\\}    # backslash -> \\  (MUST run first)
  s=${s//\"/\\\"}    # "         -> \"
  s=${s//$'\n'/\\n}  # newline   -> \n
  s=${s//$'\t'/\\t}  # tab       -> \t
  s=${s//$'\r'/\\r}  # CR        -> \r
  printf '%s' "$s"
}

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

NUDGE="audit-loose-ends: when a substantive task ends, when the user signals to wrap up / conclude the session, or when THIS session has created or changed durable records (memories, project notes, reminders/crons, the task list, or the waypoints store) — run the audit reconciliation before closing. Start at STEP 0: run \`$PLUGIN_ROOT/scripts/audit-scan.py --last 1\` to learn what the session actually CHANGED from the transcript rather than from recollection — it streams the raw JSONL from outside and prints a few KB (durable records by surface, waypoints commands, commits/tags/releases, automation actually changed, plus a GAPS section), so a long session can be audited from a FRESH cheap session instead of reloading a 300k-token one that costs dollars to resume. Use \`--quote '<regex>' --budget N\` to follow up on ONE thread instead of loading the session. Worth running for an ordinary wrap too: after a compaction your own record of the early session is gone while the transcript's is not, and that early work is exactly what gets left stale. It tells you WHERE to look, never whether a change was correct — the surface checks still apply. Then scan those surfaces for anything REDUNDANT, ORPHANED, or FALSELY still-flagged as to-do when it's actually done, and fix it; distinguish a historical completion record (keep) from a stale pending flag on finished work (fix). Mark finished items done (e.g. \`waypoints.py done <id>\`), capture genuinely-open follow-ups as waypoints, then \`waypoints.py resolve\` to release any \`waiting\` item whose block is gone, then \`waypoints.py prune\` so the closed pile moves to the archive instead of accumulating in the live store (soft dependency: probe with \`command -v waypoints.py\` first and skip the whole step if it is absent — never hand-edit the store JSON). A falsely-parked \`waiting\` item is the same defect as a stale done-flag, pointed the other way: it hides work that is ready. \`resolve\` only checks whether the target is \`done\`, so ALSO read \`waypoints.py list --waiting\` yourself and judge each MILESTONE — when the milestone has landed but the target has not, release it with \`waypoints.py triage <id> --clear\`. Then confirm touched repos are committed/clean with nothing accidentally public. For that last check run \`$PLUGIN_ROOT/scripts/redact-secret.py --scan-only [--explain-filtered] <the files you touched>\` — do NOT hand-roll a \`grep\` for sk-/password/token: an improvised pattern has no word-boundary, shape or value filtering and buries a real key in false positives. This is NOT length-based — trigger on durable-state change, not on effort; skip read-only/exploratory turns. Consult the audit-loose-ends skill for the full procedure."

printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' \
  "$(json_escape "$NUDGE")"
