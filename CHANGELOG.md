# Changelog

## [0.8.1] — 2026-09-25

### Fixed — plugin cache sync for same-version updates

The install path is keyed on the version (`~/.claude/plugins/cache/<owner>/<name>/<version>/`), so a same-version push (v0.8.0 at 11c2ee6 → 639e10d with A1-A3 features) had nowhere new to land and left the installed copy stale. Version bump to 0.8.1 unblocks `claude plugin update` / `get-haiggoh apply`.

## [0.8.0] — 2026-09-24

### Fixed — phantom/doubled paths for shell writes after chained `cd`

The `DURABLE RECORDS WRITTEN BY A SHELL COMMAND` section reported paths that never existed:

- `/Users/bra0002h/.claude/local-session-self-identification.md` (really written in `~/.claude/projects/-Users-bra0002h/memory/`)
- `/Users/bra0002h/.claude/permission-classifier-and-allowlist.md` (same)
- `…/memory/projects/-Users-bra0002h/memory/local-llm-plan-project.md` (and 2 more): a **doubled** prefix.

The command shapes that produced them:
- `cd /Users/bra0002h/.claude/projects/-Users-bra0002h/memory && cat > file <<'EOF'` — resolved against the session's dominant cwd (`~/.claude`) instead of the `cd` target, because the heredoc body was masked before the `cd` was applied.
- `cd /Users/bra0002h/.claude && ... && cd projects/-Users-bra0002h/memory && ...` — a relative path was resolved against a cwd that already included the relative segment, which doubled it.

**Fix:** `_cwd_at_position()` now parses the command prefix up to each write/remove match, applying every `cd` in order. Absolute `cd` resets the base; relative `cd` joins it. Semicolon and `&&` separators both chain cwd updates. A known limitation: subshell scope is not tracked (all `cd` in the masked command apply in order).

Tests: planted fixture transcripts for all four shapes (absolute `cd`, chained `cd`, semicolon, semicolon-chained, relative `cd` after absolute, tilde expansion). Mutation-tested every new assertion. Dogfood-verified on the incident transcript `15e51af4` — all listed paths now exist on disk.

### Added — `memory-index-audit.py` generalized and wired into memory step

New standalone script `scripts/memory-index-audit.py` that:
- Derives the memory directory from cwd (`../projects/*/memory/`) rather than a hardcoded path.
- Accepts `--reviewed <file>` to suppress known stale-description exceptions (the file lists one filename per line; inline `# comments` are stripped).
- Exits 1 on orphans/broken links; `--stale-desc` flags a memory whose body announces a correction not reflected in `MEMORY.md`.
- `--help` exits 0 with usage; unknown flag exits 2.
- Writes nothing; read-only.

Wired into the audit skill's memory step (see SKILL.md changes).

### Added — `audit-scan.py --lessons` deterministic lesson candidate mining

New `--lessons` flag that scans transcripts for five deterministic signals, no LLM calls:
- **correction**: user prompt redirects ("no,", "that's wrong", "actually", "instead", "why did you", "I said", "don't")
- **retry-after-fail**: a tool error followed within ≤3 calls by a DIFFERENT command toward the same target (excludes identical retries)
- **decision**: AskUserQuestion answers (the user's choice plus any free-text note)
- **self-correction**: assistant text containing "CORRECTED", "turned out", "was wrong", "disproved", "false negative", "premise had decayed"
- **schema-error**: tool input validation errors (e.g., "Expected array, got str")

Output: `LESSON CANDIDATES (N)` section with line addresses and ≤160-char excerpts, plus a summary line the main skill reads:
`lessons: N candidates (c corrections, r retries, d decisions, s self-corrections, e schema-errors)`

If N>0, the main skill prints one line at end of pass: "N lesson candidates found — run harvest-lessons? (~N×1.5K budgeted)". Never runs automatically.

Tests: planted fixture transcripts for each signal (positive AND negative — identical retries and code-span "no" must NOT count). Mutation-tested every new assertion.

### Added — `skills/harvest-lessons/SKILL.md` opt-in budgeted sub-skill

Consumes `--lessons` output, fetches context with `--quote` (capped at candidates × budget), promotes validated lessons to the correct layer (CLAUDE.md / memory / rule-governing plugin), writes skill-improvement lessons to task-observer log (soft dependency), checks memory headroom before writing. Includes `--budget`, `--dry-run`, `--categories` flags.

### Added — Local record repos commit step (Step F / Step 7)

New general reconciliation step for durable record directories outside project repos (default: `~/.claude/plans/`):
- **If git repo**: `status --porcelain -z`, `redact-secret.py --scan-only` new/changed files, stage **by path** (never `-A`), commit with summary. No remote, no push. Skip files modified <2 min ago.
- **If not a repo, on FIRST invocation**: explain benefit (49 of 51 deleted plans only in git history), ask via AskUserQuestion: (1) set up now (recommended), (2) snooze, (3) never ask again. Durable choice stored in `~/.claude/.audit-loose-ends/record-repos.json` (visible, not hidden).
- Soft and probe-first: absent `git` → skip silently.

### Added — task-observer activation nudge (E1)

Probe-first line in `hooks/nudge.sh`: if task-observer skill exists (standalone or plugin), append "invoke task-observer before your first substantive tool use" to SessionStart nudge. No new hook registration (reuses existing plugin hook). Silent when skill absent. **Once task-observer ships its own hook (E-upstream), this nudge goes SILENT** when that hook is present — detected by checking installed task-observer plugin for `hooks/hooks.json`.

## [0.7.0] — 2026-09-23

### Fixed — "nothing found" and "nothing I could recognise" no longer render identically

`DURABLE RECORDS MODIFIED (0 file(s))` printed one sentence — *"none recorded — the session changed no
tracked file"* — for two completely different facts: that no write happened at all, or that writes
happened and none named a path the scan recognised. The second is a confession of blindness wearing the
costume of a clean bill of health, and **the calmer the output looked, the worse the coverage was.**

Measured on a real session that **deleted** `/Users/…/AGENTS.md`, a 37 KB always-loaded instruction
file, and was told the session changed no tracked file. A deletion of an always-on rule file is
precisely the change an audit exists to catch. The tool already knew which case it was in
(`saw_shell_write_cmd`); it just did not say so in the section where the reader actually looks, only as
a hint in `GAPS` — and a hint is not a finding.

- **Three distinct absence messages** replace the one unconditional sentence: a real modification
  prints none; a scan that saw write/remove commands but recognised no durable path says
  **"no path RECOGNISED"**, states that this is *a gap in THIS scan, not evidence that nothing
  changed*, and prescribes the `ls -lt`/`find -newermt` cross-check; a genuinely quiet session says
  *"none recorded, and no write or remove command ran either"*.

### Added — removals are mined and reported, in their own section

The write-shaped detectors (`>`, heredoc, `sed -i`, `tee`) **cannot** match a removal: `rm <path>` and
`mv <durable> <elsewhere>` name a durable path while redirecting nothing. Narrower root cause than the
heredoc gap, same failure mode, **opposite severity**.

- New `_SHELL_REMOVE_RES` + `_mine_shell_removes()`, tracked in `shell_removes` **separately from**
  `shell_writes`: "this file was deleted" and "this file was edited" call for different follow-up, and
  conflating them would imply an edit where there is now nothing to audit.
- New report section **`DURABLE RECORDS REMOVED OR MOVED AWAY BY A SHELL COMMAND`**, flagged ⚠️ because
  a deleted record cannot be audited later. `GAPS` adds whether those paths are gone *now* — a later
  step may have restored them.
- The surface filter is factored into `_durable_target()` and shared by both miners, so they cannot
  diverge into one reporting scratch files while the other stays quiet.
- **A fourth absence message, found by the pre-merge dogfood itself:** when a removal *was* recognised,
  claiming "no path RECOGNISED" contradicts the REMOVED section printed directly below it and points the
  reader at the wrong worry. That case now reads *"nothing MODIFIED — but see REMOVED below: this
  session's durable change was a deletion, not an edit."* Worth recording because it is the argument for
  dogfooding before merging rather than after: five mutation-tested assertions and five green suites did
  not surface it — running the thing on the real incident did, in one read.

### Added — a credential can land in the TRANSCRIPT, not only in a file

`redact-secret.py` scans files you can name; it cannot reach a secret that was **printed**. So the
skill's step 6 now covers it: an endpoint can hand back the credential — `ttyd`'s `/token` returns the
basic-auth pair **base64-encoded**, so printing that body publishes the password. It leaked exactly
that way once while a public tunnel was live and had to be rotated. Base64 is what makes it survive a
glance: it does not read as a secret, and a shape-based scanner will not flag it either. Treat any
`/token`, `/session`, `/whoami` or `/debug` route as credential-bearing, and **test auth by STATUS,
never by content** (`curl -o /dev/null -w '%{http_code}'`).

### Testing

`tests/test_audit_scan.py` +16 assertions (planted positive **and** rejected negative for each, per
this suite's standing convention); `tests/test_skill.sh` +5. Every new property was
**mutation-tested**: reverting the absence fix, dropping the REMOVED section, disabling the removal
miner, letting removals leak into writes, dropping the `/tmp` surface filter, and collapsing the recognised-removal branch each fail
the suite (6/6 caught); the five skill assertions likewise fail when the guidance is weakened (5/5 caught).
The new tests are inserted **before** the file's summary block, since this suite ends in a
`SystemExit` and anything appended after it would never run while the suite still printed green.

One honest residual, documented in the fixture: a path named only inside a **heredoc body** is
traceless — prose-masking strips the body, so no write construct survives and the scan falls through to
the quiet message. That is why the `ls -lt` cross-check remains prescribed rather than deprecated.

## [0.6.1] — 2026-09-21

### Fixed — waypoints 0.10.0 evidence gate compatibility

The waypoints plugin 0.10.0 introduced an **evidence gate** requiring `--evidence` or `--no-evidence`
when closing an item with `waypoints.py done <id>`. The audit procedure and nudge still taught the
old bare `waypoints.py done <id>` syntax, which now fails with exit code 2.

- Updated the SessionStart hook nudge (`hooks/nudge.sh`) to show the correct syntax:
  `waypoints.py done <id> --evidence "commit <sha>, tests N/N"` or `--no-evidence "superseded by <id>"`
- Updated the audit skill (`skills/audit-loose-ends/SKILL.md`) in two locations
- Updated `README.md` project overview
- Updated `tests/test_nudge.sh` to assert the new syntax
- Fixed a bash command substitution bug in `hooks/nudge.sh` where backticks in the heredoc were
  being interpreted as command substitution; now uses a proper heredoc with resolved paths

### Testing

- All existing tests pass (test_nudge.sh, test_skill.sh, test_redact_secret.sh, test_audit_scan.py)
- waypoints plugin's own evidence gate tests (28 tests) all pass

## [0.6.0] — 2026-09-20

### Fixed — the scan audited the wrong session, and said nothing about it

`audit-scan.py` selected its target with two heuristics that are both wrong for an agent session:

- the project directory came from `os.getcwd()`, but a transcript lives under the directory the session was **launched** in — and cwd drifts as a session moves between repos;
- candidates were then ordered by **file mtime**, so a ten-second nested `claude -p` probe outranked a thousand-record real session.

Measured: `--last 1` selected a 42-record child transcript over the live 1216-record session, reported "changed no tracked file", and would have certified a clean wrap for a session that had just cut three releases. **A clean bill for the wrong subject is worse than no check** — it is indistinguishable from a tidy wrap.

- **The default now identifies this session from `CLAUDE_CODE_SESSION_ID`**, which Claude Code exports into the Bash tool environment, and looks for `<id>.jsonl` across every project dir. That is an identity, not a guess. Self-identification applies only when no target was named: `--file`, `--session`, `--project`, `--all-projects`, `--since`, `--exclude`, and `--last N>1` all behave exactly as before, and the old cwd+mtime path remains the fallback when the variable is absent.
- **Added a wrong-subject warning.** When our own session id is known and is *absent* from the transcript being reported, the digest header says `⚠️ NOT THIS SESSION` with the current id. Selection can still be heuristic, so the remaining risk is made loud instead of silent. Nothing is invented when the id is unknown.

### Changed

- The nudge, `SKILL.md` and `README.md` now teach the bare invocation. They previously taught `--last 1`, which from this version onward *opts out* of self-identification and back into mtime ordering.

### Testing

- 10 new assertions in `tests/test_audit_scan.py`. The fixture deliberately gives the **wrong** transcript the **newer** mtime and puts the right one in a different project dir — a fixture where the correct answer is also the newest would pass against the broken code and prove nothing. Covers id lookup across dirs, the default, each override, the no-env fallback, and the warning firing *and* staying silent.
- Inserted **before** the summary: this suite ends in `SystemExit`, so appended cases would never run while the total still printed `ALL PASS`.
- Mutation-tested, both caught: removing self-identification fails an assertion; removing the warning fails an assertion. `scripts/audit-scan.py` restored to its exact pre-mutation shasum.

## [0.5.7] — 2026-09-18

### Added — skill observations as a reconciliation surface

- The audit procedure now scans `~/.claude/projects/<project>/skill-observations/` for stale OPEN
  entries: action them, or mark them ACTIONED/DECLINED with a date, and archive anything past 90
  days. An observation log is exactly the surface this plugin exists to reconcile — entries
  accumulate as OPEN because nothing ever revisits them. Treated as a SOFT dependency like the
  waypoints store: absent directory means skip the step silently.
- The step is documented as reviewing *proposals*, not authoritative state, so promoting one into
  a durable rule stays approval-gated rather than something the audit does on its own.

### Internal

- `tests/test_version_consistency.sh` asserts the manifest and the CHANGELOG's newest released
  heading agree, and that the heading has at least one bullet — a bump with no entry of its own
  was the specific way this drifted before.

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
