---
name: audit-loose-ends
description: Use to reconcile durable records at the end of a task or session so nothing is left stale — invoke when the user signals a wrap-up ("wrap up", "audit", "tidy up", "let's close out"), or whenever a session has created or changed durable records (memories, project notes, reminders/crons, the task list, or the waypoints store) and you're about to stop. Scans those surfaces for anything redundant, orphaned, or falsely still-flagged as to-do when it's actually done, and fixes it.
---

# audit — reconcile durable records so nothing goes stale

The complement to storing progress: after work happens, the *records* of it drift — a finished task
still flagged "pending" in a memory, a note describing a plan that shipped, a follow-up nobody
tracked. Left alone, a future session re-surfaces settled ground as if it were open. This skill is
the recurring **end-of-task reconciliation** that keeps records honest.

(Distinct from **no-hidden-changes**, whose reconciliation is a *one-time, first-run* pass checking
whether a *rule* contradicts your setup. This one is *recurring* and reconciles *records*.)

## When it applies

Trigger when **either**:
- the user signals a wrap-up — "wrap up", "audit", "tidy up", "close out" — **or**
- this session **created or changed durable records** (memories, project notes, reminders/crons, the
  task list, or the waypoints store), especially work that **completed** something a record still
  flags as pending.

It is **NOT length-based**: a long but read-only/exploratory/record-free task needs no audit
(nothing can have gone stale); a short task that just closed a tracked to-do does. Tie-breaker:
*"did this change persistent state or finish something a record calls open?"*

## The procedure

Scan each surface and fix drift before closing:

1. **Memory** (`~/.claude/.../memory/`): index (`MEMORY.md`) + files. Every file indexed (no
   orphans)? Any entry describing finished work as pending/⏳/REMAINING/TODO? Any redundant/duplicate
   memory? **Distinguish a historical completion record (keep as-is) from a stale pending flag on
   finished work (fix).**
2. **Project notes** (e.g. `PROJECT-NOTES.md` in the relevant repos): do "remaining"/"next" lists
   still list things that are done?
3. **Reminders / crons / scheduled tasks**: still needed, or fired-and-forgotten?
4. **Task list** (the session task tracker): anything stuck pending/in-progress that's actually done?
5. **The waypoints store** (`~/.claude/waypoints.json`, if the `waypoints` plugin is present): mark
   finished items done (`waypoints.py done <id>`); **add genuinely-open follow-ups** you'd not want to
   lose as new waypoints (`waypoints.py add "…" [--surface-on YYYY-MM-DD]`). Then **prune** — see below.

   **Pruning is part of the routine reconciliation, not an extra.** `done` leaves an item in the
   LIVE store (hidden from the banner but still loaded, counted and paginated with the open work);
   only `waypoints.py prune` moves the closed pile into the archive. Skip it and the live store
   grows a tail of finished items forever — which is the same defect this skill exists to fix, one
   layer down: a record that is technically accurate and practically in the way.

   ```sh
   waypoints.py prune          # MOVES every done item to the archive; nothing is destroyed
   waypoints.py archive list   # the paper trail, still readable and restorable
   ```

   Prune **after** you have finished marking things done, so one pass sweeps the whole session's
   closures. It is safe by construction: archived items stay readable and `waypoints.py reopen <id>`
   brings one back in one step. If the count looks wrong afterwards, `waypoints.py journal` says
   which command moved what.

   **SOFT DEPENDENCY — probe, never assume.** This skill must work unchanged on a machine that
   does not have waypoints, so do not run any `waypoints.py` command until you have confirmed it
   is there. One check, and no output means not installed → skip step 5 entirely and say nothing
   about it:

   ```sh
   command -v waypoints.py >/dev/null 2>&1 && echo installed
   ```

   Do NOT substitute a hand-edit of `~/.claude/waypoints.json` when the CLI is absent — the file
   is one JSON document, so a botched escape makes EVERY item unreadable at once. No CLI means
   this step does not apply, full stop.
6. **Repos touched this session**: committed and clean? Nothing left uncommitted or accidentally
   pushed to a public surface? For the credential half of that question, run the scanner that ships
   with this plugin — **never hand-roll a `grep`**:

   ```sh
   "$CLAUDE_PLUGIN_ROOT/scripts/redact-secret.py" --scan-only [--explain-filtered] FILE...
   ```

   An improvised pattern (`grep -inE "sk-[A-Za-z0-9]{8}|password|bearer"`) has no word-boundary, no
   shape test and no value test, so it flags `task-specific`, `on-disk-cache`, `--password` as a flag
   *name* and `MAX_OUTPUT_TOKENS=8192` — and a real key hides among them. The scanner applies five
   layers (boundary → vendor shape → entropy → assignment-not-keyword → value sanity), never
   suppresses silently (`--explain-filtered` shows every near-miss and why), writes nothing under
   `--scan-only`, and carries a `--self-test` corpus so its no-false-negative property is verified
   rather than asserted. `password=`/`token=` hits are report-only unless you pass
   `--include-assignments`. It walks no directories: name the files you touched.

### Hybrid discovery (agent-side, here — never in a startup hook)
While reconciling, sweep memories/notes for pending markers (`⏳`, `REMAINING`, `TODO`) that aren't
yet tracked as waypoints and add them. Keep this in the deliberate audit pass, not the startup
banner, so the banner stays precise and false-positive-free.

## Finishing an item

Marking something done means marking it done **in whichever surface holds it** — flip the memory's
flag, tick the note, and `waypoints.py done <id>`. Don't leave the same completion recorded as open in
one place and done in another.

## The point

We never carry stale to-dos or outdated records forward. A future session (or a startup banner)
should re-surface only what's *genuinely* still open.
