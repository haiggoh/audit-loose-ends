---
name: audit-loose-ends
description: Use to reconcile durable records at the end of a task or session so nothing is left stale — invoke when the user signals a wrap-up ("wrap up", "audit", "tidy up", "close out"), or whenever a session has created or changed durable records (memories, project notes, reminders/crons, the task list, or the waypoints store) and you're about to stop. Scans those surfaces for anything redundant, orphaned, or falsely still-flagged as to-do when it's actually done, and fixes it.
---

# audit — reconcile durable records so nothing goes stale

The recurring **end-of-task reconciliation** that keeps records honest: after work happens, its
*records* drift — a finished task still flagged "pending", a note describing a shipped plan, a
follow-up nobody tracked. (Distinct from **no-hidden-changes**, a one-time first-run rule audit.)

## When it applies

Trigger when **either**: the user signals a wrap-up ("wrap up", "audit", "tidy up", "close out"),
**or** this session created/changed durable records (memories, project notes, reminders, task list,
waypoints store) — especially work that completed something a record still flags as pending.
NOT length-based; tie-breaker: *"did this change persistent state or finish something a record
calls open?"*

## Step 0: scan the transcript, don't resume the session

```sh
"$CLAUDE_PLUGIN_ROOT/scripts/audit-scan.py"                        # THIS session (self-identifying)
"$CLAUDE_PLUGIN_ROOT/scripts/audit-scan.py" --exclude "$CUR" --last 3
"$CLAUDE_PLUGIN_ROOT/scripts/audit-scan.py" --all-projects --since 2026-09-01
```

It streams the raw JSONL from outside and prints a few KB: durable records modified grouped by
surface, waypoints commands run, commits/tags/releases by repo, automation actually *changed*, and a
GAPS section. **It tells you WHERE, never WHETHER** — it reports which files changed, never whether
the change is correct. It is not a substitute for the surface checks: Steps 1–8 are still the looking.

Read `DURABLE RECORDS MODIFIED` (backed by a change record) with more confidence than
`DURABLE RECORDS WRITTEN BY A SHELL COMMAND` (inferred from a `>`/heredoc/`sed -i`/`tee` command —
the command may have failed or only named the path; confirm those before acting on them).

**Lesson candidates.** The scanner prints a `lessons: N candidates (…)` summary line; if N>0, offer
harvest-lessons once (~N×1.5K budgeted). Since 0.13.6 user turns are read from `last-prompt`, raw
`user`, and mid-turn `queue-operation` records alike, and a zero in a class the self-test corpus
cannot fire prints UNKNOWN, not 0. `--self-test` must fire all five reported classes.

**Heredoc bodies.** Since 0.11.0 a write CALL inside an interpreter heredoc is listed, tagged
*(inside a heredoc body)*; a path merely NAMED in the body is not. Still blind: a script written to
a file and run later, a runtime-computed target, non-Python bodies — cross-check with `ls -lt` over
the records dir, bounded by the printed session span.

Run the scan on an ordinary wrap too: after a compaction your record of the early session is gone
while the transcript's is not. Audit a big session from a FRESH session reading the digest — treat a
digest-vs-memory disagreement as the digest being right about *what happened* and you being right
about *what it meant*.

When the digest raises a question, quote just the thread:

```sh
"$CLAUDE_PLUGIN_ROOT/scripts/audit-scan.py" --quote 'waypoints.*done' --budget 3000
```

For full chronology (reconstructing *reasoning*, not *changes*) use `cc-transcript` — a different
tool for a different question, and a much larger artifact.

## The procedure

1. **Memory** (`~/.claude/.../memory/`): every file indexed (no orphans)? Any entry describing
   finished work as pending/⏳/REMAINING/TODO? **Distinguish a historical completion record (keep)
   from a stale pending flag on finished work (fix).** Run the index auditor before and after edits:
   ```sh
   "$CLAUDE_PLUGIN_ROOT/scripts/memory-index-audit.py" --stale-desc [--reviewed "$CLAUDE_PLUGIN_ROOT/scripts/memory-index-reviewed.txt"]
   ```
   (`--stale-desc` flags memory bodies announcing corrections not reflected in `MEMORY.md`; exits 1
   on orphans/broken links; read-only.)
2. **Project notes** (e.g. `PROJECT-NOTES.md` in the relevant repos): do "remaining"/"next" lists
   still list things that are done?
3. **Reminders / scheduled tasks**: still needed, or fired-and-forgotten?
4. **Task list**: anything stuck pending/in-progress that's actually done?
5. **Skill observations** (SOFT DEPENDENCY — probe, never assume the path; prints `none` when there
   is no log, then skip silently):
   ```sh
   "$CLAUDE_PLUGIN_ROOT/scripts/observation-log.py" --open
   ```
   Review each OPEN entry — action it or resolve it. In the per-file layout edit only that one
   file's frontmatter (`status`, `resolved`, `resolution`); in a legacy `log.md` mark it
   ACTIONED/DECLINED with the date. A `shard` line means two logs observe the same skills — report
   it. Entries are PROPOSALS, never authoritative state: promoting one into a durable rule is
   approval-gated.
6. **Waypoints store** (SOFT DEPENDENCY — `command -v waypoints.py` first; absent → skip silently.
   Never hand-edit `~/.claude/waypoints.json`: one JSON document, one bad escape loses every item):
   ```sh
   waypoints.py done <id> --evidence "…"   # finished items
   waypoints.py add "…"                    # genuine follow-ups
   waypoints.py resolve                    # release waiting items whose targets landed
   waypoints.py list --waiting             # what is still parked, and on what
   waypoints.py prune                      # move done items to the archive
   waypoints.py archive list               # the paper trail (`reopen <id>` restores one)
   ```
   Ordering: **`done` → `resolve` → `prune`**. Releasing a falsely-parked `waiting` item is the same
   defect class pointed the other way — a false block hides work that is ready to start. `resolve`
   keys only on the target's done flag, and the milestone is descriptive, not evaluated by the CLI:
   read each `list --waiting` milestone yourself, and when it has landed but the target has not,
   release the item with `waypoints.py triage <id> --clear` and say why. Dangling targets: repoint
   with `triage <id> --waiting-on "<real-id> @ …"`, never leave them dangling. An
   unrecognised-command error from `resolve` means the installed waypoints is too old for the
   waiting tier — skip it and carry on to prune. Released items come back untriaged on purpose.
   Residual-scope check: if an item's remainder is a subset of a sibling's full scope, close it with
   its outcome and transfer priority. `scripts/waypoint-reconcile.py` does this deterministically
   when waypoints is installed.
7. **Repos touched this session**: committed and clean? Run the shipped secret scanner — never a
   hand-rolled grep — on exactly the files you touched, NUL-delimited, count checked:
   ```sh
   "$CLAUDE_PLUGIN_ROOT/scripts/verify-paths.sh" --null
   "$CLAUDE_PLUGIN_ROOT/scripts/redact-secret.py" --scan-only --require FILE...
   ```
   Five filter layers (boundary → vendor shape → entropy → assignment-not-keyword → value sanity);
   `--explain-filtered` shows every near-miss and why; `--self-test` proves the no-false-negative
   property. `password=`/`token=` hits are report-only without `--include-assignments`. A printed
   response body can leak a credential too (a ttyd `/token` route returns base64 user:pass) — test
   auth by STATUS (`curl -o /dev/null -w '%{http_code}'`), never by content. A key found only in a
   LOCAL transcript was not leaked; rotate only what actually left the machine. Committed fixtures
   hold key TEMPLATES (`sk-ant-api03-{A:95}`, `AKIA{U:16}`), never literals. Never print a secret
   and then scrub it — filter by NAME before any value is emitted.
8. **Local record repos** (`$RECORD_REPOS`, default `~/.claude/plans/`): if a git repo, at wrap-up
   commit by path (NUL-delimited stage), never add a remote, never push; skip files modified in the
   last ~2 minutes and name them in the report (another session may still be writing). The
   durable skip/never choice lives in a visible documented file
   (`~/.claude/.audit-loose-ends/record-repos.json`), not hidden state.

While reconciling, sweep memories/notes for pending markers (⏳, REMAINING, TODO) not yet tracked as
waypoints and add them — here in the audit pass, never in a startup hook.

## Finishing an item

Mark it done **in whichever surface holds it** — flip the memory's flag, tick the note, and
`waypoints.py done <id> --evidence "commit <sha>, tests N/N"` (or `--no-evidence "superseded by <id>"`).
Never leave the same completion recorded as open in one place and done in another.

## Branding (✍️)

Lead the first substantive reply after `/audit-loose-ends` (or `/harvest-lessons`) with
"✍️ audit-loose-ends:" so the user can see which plugin just became active.

Incident history and measured anecdotes live in `docs/skill-history.md` — the skill body stays
lean; read that file when a rule's rationale matters.
