# audit-loose-ends

A Claude Code plugin that reconciles your **durable records** at the end of a task or session, so
nothing is left **redundant, orphaned, or falsely flagged as to-do when it's already done**. A
SessionStart nudge keeps the rule in view; a bundled skill holds the full procedure.

## Why

Storing progress isn't enough — the *records* of it drift. A finished task stays flagged "pending"
in a memory; a note describes a plan that already shipped; a follow-up never gets tracked. Left
alone, a future session (or a startup banner) re-surfaces settled ground as if it were open. `audit-loose-ends`
is the recurring end-of-task pass that keeps records honest.

**What changed in 0.9.0**: The wrap-up audit now produces its "clean / not clean" verdict from a deterministic script (`verify-state.py`) instead of model judgement. The script inspects live repo state (git, tests, no-hidden-changes traps) and prints a fixed-format `VERDICT:` block. The model may only *relay* the verdict verbatim — it cannot override it. Harvest-lessons now runs by default (opt-out with `AUDIT_HARVEST=0` or "no harvest").

## What it does

At session start it injects a **model-only** one-line reminder (no user-facing banner). The reminder
fires the reconciliation when:
- you signal a wrap-up — "wrap up", "audit", "tidy up", "close out" — or
- the session **created or changed durable records** (memories, project notes, reminders/crons, the
  task list, or the [`waypoints`](https://github.com/haiggoh/waypoints) store).

It is **not length-based**: a long read-only task needs no audit; a short task that closed a tracked
to-do does. The procedure (in `skills/audit/SKILL.md`) scans each surface, distinguishes a
*historical completion record* (keep) from a *stale pending flag* (fix), marks finished items done
(`waypoints.py done <id> --evidence "commit <sha>, tests N/N"` or `--no-evidence "superseded by <id>"`), prunes the closed pile into the archive, **releases any `waiting`
waypoint whose block is gone**, captures genuinely-open follow-ups as waypoints, and confirms
touched repos are clean.

Pruning and releasing are the same duty in two directions: pruning clears finished work *out* of
the live store, releasing clears a false block *off* unfinished work. `waypoints.py resolve` does
the mechanical half — it releases items whose target is `done` — but it reads the target's done
flag, never the milestone written next to it. So the audit pass also reads `list --waiting` and
judges each milestone by hand, releasing with `triage <id> --clear` when the milestone has landed
even though its target has not. A waypoint parked on a condition that was met is presented as
nothing-to-do while being ready to start, which is worse than a stale done-flag.

### The deterministic verdict gate (`scripts/verify-state.py`)

**New in 0.9.0.** The wrap-up audit no longer relies on model judgement to decide "clean / not clean." Instead, `scripts/verify-state.py` inspects live state and prints a fixed-format `VERDICT:` block with exit code 0 (clean) or 1 (not clean).

```sh
scripts/verify-state.py --repo /path/to/repo                    # check a specific repo
scripts/verify-state.py --session 13043911 --from-scan --repo /tmp  # from audit-scan repos + transcript
scripts/verify-state.py --transcript /path/to/session.jsonl --repo /tmp  # explicit transcript
```

**What it checks (each = one FAIL/WARN/PASS/UNKNOWN line):**

| id | Check | Level |
|---|---|---|
| G1 | conflict markers in tracked files at HEAD and working tree | FAIL |
| G2 | dirty working tree (porcelain count, lists ≤10 paths) | FAIL |
| G3 | branch ahead of / diverged from upstream, or no upstream | FAIL (ahead/diverged) · WARN (no upstream/detached) |
| G4 | in-progress rebase/merge/cherry-pick/revert/bisect | FAIL |
| G5 | version agreement: plugin.json, VERSION, CHANGELOG top heading | FAIL on mismatch |
| G6 | newest local v* tag at HEAD-ancestry has pushed tag + GitHub release | WARN (missing release) · UNKNOWN (gh unavailable) |
| G7 | remote URL embeds credentials (`https://user:token@`) | FAIL, value never printed |
| T1 | transcript: a test command whose LAST run exited ≠0, was killed, or timed out | FAIL — "tests not shown green" |
| H1 | (no-hidden-changes) transcript ran `git add -A`/`--all`/`commit -a` | WARN |
| H2 | (no-hidden-changes) transcript wrote under `~/.claude/plugins/cache/` | FAIL |
| H3 | (no-hidden-changes) transcript force-pushed or moved a pushed tag | FAIL |
| H4 | (no-hidden-changes) new untracked files with no `git check-ignore` hit and no commit | WARN |

H-checks run only when `no-hidden-changes` is detected (reads `installed_plugins.json` + `settings.json`). Env override `AUDIT_NHC=0|1` forces off/on.

**Output format (fixed; tests assert it):**
```
VERIFY-STATE  (read-only)
  repo ~/ClaudeWorkspace/x  [feature/y]
    FAIL G1 conflict markers: CHANGELOG.md:5, CHANGELOG.md:62
    PASS G2 working tree clean
    ...
  transcript
    FAIL T1 tests not shown green: tests/test_session_picker_pty.py (last run killed)
  nhc: detected 1.7.0 (enabled)
    WARN H1 `git add -A` ran in ~/ClaudeWorkspace/local-agents
VERDICT: NOT CLEAN — 3 FAIL, 1 WARN, 0 UNKNOWN
```

**Exit code contract:** 0 = no FAIL; 1 = ≥1 FAIL; 2 = usage error. WARN/UNKNOWN never change exit code.

**From transcript (`--from-scan`):** pass `--session <id>` and `--from-scan`; it runs `audit-scan.py --repos-only --session <id> --all-projects` to discover touched repos and the transcript, then runs the same checks.

**Harvest by default:** Main skill Step 0 runs `audit-scan.py --lessons` always; if N>0 it proceeds into harvest-lessons (budget 3000 tokens ≈ 2 candidates; >15 → asks which categories). Opt-out: "no harvest" or `AUDIT_HARVEST=0`.

### The transcript scan (`scripts/audit-scan.py`)

Step 0 of the procedure, and the reason a long session is affordable to audit at all.

```sh
scripts/audit-scan.py                                # THIS session, identified from CLAUDE_CODE_SESSION_ID
scripts/audit-scan.py --exclude "$CURRENT" --last 3   # skip the live session
scripts/audit-scan.py --all-projects --since 2026-09-01
scripts/audit-scan.py --quote 'waypoints.*done' --budget 3000
```

It streams the raw session JSONL from **outside** and prints a few KB: the durable records modified
grouped by surface (memory / plans / waypoints / CLAUDE.md / settings / hooks / automation), the
waypoints commands run, commits and pushes and tags and releases condensed to repo-plus-subject,
automation that was actually *changed* rather than merely inspected, the task list's end state, and a
**GAPS** section naming what it cannot know. Read-only, and it prints its own compression ratio so
the saving is measured rather than claimed — about **600× on a 4.8 MB transcript**.

**The problem it solves is cost.** The facts a reconciliation needs are a few hundred bytes; the
context they normally arrive in is megabytes. Resuming a 300k-token session to tidy up has cost
several dollars in one go — more than the work being reconciled. So audit a big session the way
`resume-interrupted` recovers one: from a **fresh** session, reading a digest, with nothing of the old
session in context.

What makes it cheap is that Claude Code already records every file it modified as a tiny
`file-history-delta`, so the authoritative answer costs one small record per file version — the
Edit/Write arguments, which are the largest payloads in the file, are never read. And when the digest
raises a question, `--quote` prints just the matching records with line addresses and a hard character
budget, so a follow-up costs what that one thread costs. Paying per question is the economy; loading
the session to answer one is what it avoids.

It is worth running for an **ordinary same-session wrap** too, for a specific reason: after a
compaction your own record of the early session is gone while the transcript's is not, and that early
work is exactly what gets left stale. It locates drift; it never judges it — a changed memory file is
not a correct one, and a commit is not a clean tree. The surface checks still apply.

> Different from [`cc-transcript`](https://github.com/haiggoh/claude-code-transcript-distiller),
> which compacts a transcript for **reading** — a faithful, line-addressable chronology, and the right
> tool when you need the session's reasoning. On that same 4.8 MB transcript it produces a 352 KB
> capsule (~88k tokens, still about a dollar to load). Preservation versus reconciliation: different
> questions, different sizes.

### The secret sweep (`scripts/redact-secret.py`)

"Nothing accidentally public" is the one step in the procedure that used to get answered with an
improvised `grep -inE "sk-[A-Za-z0-9]{8}|password|bearer"`. That pattern has no word boundary, no
shape test and no value test, so it reports `task-specific`, `on-disk-cache`, `--password` as a flag
*name* and `MAX_OUTPUT_TOKENS=8192` — 15 hits, all false, with a real key free to hide among them.
So the scanner ships with the plugin and the skill points at it *at that step*, which is where the
bad habit started:

```sh
"$CLAUDE_PLUGIN_ROOT/scripts/redact-secret.py" --scan-only [--explain-filtered] FILE...
```

Five layers, each chosen so it cannot suppress a real credential:

| | layer | kills | false-negative risk |
|---|---|---|---|
| L1 | left word boundary | `taSK-`, `diSK-`, `aSK-` | none — no key is glued behind a word |
| L2 | documented vendor shapes (`sk-ant-apiNN-`, `sk-proj-`, `ghp_`, `AKIA`, `AIza`, `glpat-`, `hf_`, `xoxb-`, …) | nothing; pure accept | none — and this is what makes L3 safe |
| L3 | entropy gate, **generic `sk-` only**: ≥20 chars and ≥2 of {lower, upper, digit}, or one unbroken ≥32-char run | prose slugs like `sk-prefixed-keys-are-recognizable` | ~(26/62)^40, and such a key already passed L2 |
| L4 | keywords only as `key=value`, never bare | `--password` as a flag name | space-separated `--password foo` is not matched (documented) |
| L5 | value sanity: numeric, known non-secret, `$VAR`/`{{x}}`, path, source ref, placeholder, prose | `MAX_OUTPUT_TOKENS=8192`, `AUTH_TOKEN=local`, `api_key: /path/to/key.txt` | none — these cannot be the secret |

Properties that matter: **suppression is never silent** (every near-miss is counted, and
`--explain-filtered` prints it with its reason); `--scan-only` writes nothing; redaction is
same-length at the same offset so the **inode and mode survive** (safe on a live transcript);
`password=`/`token=` hits are **report-only** unless you pass `--include-assignments`; and it walks
no directories — you name the files. `--self-test` runs a must-match / must-not-match corpus seeded
with the real historical false positives, so "no false negatives" is a property that fails a test
rather than a claim in a README.

The corpus lives in `tests/fixtures/scan-corpus.txt`, not inside the scanner, so sweeping this repo
doesn't keep re-reporting the fixtures' own credential-shaped samples. It is **exempt but visible**:
the file declares itself with a magic first line, the scanner prints
`SKIPPED: declared test corpus (--no-corpus-skip to scan it anyway)` instead of quietly ignoring it,
and a missing or undeclared corpus makes `--self-test` **fail** rather than vacuously pass. `MUST-NOT-MATCH` is
self-policing — anything credible parked there fails the self-test as a false positive.

`MUST-MATCH` holds key **shapes as templates** (`sk-ant-api03-{A:95}`, `AKIA{U:16}`, …) that the
loader expands deterministically, never literal key-shaped runs. That is not cosmetic: **GitHub push
protection rejected this file** when the shapes were literal, reading the synthetic `sk_live_` and
`xoxb-` fixtures as a live Stripe and Slack key. Templates also mean the file cannot physically hold
a leaked credential, and the test suite enforces it — scanning the corpus with `--no-corpus-skip`
must report zero token hits.

## Relationship to the siblings

- **waypoints** — *stores* the open items; `audit-loose-ends` *maintains* that store (one of the surfaces it
  reconciles). waypoints saves; audit checks.
- **no-hidden-changes** — reconciles a *rule* against your setup **once, at first run**; `audit-loose-ends`
  reconciles your *records* **recurringly, at wrap-up**. Same verb family, different trigger + target.
- **resume-interrupted** — recovers an *accidentally* cut-off session; `audit-loose-ends` tidies the records of
  a *deliberately* concluded one.

## Install

```
/plugin marketplace add haiggoh/get-haiggoh
/plugin install audit-loose-ends@haiggoh
```

## Optional / disabling

It's a plugin — disable or uninstall via `/plugin` if you don't want the reminder.

## Tests

```
bash    tests/test_nudge.sh
bash    tests/test_skill.sh
bash    tests/test_redact_secret.sh   # includes a mutation check: removing L1 must break the corpus
python3 tests/test_audit_scan.py     # planted positives for every detector; mutation-tested 21/21
```

## License

MIT — see [LICENSE](LICENSE).
