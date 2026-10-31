# audit-loose-ends skill — incident history and rationale

Moved out of `skills/audit-loose-ends/SKILL.md` in 0.13.7 to keep the skill body inside the
1500-word budget (check-code SKILL-BUDGET). The rules these incidents produced stay in the skill;
this file keeps the stories and the numbers behind them.

- **Why step 0 exists:** resuming a 300k-token session to reconcile it cost several dollars — more
  than the work it reconciles — so the scanner emits a few-KB digest instead (~600× smaller on a
  4.8 MB transcript, measured). Audit big sessions from a fresh session reading the digest, the
  way `resume-interrupted` recovers one.
- **Two confidence sections:** before 0.5.6, shell-inferred writes were not reported at all, so a
  session that edited three memory files through heredocs showed one and a short list read as
  "nothing changed". Auto-mode sessions prefer `sed`/heredoc over the Edit tool, which made the
  blind spot bite hardest exactly there.
- **Why the digest is trusted over memory:** after a compaction the session's own record of the
  early part is gone while the transcript's is not; recall favours recent/interesting over touched.
- **Secret-scan path-list incident (2026-10-25):** a word-split turned 27 filenames into 222 paths
  and the scanner reported "0 occurrences across 222 files" — a confident clean result over paths it
  never opened. Hence NUL-delimited lists + `verify-paths.sh --null` + `--require`.
- **ttyd `/token` leak:** a local service behind auth echoed an endpoint that hands back the
  credential base64-encoded (`{"token":"<base64 user:pass>"}`); printing that body published the
  password into the transcript while a public tunnel was live. Base64 survives a glance and
  shape-scanners. Rule: treat `/token`, `/session`, `/whoami`, `/debug` as credential-bearing;
  test auth by status code, never by content.
- **Fixture templates, never literals:** GitHub push protection rejected a test file whose
  synthetic `sk_live_…`/`xoxb-…` samples had a real vendor shape. Write `sk-ant-api03-{A:95}`,
  `AKIA{U:16}`, expand at load time.
- **sed scrub leak:** `sed 's/\(TOKEN\|KEY\)=.*/\1=<redacted>/'` leaked a token in cleartext —
  BSD/macOS `sed` has no `\|` in a basic regex, the group never matched, exit 0. Filter by NAME
  before emitting values; if scrubbing, use `sed -E`/`grep -E` and verify the placeholder.
- **Plans repo history:** 49 of 51 deleted plans existed nowhere but git history (measured) —
  why `~/.claude/plans` is a local git repo. 2026-09-24: an NVIDIA test plan appeared mid-wrap-up
  from another session — hence skip files modified in the last ~2 minutes and name them.
- **Heredoc under-report:** caught by `ls -lt` over the records dir, which remains the cross-check
  for scripted-edit sessions.
