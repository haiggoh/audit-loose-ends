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

NUDGE="audit-loose-ends: when a substantive task ends, when the user signals to wrap up / conclude the session, or when THIS session has created or changed durable records (memories, project notes, reminders/crons, the task list, or the waypoints store) — run the audit reconciliation before closing. Scan those surfaces for anything REDUNDANT, ORPHANED, or FALSELY still-flagged as to-do when it's actually done, and fix it; distinguish a historical completion record (keep) from a stale pending flag on finished work (fix). Mark finished items done (e.g. \`waypoints done <id>\`), capture genuinely-open follow-ups as waypoints, and confirm touched repos are committed/clean with nothing accidentally public. This is NOT length-based — trigger on durable-state change, not on effort; skip read-only/exploratory turns. Consult the audit-loose-ends skill for the full procedure."

printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' \
  "$(json_escape "$NUDGE")"
