# Changelog

## [0.5.6] — 2026-09-10

### Fixed — the scanner was blind to records written by the shell

MEASURED 2026-09-08: `audit-scan.py --last 1` reported **1** memory file modified for a session that
modified **3**. The two it missed were written by a heredoc and by `sed -i`; the one it caught used
the Write tool. Neither shell form produces a `file-history-delta` or a `Write`/`Edit` record, so
they were invisible — and a short `DURABLE RECORDS` list reads as *"nothing changed"* when it
actually means *"nothing changed through a tool I parse"*.

That inverts this tool's whole premise. The scan is documented as being right about what happened
while recollection is lossy; here recollection was right and the digest was wrong. It also bites
hardest exactly where it is used most: an auto-mode session is *instructed* to prefer `sed`/heredoc
over the Edit tool, so the sessions most likely to be audited this way were the ones it was
blindest on.

- Write targets are now mined from Bash command strings — `>`/`>>`, heredoc redirects, `tee`,
  `sed -i`/`perl -i`, and `mv`/`cp`/`install` onto a path — and reported under
  **`DURABLE RECORDS WRITTEN BY A SHELL COMMAND`**, a deliberately SEPARATE lower-confidence
  section. A path in a command is weaker evidence than a delta record (the command may have failed
  or been a dry run), so merging the two would trade this false negative for a false positive in
  the one section the audit acts on. A file with a real delta record is never double-reported.
- Mined from the prose-MASKED command, so a path quoted inside a commit message is not counted as
  a write, and filtered to durable surfaces — with temp dirs excluded, because `> /tmp/x.txt`
  matches the `docs` glob (`*.txt`) and is the commonest redirect in any session.

### Fixed — GAPS printed a generic disclaimer instead of naming what it saw

Second defect from the same run: GAPS printed *"anything from a file written by a shell redirect"*
**unconditionally**, including on the very session that had three such files. GAPS is the mechanism
that names what the tool cannot know, so it now reports the specific uncertainty — how many
shell-written paths were found and that no delta confirms the write landed — and keeps the generic
line only when no write-shaped command appeared at all.

### Fixed — a relative path resolved against the wrong cwd, inventing a path

Found by DOGFOODING the fix on the session that wrote it: the digest named
`cost-tracker/scripts/audit-scan.py`, a file in neither repo, because relative paths were resolved
against the session's *most common* cwd rather than the one in effect at that record. A session that
moves between repos gets a path that never existed — worse than no path, since it sends the reader
to audit a file that is not there. Now tracked per record.

Tests: 15 new checks (6 planted positives, 6 noise negatives, plus double-reporting, both GAPS
branches, and the cwd case) in the repo's framework-free style, mutation-tested **5/5** — removing
the miner, dropping the redirect pattern, merging the two confidence levels, reverting GAPS to the
unconditional line, and restoring the dominant-cwd resolution are each caught. The skill now
documents both sections, how to read them differently, and the residual blind spot: a path named
only *inside* a heredoc body is still undetected, so `ls -lt` over the records dir remains the
cross-check.

## [0.5.5] — 2026-09-07

### Fixed
- **The match window is now placed BEFORE the subject marker.** `condense()` cuts the stored value at
  that marker, so the window appended after it was never read — 0.5.3 and 0.5.4 both looked applied
  and a real ship one-liner still displayed its head. Both earlier fixtures happened to contain no
  commit, so nothing in the suite exercised the combination; the test now covers a late match *and* a
  commit subject in the same command, which is the shape every ship command in this repo has.

  Worth naming as a pattern rather than a one-off: three consecutive releases fixed a real cause of
  the same visible symptom, and each fix was verified against a fixture that isolated it. Isolating
  the cause is what let the next cause hide. What finally settled it was reproducing the digest's own
  offending line from the transcript and reading the stored value directly, rather than adding one
  more fixture.

## [0.5.4] — 2026-09-07

### Fixed
- **The match is now located BEFORE the command text is flattened.** The anchor accepts a newline as
  a command position, so flattening first removes the very character that makes a match possible.
  That silently undid 0.5.3 for any command whose operative call *began a line* rather than following
  an `&&` — including the shape that motivated 0.5.3 in the first place, a ship one-liner whose
  `claude plugin update` sat on a later line. It was still displaying the head, and the fix looked
  applied because the commands that happened to use `&&` had started rendering correctly.

### Tests
- A newline-anchored fixture, alongside the `&&` one. Mutation-tested: flattening before the search
  is caught. A third candidate fix — stripping a leading newline from the fragment — turned out to be
  dead code, since `split()` already drops it; removed rather than papered over with a test that
  would have passed either way.

## [0.5.3] — 2026-09-07

### Fixed
- **The retained slice of a command is now guaranteed to contain the match.** Third and last facet
  of the truncation defect: 0.5.2 displays a raw-kept command from its match, but a long one-liner
  can push the matching call past the retention cap, and with nothing left to match the display fell
  back to the head — so a `claude plugin update` entry showed the `python3 - <<PY` that opened the
  same line, exactly the misattribution 0.5.2 set out to remove. The head is still kept, because
  that is where the leading `cd` and therefore the repo name come from; a window around the match is
  appended to it.

### Tests
- The first version of this test was padded with a heredoc, and heredoc bodies are stripped *before*
  the cap applies — so the fixture never exceeded it and the test passed without exercising the fix
  at all (the mutation came back NOT CAUGHT and was right to). It now pads with real shell code and
  asserts up front that the match really does land past the cap. 4 assertions, mutation-tested 2/2.

## [0.5.2] — 2026-09-07

### Fixed
- **A raw-kept command is now shown from the MATCH, not from the head of the line.** The sections
  the audit is meant to trust most — plugin installs, automation changes, destructive commands,
  waypoints calls — print the command text itself, and a shell one-liner routinely carries the
  operative call last. So `claude plugin update audit-loose-ends` appeared under the
  `git add … && git commit …` that happened to open the same line, and a destructive entry showed a
  `mktemp` where the reader was looking for the `rm`. Unlike 0.5.1's defects the *entry* was true;
  the evidence printed beneath it belonged to a different command, which is its own way of being
  wrong — a reader checking the digest against the session finds them disagreeing. The fragment is
  marked `… ` so it is visibly mid-command, steps over the operator the anchor matched (otherwise
  every entry reads `… && claude plugin update`), and is still capped.

### Tests
- 6 new assertions, mutation-tested 4/4. The operator step-over needed an exact-equality assertion
  to be caught at all: an `in` check on the command still passed with the `&&` left on the front.

## [0.5.1] — 2026-09-07

### Fixed
Four defects in `audit-scan.py`, all four found by dogfooding 0.5.0 — running the finished scanner
on the very session that built it. Each one **fabricated** a fact rather than missing one, which in
an audit is the worse failure: nothing in the digest tells a reader that an entry was invented.

- **Prose in a quoted argument was read as shell code.** 0.5.0 stripped heredoc bodies, but the same
  prose also arrives as `gh release create --notes "…"`, whose body is a changelog *describing the
  commands being detected*. Because the start of a line counts as a command position, a changelog
  line beginning `claude plugin update …` was reported as a plugin update that ran. `shell_only` now
  also masks multi-line quoted data, quote-aware: `$( )` inside quotes is live code and is followed
  as such, and a data region is blanked segment by segment — the runs between its quotes and any
  substitution inside it — so `--notes "$(cmd "prose")"` loses the prose and keeps the `$(cmd`.
  Same-line arguments are left alone; an unterminated quote treats the remainder as data, which
  under-detects in data rather than over-detecting prose as commands.
- **A long commit message truncated away the commands that followed it.** The *raw* command was
  stored, so a 40-line message consumed the retention budget and the `git push` / `git tag` /
  `gh release` after it were cut off — the digest printed `push` with no target and `tag ?` with no
  version. What is stored is now the shell code, with the subject carried explicitly beside it.
- **`git tag` with no operand is a listing.** `git tag | tail` changes nothing, yet it was reported
  as a tag creation with `|` as the tag name. A tag operand is now required, and the listing is
  counted as read-only git.
- **`cd ~/ClaudeWorkspace;` produced the repo name `ClaudeWorkspace;`** — trailing shell punctuation
  is now stripped.

Found while fixing the above: `GIT_READONLY` carried a trailing `\b` on the whole alternation, so
every alternative ending at `$` or a shell operator could never match — `git tag` and `git branch`
were silently uncounted. Boundary placement, not vocabulary, and invisible in a passing suite
because a read-only tally that is too low looks like a quiet session.

### Tests
- 15 new assertions covering all of the above, and **mutation-tested 11/11** on the new paths. Two
  of those mutations initially came back NOT CAUGHT and both were the tests' fault, not the
  mutations': one asserted `SUBJ_MARK not in output` when the marker begins with a newline, so
  flattening the value passed it trivially; the other exercised only the closing half of a
  two-sided rule. The `$( )` segment split is now tested from **both** sides — prose before the
  substitution and prose after it — because either half alone leaves the false positive intact.

## [0.5.0] — 2026-09-07

### Added
- **`scripts/audit-scan.py` — reconcile a session by scanning its transcript instead of resuming
  it.** The facts this pass needs are a few hundred bytes; the context they normally arrive in is
  megabytes. Reloading a 300k-token session to tidy up has cost several dollars in one go, which is
  more than the work being reconciled — so the audit now starts from a digest read from **outside**
  the transcript, in a fresh cheap session, the way `resume-interrupted` recovers one.
  - Emits, in a few KB: durable records modified **grouped by surface** (memory / plans / waypoints /
    CLAUDE.md / settings / hooks / automation / scripts / skills), the waypoints commands run,
    commits / pushes / tags / releases condensed to repo-plus-subject, automation that was actually
    **changed** rather than merely inspected, the task list's end state, and a **GAPS** section
    naming what it cannot determine.
  - **What makes it cheap:** Claude Code already records every modified file as a tiny
    `file-history-delta` carrying just a path, so the authoritative answer costs one small record
    per file version and the Edit/Write arguments — the largest payloads in the file, and the reason
    a naive scan would cost as much as the thing it replaces — are never read.
  - **`--quote REGEX --budget N`** is the other half: matching records only, with line addresses and
    a hard character cap. The digest is deliberately too terse to answer follow-ups, so without a
    targeted way to go deeper the only option would be loading the session. Paying per question is
    the economy.
  - Reports its **own compression ratio**, so the saving is measured rather than asserted: ~600× on
    a 4.8 MB transcript.
  - Selection: `--last N`, `--session`, `--project`, `--all-projects`, `--since`, and `--exclude` for
    skipping the live session, which has not finished and so cannot be reconciled yet. `--json` for
    the unabridged facts, `--list` to see what would be scanned. Read-only in every mode, asserted
    by a byte-comparison test.
  - Quoted text is scrubbed through the plugin's **own** `redact-secret.py` rather than a
    hand-rolled pattern, and a redactor that fails to load or errors is reported as UNAVAILABLE /
    fails closed — never silently skipped.
- **Step 0 in the skill, and it applies to an ordinary wrap too.** Not only the expensive case: after
  a compaction your own record of the early session is gone while the transcript's is not, and that
  early work is exactly what gets left stale. Recall is also lossy in the direction that matters — it
  favours what was recent and interesting, while the audit needs what was *touched*. The rule: run it
  unless the session is short enough to name every file you changed.
- The skill and README state plainly what the scan does **not** do: it locates drift without judging
  it. A changed memory file is not a correct one; a commit is not a clean tree. Steps 1–6 still do
  the looking. The README also documents why this is not
  [`cc-transcript`](https://github.com/haiggoh/claude-code-transcript-distiller) — measured, not
  assumed: that distiller turns the same 4.8 MB transcript into a 352 KB capsule (~88k tokens), which
  is the right artifact for reading a session and the wrong one for reconciling it.

### Tests
- `tests/test_audit_scan.py` — framework-free, no pytest. Every detector is tested against a
  **planted positive** as well as its negative, because during development three detectors "passed"
  by finding nothing: a heredoc-stripping fix silently removed the real `launchctl` calls along with
  the false ones and the digest looked *cleaner* for it. A detector that cannot be shown to fire is
  indistinguishable from a broken one.
- Mutation-tested **21/21**. The sweep additionally exposed four tests that were asserting nothing:
  a fixture that placed the planted string where an anchor rejected it anyway, a size check that
  passed via a different cap, an assertion that compared a truncation against the very constant that
  produced it, and a fixture helper that ran `json.dumps` over its own deliberately-malformed lines
  and thereby made them valid. All four are fixed and now fail when the behaviour is removed.
- Bugs the tests caught and now pin: `realParentDir` + `trackingPath` were joined into a doubled
  path so no file matched its own tool call; macOS's `/tmp` → `/private/tmp` symlink made one file
  appear as two; `Read` was counted as a file change; `redact-secret`'s `DEFAULT_PATTERN` is raw
  **bytes** and passing it uncompiled made every quoted line come out `[REDACTION FAILED]` — safe,
  silent and useless.

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
