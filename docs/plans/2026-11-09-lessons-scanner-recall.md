# Execution plan — audit-scan.py `--lessons`: RECALL first, then precision (audit-loose-ends 0.13.13)

> **For the executor:** run this with `superpowers:executing-plans` (native — you do every task
> yourself, one final review). Autopilot mode: `run-to-completion:execute-unattended` rules apply —
> no stopping between tasks, decide-and-record, stop only at the authority boundary below.
> **Written:** 2026-11-09 ~02:00 CET by a cloud Opus 5.5 session. **Executor:** free session, Mistral
> Large 4 "Le Chonk" (NVIDIA), effort max. **Worktree:** `~/ClaudeWorkspace/.wt/ale-lessons-recall`,
> branch `feat/lessons-recall`, from `origin/main` 485c229 (v0.13.12).
> **Waypoint:** 🧭 `audit-scan-classifier-hardening` (`waypoints.py show audit-scan-classifier-hardening`).

## 🚨 System instructions for the executor — read first

1. This plan is self-contained. Do not depend on any previous chat. Re-verify every "confirmed live"
   fact below with its probe before you rely on it — they were true at 02:00 CET 2026-11-09.
2. Before the first file edit, write exactly THREE strategy sentences linking Task 1 to the final
   outcome. Then do Phase 0 (read-only). No edits before Receipt 0 exists.
3. Use native Read/Grep/Glob/Edit/Write for files; the shell only for git, tests, running scripts.
   Edit anchors come from a FRESH Read, whole lines at exact indentation. Never rewrite a file from a
   fragment. On a tool-schema error, read the schema; never re-guess.
4. Work ONLY in this worktree. Never switch the branch of `~/ClaudeWorkspace/audit-loose-ends` (other
   tooling resolves through it, and rtc-ship requires it on `main`). Never touch
   `~/ClaudeWorkspace/.wt/ale-index-limit` or `~/ClaudeWorkspace/.wt/audit-loose-ends-additive`
   (stale, unmerged, not yours).
5. TDD every behaviour: the test first, watch it fail FOR THE RIGHT REASON, then the code. Each new
   detector also needs a planted NEGATIVE that must stay silent. Mutation-check each new predicate
   (temporarily break it, confirm red, restore from git). Never weaken a test to get green.
6. Commit at every task end, staged BY PATH (never `git add -A`/`.`), confirm with
   `git diff --cached --stat`. Trailers, exactly (check your real model identity first; if you are
   not Le Chonk, use your own model's trailer from memory `commit-attribution-by-model`):
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
   `Co-Authored-By: Mistral Large 4 "Le Chonk" 1T-A52B <noreply@mistral.ai>`
7. Append one line to §8 Progress log at each task end, in that task's commit.
8. Review each task with an independent stateless dispatch (`python3
   ~/ClaudeWorkspace/free-agents/bin/free-agent-tool.py`, stdin JSON `{"prompt":…,"files":[diff
   file],"role":"validator"}`, save with `--out FILE` — free-agents ≥0.55.6 writes the full envelope).
   Check every finding against the real code; reviewers invent file names. Record verdicts in §8.
9. Never kill, restart or `--stop` anything on ports 4141–4151 or 8000–8010; never start another
   session; never `pkill`. You may run `la-evict.sh --orphans` (or `--tier 0`) at any time.
10. Never print process argv (`ps aux`, `pgrep -fl`) or secret values. Write home paths as `~`/`$HOME`.
11. **Highest granted boundary: release.** Via `rtc-ship.sh` only — merge to `main`, tag `v0.13.13`,
    GitHub release, plugin refresh, dogfood. Never force-push, never move a published tag; a broken
    release is fixed forward as 0.13.14.
12. You are the final executor. Never hand this off to another session.

## 📌 Context and objectives

**Project:** audit-loose-ends (haiggoh), the end-of-task reconciliation plugin. Source repo
`~/ClaudeWorkspace/audit-loose-ends` (confirmed live; NOT the plugin cache
`~/.claude/plugins/cache/haiggoh/audit-loose-ends/…`, which is a derived copy — never edit it).
Target file: `scripts/audit-scan.py`, function `_extract_lesson_candidates` (≈ line 1464) and the
predicates above it (≈ 1282–1416); self-test corpus `tests/fixtures/lessons-corpus.txt` and record
scenarios `tests/fixtures/lessons-scenarios/*.jsonl`; tests `tests/test_audit_scan.py`.

**The problem (user, 2026-11-09, verbatim):** *"'Every lesson here was found by hand, not by the
scanner.' that in and of itself could be a lesson, maybe we need to improve our scanner"*.

**Evidence (each labelled):**

- *Confirmed live 2026-11-09:* on session `af94571f-28bf-4b05-9085-7b84abe907d9`
  (`~/.claude/projects/-Users-bra0002h/<id>.jsonl`), `audit-scan.py --lessons` reported 2 candidates,
  both FALSE (line 25 = a pasted transcript tail as the user's first prompt; line 511 = an injected
  skill body). Retries, decisions, self-corrections, schema errors: 0. The 5 real lessons were found by
  hand: validator/producer envelope mismatch (tool error at line 572, then a changed approach);
  git commit "nothing staged" (line 161) then retry with the index's path case; a watch-your-step
  hook BLOCK (line 95); an assistant self-correction "That landed on the wrong waypoint" (line 1054);
  the AskUserQuestion answer record (line 830).
- *Confirmed live — ROOT CAUSE of the structural classes:* sections 3 and 5 of
  `_extract_lesson_candidates` only look at TOP-LEVEL records with `type == "tool_result"`. Real
  transcripts never contain that shape: af94571f has **0** top-level tool_result records and **153**
  `tool_result` BLOCKS inside `user` records (4 with `is_error`); a sweep of 400 real transcripts found
  0 files with the top-level shape. The fixtures `lessons-scenarios/retry-after-fail.jsonl` and
  `decision.jsonl` use ONLY the top-level shape, so `--self-test` is green while both classes are inert
  on every real session. (`_errored_tool_results` at ≈1417 already handles the block shape — reuse it.)
  Probe: the python snippet in Phase 0 step 4.
- *Dated observation (2026-11-08, obs 0098 recurrence):* a session's best correction lived in an
  AskUserQuestion answer's `notes`; the scanner never reads answers or notes.
- *Waypoint points already recorded (read them with `waypoints.py show`):* 0070 self-quotation noise;
  0087 partial-agreement corrections; 0063 unbacked "tracked on waypoints" claims; 0098 skill-injection
  + pasted-text false positives; plus the 2026-11-09 RECALL leads.
- *Unknown to inspect:* "skill-text halves already staged 2026-11-06 under
  skill-updates/2026-11-06/{audit-loose-ends,harvest-lessons}" — locate it (likely under
  `~/.claude/skill-observations/`); if not found in 5 minutes, record "not found" and move on.

**Acceptance criteria (observable):**

1. On a fixture in the REAL record shape, retry-after-fail and decision fire; on the legacy shape they
   still fire (compatibility).
2. AskUserQuestion answers AND notes enter the user-text pool (correction + decision).
3. Skill-injection records and pasted-transcript user turns no longer fire CORRECTION (planted MUSTNOTs).
4. Hook/permission denials surface as candidates (new class `guard-block`, in the summary line).
5. Widened self-correction phrases fire; their MUSTNOT twins stay silent.
6. GAPS prints `RECALL GAP` when the session wrote lesson-shaped memory/observation files but the
   scanner found 0 overlapping candidates.
7. A golden recall scenario (synthetic, modelled on af94571f — §Task 7) yields ≥4/5 real lessons and
   0 of its 2 false positives; `--self-test` fails if not.
8. Dogfood: the INSTALLED 0.13.13 `audit-scan.py --lessons` on the real af94571f transcript reports
   ≥4 of the 5 lessons above and NOT lines 25/511.
**Deferred unless time remains (record which):** 0063 unbacked-tracking claims (Task 8).

**Non-goals:** no LLM calls inside audit-scan (it stays deterministic and offline); no change to the
durable-records digest outside the lessons/GAPS sections; no CLAUDE.md edits.

## 🔒 Authority matrix

| Operation | Status | Gate / evidence |
|---|---|---|
| Read anything under `~/.claude/projects/*.jsonl`, the repo, memory | allowed now | read-only |
| Edit files in this worktree | allowed now | Phase 0 done |
| Commit on `feat/lessons-recall`, push it | allowed now | task receipt green |
| Copy REAL transcript lines into fixtures | **prohibited** | synthesize records instead (privacy, secrets) |
| `rtc-ship.sh` → merge `main`, tag `v0.13.13`, release, refresh | allowed after gate | Task 9 receipts: full suite green on THIS tree, `--versions-only` green, redact scan clean |
| Edit observation files `0098`/`0070`/`0087`/`0063` frontmatter only | allowed after release | dogfood receipt |
| `waypoints.py done audit-scan-classifier-hardening` | allowed after dogfood | evidence = release URL + counts |
| Edit memory files / MEMORY.md / CLAUDE.md | **prohibited** | report proposals instead |
| Force-push, move a tag, delete branches/worktrees, kill processes | **prohibited** | — |

## 🛑 Phase 0 — forced preflight (read-only)

1. Three strategy sentences (instruction 2).
2. `git -C ~/ClaudeWorkspace/.wt/ale-lessons-recall status --porcelain` (expect only this plan file
   committed — clean); `git log --oneline -2`; `git -C ~/ClaudeWorkspace/audit-loose-ends branch
   --show-current` (expect `main`) and `status --porcelain` (expect empty).
3. Baseline: the repo's own test command from `rtc-ship.json` `test_cmd`, run from the worktree:
   `{ echo 'python3 tests/test_audit_scan.py'; for t in tests/test_*.sh; do echo "bash $t"; done; } |
   parallel --will-cite -j 12; echo "exit=$?"`. Record pass/fail counts. Run it in the background and
   check `ps -o pid,stat,%cpu,etime -p <pid>` after 3 minutes: 0% CPU and no new output = wedged → kill
   only your own pids and run each suite alone.
4. Re-prove the root cause on the live transcript:
   `python3 -I -c 'import json,sys,collections; c=collections.Counter(); b=0
   for l in open(sys.argv[1]):
       d=json.loads(l); c[d.get("type")]+=1; m=d.get("message") or {}
       b+=sum(1 for x in (m.get("content") if isinstance(m,dict) and isinstance(m.get("content"),list) else []) if isinstance(x,dict) and x.get("type")=="tool_result")
   print("top-level:", c["tool_result"], "blocks:", b)' ~/.claude/projects/-Users-bra0002h/af94571f-28bf-4b05-9085-7b84abe907d9.jsonl`
   (expect top-level 0, blocks ≈153).
5. Baseline lessons: `python3 scripts/audit-scan.py --lessons <that transcript> 2>&1 | sed -n
   '/LESSON CANDIDATES/,$p'` — check `--help` for how to pass a path. Expect 2 candidates (lines 25,
   511). `python3 scripts/audit-scan.py --self-test; echo $?` (expect 0).
6. Read one REAL `user` record holding a tool_result block, one assistant `tool_use` record, and the
   AskUserQuestion answer record (line 830) from that transcript to learn the exact keys
   (`tool_use_id`, `is_error`, the answers/annotations layout). Write the observed shapes into §8.

**🧪 Receipt 0:** outputs of 2–6, the baseline counts, and the observed record shapes.

## Tasks (each ends with a discriminant + receipt + commit + §8 line)

**Task 1 — structural classes read the REAL shape.** Pair each assistant `tool_use` (id, name, input)
with its `tool_result` block (by `tool_use_id`) inside the following `user` record; treat
`is_error: true` as the failure signal. Retry-after-fail = a failed result followed within the next 3
tool calls by a call to the same tool on the same target with a different input (Bash target = first
word AND, for git, the subcommand; Edit/Write target = file_path). Keep the legacy top-level path.
New fixtures `lessons-scenarios/retry-after-fail--block-shape.jsonl` and `decision--block-shape.jsonl`
(synthetic). *Discriminant:* run the new fixtures against the UNMODIFIED code first → they must fail
(this is the proof the old self-test was inert); then green. Also a MUSTNOT scenario: a failed call
followed by an UNRELATED call stays silent.

**Task 2 — AskUserQuestion answers and notes are user text.** Extract the answer text and any
`notes`/annotations from the tool_result block of an AskUserQuestion call; feed it to the correction
pool and emit a `decision` candidate. Fixture with a note that is a correction ("look again, several
of those do have menus") → fires correction; a plain option pick → decision only.

**Task 3 — precision: skill bodies and pasted transcripts.** Skip user text that starts with
`Base directory for this skill:` and Skill tool results. Down-weight a user turn that is mostly
pasted assistant output (e.g. ≥60 % of its non-empty lines indented ≥2 spaces or containing box-drawing
characters `⏺ ✻ ─ ❯`) — decide the exact heuristic, record why, keep it conservative. MUSTNOT lines in
`lessons-corpus.txt` for both shapes, plus waypoint point 0070 (a record containing `re.compile(` or a
`_LESSON_` identifier) and MUST lines for 0087 partial agreement (`except for`, `agree with everything
except`, `I'd (much) rather`).

**Task 4 — `guard-block` class.** A tool_result block whose text matches a hook/permission denial
(`PreToolUse:` … `hook error`, `BLOCKED`, `permission denied by rule`, the harness's permission-denied
wording — inspect real examples with Grep across `~/.claude/projects/*/*.jsonl`, never print secrets)
is a candidate. Add to `_LESSON_ALL_CLASSES`, the summary line, `--self-test`, and README/SKILL text.

**Task 5 — wider self-corrections.** Phrases: `landed on the wrong`, `that'?s (a|my) (mistake|bug)`,
`the cause was`, `root cause`, `looks wrong`, `false (negative|positive)`, `re-?extract`. Keep the
owned-failure pairing idea where it prevents noise; MUSTNOT twins (e.g. "the root cause analysis
section of the README" in neutral prose).

**Task 6 — RECALL GAP in GAPS.** If the session's durable writes include lesson-shaped files
(memory dir `*.md` appends, `skill-observations/observation-log/*.md`, a playbook "Pitfalls" edit) and
the lessons pass found 0 candidates within ±50 records of those writes, print
`RECALL GAP: N lesson-shaped write(s), 0 candidates near them — harvest by hand`. Fixture both ways.

**Task 7 — golden recall scenario.** `lessons-scenarios/golden--recall-af94571f.jsonl`: SYNTHETIC
records reproducing the 5 lesson shapes and the 2 false-positive shapes from the evidence list (no
real text copied; neutral placeholder paths). `--self-test` asserts ≥4/5 fire with the right classes and
both false positives stay silent. Run `scripts/redact-secret.py --scan-only` on every new fixture.

**Task 8 (deferrable) — waypoint point 0063.** GAPS flags assistant text matching
`tracked on|on waypoints` with no `waypoints.py add|edit` in the session. Do it if Tasks 1–7 are green
with time left; else record "deferred" in §8 and add it as a point on the waypoint.

**Task 9 — docs, version, gates.** CHANGELOG `## [0.13.13] — <date>` (match the 0.13.12 entry
style): Fixed (structural classes inert on real transcripts — say it plainly), Added (AskUserQuestion
answers, guard-block, RECALL GAP, golden recall scenario), Changed (precision filters). README/SKILL
lines that state class counts. `rtc-ship.sh --bump-versions . 0.13.13` then
`rtc-ship.sh --versions-only .` green. Full suite (Phase 0 step 3 command) green on THIS tree;
`python3 scripts/audit-scan.py --self-test` exit 0. Independent validator dispatch over the whole
branch diff; resolve each finding.

**Task 10 — ship and dogfood.** Read `rtc-ship.sh --help` first. Run it from this worktree. If its
test phase wedges (0% CPU), kill only its pids and re-run with `RTC_SKIP_TESTS=1` — ONLY with the
Task 9 green run of the SAME tree recorded in §8. After the tag: confirm the update is visible
(`get-haiggoh plan`; re-check once after ~60 s if negative), let rtc-ship refresh, then DOGFOOD with the
INSTALLED copy (`ls -d ~/.claude/plugins/cache/haiggoh/audit-loose-ends/*/ | sort -V | tail -1`):
`--lessons` on the real af94571f transcript (acceptance 8) and `--self-test`. Then: frontmatter-resolve
obs 0098 (and 0070/0087/0063 for what shipped) with `resolution:` naming v0.13.13; `waypoints.py done
audit-scan-classifier-hardening --evidence "v0.13.13 <release URL>; self-test N/N; dogfood af94571f:
K/5 lessons, lines 25/511 silent"` — or, if anything was deferred, `edit --point` the remainder instead
of closing.

## 🧨 Adversarial review

- Fix the fixtures to match the code → self-test green → classes still dead on real sessions → rule:
  new fixtures must be in the REAL shape and must FAIL on the unmodified code first → Task 1
  discriminant receipt.
- Copy real transcript lines into fixtures → green, realistic → leaks paths/keys into a public repo →
  synthetic only + redact scan → Task 7 receipt.
- Widen phrase lists until recall is high → dogfood looks great → every harvest drowns in noise →
  every MUST has a MUSTNOT twin; count candidates on af94571f before/after and report the delta.
- Test the source, dogfood the source → "works" → the installed copy is stale (version-gated refresh
  copies nothing) → dogfood ONLY via the plugin cache path resolved by `sort -V`, and print its version.
- Background suite piped through `| tail` → "completed exit 0" → failures hidden (obs 0097) → capture
  `exit=$?` inside the command, never read a pipe's exit.
- rtc-ship wedge → ship with `RTC_SKIP_TESTS=1` on an unverified tree → red release → only with the
  §8-recorded green run of the same commit.
- Editing the plugin cache to make dogfood pass → passes → reverted by next update → prohibited;
  fix in source, fix forward.
- A lower boundary read as higher: push ≠ merge ≠ release — this plan grants release; nothing beyond
  (no other repos, no memory/CLAUDE.md edits).
- Untestable safely: none of the steps need live services except GitHub (push/release via rtc-ship).

## 🏁 Final delivery (your last message to the user)

Implemented vs deferred; receipts that ran (with counts) and tests that did not; release URL; dogfood
output (K/5 + the two silent lines); waypoint/observation state; anything you could not do and why.
Confirm you stopped at the release boundary and touched no memory/CLAUDE.md files.

## 8. Progress log (one line per task, committed with it)

- 2026-11-09 02:00 — plan written (cloud Opus 5.5). Root cause confirmed live: structural lesson classes
  read only top-level tool_result records (0 in real transcripts).
- 2026-11-09 ~02:10 — Receipt 0 (Phase 0, read-only, all verified by running): (2) worktree clean at
  3b4e0dc on 485c229; main repo `~/ClaudeWorkspace/audit-loose-ends` on `main`, clean. (3) baseline suite
  via rtc-ship.json test_cmd (`… | parallel -j 12`) → exit=0, ALL PASS, exit captured inside the
  command, full log /tmp/ale-baseline-tests.log. (4) root cause re-proved on af94571f: top-level
  tool_result records = 0, tool_result blocks inside user records = 171. (5) baseline
  `--lessons af94571f` exit=0 → 4 candidates: corrections at lines 25, 511, 1263, schema-error at 1360,
  0 retries / 0 decisions / 0 self-corrections (transcript grew since the 02:00 snapshot's 2
  candidates: 1263 = the user's own quoted prompt, 1360 = pasted output — both more false positives);
  `--self-test` exit=0, 20 lines/scenarios fired across 5 classes. (6) observed shapes: user-record
  tool_result block keys = type/tool_use_id/content (+is_error when true), content is str or list of
  {type,text}; assistant tool_use block = type/id/name/input; AskUserQuestion answer = user record
  with top-level toolUseResult={questions, answers:{q→a}, annotations} AND a tool_result block
  "Your questions have been answered: …". Also: waypoint audit-scan-classifier-hardening read in full;
  skill-updates/2026-11-06/{audit-loose-ends,harvest-lessons} LOCATED under
  ~/.claude/skill-observations/; denial wording observed = `🥾 watch-your-step: ✖ BLOCKED — …` inside
  Bash tool_result content, plus top-level `toolDenialKind` records (counted in s.denials).
- 2026-11-09 ~02:30 — Task 1 DONE: block-shape pairing implemented (`_tool_target`/`_tool_input_key`,
  tool_use_id pairing, next-3-tool-calls window, git subcommand target, decision from
  toolUseResult.answers). Discriminant receipt: new scenarios failed on UNMODIFIED code
  (self-test exit=1, exactly 2 misses: both block-shape scenarios; unit positives got=[]). Green:
  suite exit=0 (421 ok), self-test 22 fired/5 classes exit=0. Mutation checks: window >30 →
  "4th call outside window" red; decision disabled → decision--block-shape miss red; both restored.
  af94571f delta: 4→10 candidates (retries 0→4, decisions 0→2 incl. line 830). Ruling: retry
  candidate line = the retrying call; compound retries pair on the first subcommand only
  (`git add X && git commit` targets "git add") — accepted heuristic limit, recorded here.
- 2026-11-09 ~03:00 — Task 2 DONE: `_answer_texts` reads toolUseResult answers + annotation
  `notes` (not `preview`); they enter the same correction pool/dedupe as typed prompts
  (category answer-note); `look again` added to _LESSON_ADVICE (menu-survey correction, obs 0098
  recurrence, user-supplied example 2026-11-09). Discriminant: self-test on unmodified code
  missed the new MUST line + correction--answer-note scenario. Green: suite exit=0,
  self-test 24/5 exit=0. Mutation: notes extraction disabled -> _answer_texts unit test red;
  restored. Validator dispatch: 4/4 attempts timed out (gemini + 3 nvidia) at ~02:55 —
  user confirmed nvidia is saturated by 7 concurrent sessions; re-dispatch planned with a
  no-nvidia FA_DISPATCH_PREFS.
- 2026-11-09 ~03:35 — Task 3 DONE: correction GATE `_is_correction_text` (skill-injection prefix,
  pasted-output >=60% indented/box-drawn lines — calibrated on af94571f line 25 share 0.94 —
  and 0070 self-quotation re.compile(/_LESSON_*) wraps the vocabulary; corpus predicate now
  tests the gate; _LESSON_PARTIAL adds 0087 shapes (except for / agree…except / I'd (much)
  rather). af94571f: corrections 3->1 — lines 25 and 511 SILENT (acceptance 3), line 1263
  remains (accepted: acceptance names 25/511 only; 1263 is a single-line quoted prompt, not
  pasted/skill-shaped). Ruling: "(much)" in the waypoint means OPTIONAL much — first regex
  version took it literally and the I'd-rather MUST missed; fixed. Suite exit=0, self-test
  27/5 exit=0. Mutation: pasted threshold 0.99 -> both pasted tests red; restored.
  Validator (local-laguna-s, poolside family, no-nvidia prefs, role dropped per user):
  Tasks 1+2 diff = "clean".
- 2026-11-09 ~03:50 — Task 4 DONE: new class `guard-block` (in _LESSON_ALL_CLASSES, summary line,
  display, self-test). Fires on ERRORED tool_result blocks matching denial wording
  (PreToolUse / hook error / BLOCKED / permission denied / denied by rule|hook /
  watch-your-step:) plus toolDenialKind==permission-rule records; user-rejected excluded;
  one candidate per record. Ruling: errored-only on the block shape — af94571f lines 124/331
  are non-errored Reads of a playbook quoting "BLOCKED" and fired until restricted; line 95
  (the real hook block) is is_error. af94571f: 13 -> 9 candidates, guard-block = line 95 only.
  Suite exit=0, self-test 28/6 exit=0. Mutation: errored-only dropped -> quoted-BLOCKED
  MUSTNOT red; restored.
- 2026-11-09 ~04:00 — Task 5 DONE: _LESSON_SELF_CORRECTION widened (landed on the wrong /
  that's my bug / the cause was / root cause / looks wrong / false positive / re-extract /
  already true before / could not have failed — the last two from the user's obs-0100
  launch-check example); _LESSON_OWNED_FAILURE now also accepts landed-on-the-wrong,
  that's-my-bug, looks-wrong, false positive as self-standing wrongness admissions (measured:
  af94571f line 1054 has no my/our token). MUSTNOT twins (README root-cause section, nightly
  re-extract) stay silent via the pairing. af94571f: self-corrections 0->2, line 1054 fires;
  total 11 candidates. Suite exit=0, self-test 32/6 exit=0. Mutation: landed-on-the-wrong
  removed from owned -> self-test miss on its MUST; restored.
- 2026-11-09 ~04:10 — Task 6 DONE: RECALL GAP printed under a GAPS header by the --lessons pass
  when a transcript has lesson-shaped writes (memory *.md, observation-log *.md delta or
  tool call, playbook Pitfalls edit) and NO candidate within ±50 records of any of them.
  af94571f: 7 lesson-shaped writes (lines 155,461,462,480,481,1240,1241), 3 near a candidate
  -> no gap (correct per the 0-near wording). Unit fixtures both ways (gap fires / suppressed
  near / no writes / Read-is-not-a-write). Suite exit=0, self-test exit=0. Mutation: gap
  condition inverted -> both gap tests red; restored.
- 2026-11-09 ~04:20 — Task 7 DONE: golden--recall-af94571f.jsonl (synthetic, markers GOLD-L1..L5
  + GOLDFP1/2, no real text; redact-secret --scan-only clean on all 6 fixture files). Direct
  extractor run: 5/5 lessons fire with the right classes (2 retry-after-fail, 1 decision,
  1 self-correction, 1 guard-block), both FPs silent. _self_test_corpus special-cases
  golden--*: asserts >=4/5 with right class + both GOLDFP silent. self-test 33/6 exit=0.
  Mutation: retry window killed -> "golden recall 3/5" miss, red; restored.
- 2026-11-09 ~04:30 — Task 8 DEFERRED (per plan: Tasks 1–7 green, ship path prioritised): waypoint
  point 0063 (GAPS flag for unbacked "tracked on|on waypoints" claims with no waypoints.py
  add/edit in the session) remains open on waypoint audit-scan-classifier-hardening.
- 2026-11-09 ~04:35 — Task 9 DONE: CHANGELOG ## [0.13.13] entry (Fixed/Added/Changed, matches
  0.13.12 style); SKILL.md class counts updated to six (audit-loose-ends + harvest-lessons);
  rtc-ship.sh --bump-versions . 0.13.13 -> plugin.json + CHANGELOG agree, --versions-only
  ALL PASS exit=0; full parallel suite on this tree exit=0 (463 ok), --self-test 33/6 exit=0.
  Whole-branch validator dispatch launched (no-nvidia prefs /tmp/prefs-nonnvidia.json, no role
  per user 2026-11-09); verdict recorded at ship commit.
