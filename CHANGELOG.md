# Changelog

## [0.3.0] — 2026-09-04

### Added
- **Pruning is now part of the routine reconciliation.** `done` leaves a waypoint in the LIVE
  store — only `prune` moves the closed pile into the archive — so a session that faithfully
  closed its items still left the store growing a permanent tail of finished work. The audit
  pass now sweeps closures and then prunes, in that order, so one pass covers the session.
- **Soft dependency on waypoints, probed rather than assumed.** Step 5 runs only when
  `command -v waypoints.py` finds the CLI. On a machine without waypoints the step is skipped
  silently: nothing is printed, and no `waypoints.py` command is attempted.
- The nudge and the skill now state the rule that the store JSON is **never** hand-edited when
  the CLI is missing — it is one JSON document, so a botched escape makes every item unreadable
  at once, not just the one being touched.

### Fixed
- The command name in the nudge, the skill and the README was `waypoints done <id>`; the CLI on
  the Bash-tool PATH is `waypoints.py` (the extensionless `waypoints` launcher is a different
  entry point). Three tests now assert the corrected name, the prune step and the probe.

## [0.2.0]
- Ship the secret scanner at the step that used to improvise a `grep`.

## [0.1.1]
- Drop bare "wrap" from the triggers; keep "wrap up" / "tidy up" / "audit".

## [0.1.0]
- First release: end-of-task reconciliation of durable records.
