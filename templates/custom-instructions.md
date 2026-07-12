# Manual install (without the plugin)

If you don't use the plugin, paste this into your `CLAUDE.md` (or an `AGENTS.md`) to get the same
behavior as a personal always-on rule:

---

**Audit records at wrap-up.** At the end of a substantive task, when I signal a wrap-up ("wrap",
"wrap up", "audit", "tidy up", "close out"), or whenever a session has created or changed durable
records (memories, project notes, reminders/crons, the task list, or the waypoints store), reconcile
those records before closing: scan for anything redundant, orphaned, or falsely still-flagged as
to-do when it's actually done, and fix it. Distinguish a historical completion record (keep) from a
stale pending flag on finished work (fix). Mark finished items done (e.g. `waypoints done <id>`),
capture genuinely-open follow-ups as waypoints, and confirm touched repos are committed/clean. NOT
length-based — trigger on durable-state change, not on effort; skip read-only/exploratory turns.
