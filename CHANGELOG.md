# Changelog

## [0.4.0] — 2026-09-07

### Added
- **Releasing `waiting` waypoints is now part of the routine reconciliation, alongside pruning.**
  The two are the same duty pointed in opposite directions: pruning clears finished work out of the
  live store, releasing clears a *false block* off unfinished work. An item parked in the `waiting`
  tier is presented as nothing-for-you-to-do; once its condition is met that presentation is drift
  of exactly the kind this skill exists to catch, and arguably worse than a stale done-flag because
  it hides work that is ready to start. The pass now runs `waypoints.py resolve` every time — the
  release it performs may have been earned in an earlier session, so it is not conditional on
  having touched a waiting item this session.
- **The two things `resolve` cannot do are now stated as the reader's job.** It keys purely on
  whether the target item is `done`, which leaves two gaps that would otherwise look discharged:
  - *The milestone is descriptive, never evaluated.* `--waiting-on "some-id @ the design doc lands"`
    releases only when `some-id` closes entirely, even if that milestone was reached long ago. The
    pass now reads `waypoints.py list --waiting` and judges each milestone, releasing with
    `waypoints.py triage <id> --clear`. This is the common case for a long-running target with
    several milestones.
  - *Dangling targets are surfaced, not repaired.* `resolve` reports a waiting item pointing at a
    target that no longer exists and deliberately refuses to guess. That report is an orphaned
    record and is now explicitly this pass's to fix — repoint it with
    `triage <id> --waiting-on "<real-id> @ …"` or clear the block.
- Documented ordering: **`done` → `resolve` → `prune`**, with the note that pruning first is not
  wrong (an archived target still counts as landed), only a worse read of the same store.
- `tests/test_skill.sh` — the first content test over `SKILL.md`, pinning the load-bearing
  instructions of the release contract. Both halves are asserted, because prose that keeps
  `resolve` and drops the hand-judgement would leave milestone-met items parked forever with
  nothing in the repo noticing. Mutation-tested 5/5 against `test_nudge.sh`.

### Changed
- The SessionStart nudge now names `resolve` in the sequence and carries the milestone caveat, so
  the always-loaded surface and the skill agree.
- The soft dependency is now **two** probes, not one. `command -v waypoints.py` still gates the
  whole step, but the `waiting` tier and `resolve` shipped later than `done`/`prune`, so a
  waypoints old enough to lack the subcommand is treated as "this store has no waiting tier,
  nothing to release" — skipped silently, never reported as a failure, never emulated.

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
