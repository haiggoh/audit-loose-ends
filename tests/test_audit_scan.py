#!/usr/bin/env python3
"""Framework-free tests for scripts/audit-scan.py.

Run: python3 tests/test_audit_scan.py     (no pytest, matching the rest of this repo)

Every detector here is tested against a PLANTED POSITIVE as well as the negative it is meant to
reject. That is not symmetry for its own sake: while building this scanner, three separate detectors
"passed" by finding nothing at all — a heredoc-stripping fix silently removed the real `launchctl`
calls along with the false ones, and the digest looked cleaner for it. A detector that cannot be
shown to fire is indistinguishable from one that is broken.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "audit-scan.py")

spec = importlib.util.spec_from_file_location("audit_scan", SCRIPT)
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

_fail = 0


def check(ok, label, detail=""):
    global _fail
    if ok:
        print(f"  ok: {label}")
    else:
        print(f"  FAIL: {label}" + (f"\n        {detail}" if detail else ""))
        _fail += 1


def eq(got, want, label):
    check(got == want, label, f"got {got!r}, want {want!r}")


# --------------------------------------------------------------------------- fixtures


def rec_bash(cmd):
    return {"type": "assistant", "timestamp": "2026-09-07T10:00:00Z", "sessionId": "test-sess",
            "cwd": "/Users/x/repo", "gitBranch": "main", "version": "2.1.220",
            "message": {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}}


def rec_write(path):
    return {"type": "assistant", "timestamp": "2026-09-07T10:00:01Z", "sessionId": "test-sess",
            "message": {"content": [
                {"type": "tool_use", "name": "Write", "input": {"file_path": path}}]}}


def rec_read(path):
    return {"type": "assistant", "timestamp": "2026-09-07T10:00:01Z", "sessionId": "test-sess",
            "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": path}}]}}


def rec_delta(parent, tracking):
    return {"type": "file-history-delta", "trackingPath": tracking,
            "timestamp": "2026-09-07T10:00:02Z",
            "backup": {"realParentDir": parent, "version": 1}}


def scan_records(records):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        for r in records:
            # A str is written VERBATIM so a test can plant a genuinely malformed line. Passing it
            # through json.dumps would encode it as a valid JSON string, which is how an earlier
            # version of this helper made every "invalid" fixture line perfectly valid -- the
            # unparseable-line tests were asserting nothing at all.
            fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
        path = fh.name
    try:
        return A.Scan(path).run()
    finally:
        os.unlink(path)


def cmds(records, cat):
    return [A.condense(cat, c) for c in scan_records(records).cmds.get(cat, [])]


def render(records):
    """The rendered DIGEST for a set of records, not the Scan object.

    Some findings exist only in the report layer (which section a path lands in, what GAPS says),
    so asserting on Scan fields alone would let a detector fire while the reader never sees it.
    Goes through the CLI, like the end-to-end tests."""
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        for r in records:
            fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
        path = fh.name
    try:
        return subprocess.run([sys.executable, SCRIPT, path], capture_output=True, text=True,
                              timeout=60).stdout
    finally:
        os.unlink(path)


# --------------------------------------------------------------------------- path reconstruction

print("== file-history path reconstruction ==")

s = scan_records([rec_delta("/Users/bra0002h/.claude", ".claude/CLAUDE.md")])
eq(sorted(s.files), ["/Users/bra0002h/.claude/CLAUDE.md"],
   "realParentDir + basename, not parent + full relative path")

# The original bug: joining realParentDir with the whole trackingPath doubled the middle of the
# path, so the same file seen via a tool call never matched and was reported as both changed and
# unchanged at once.
check(not any("/.claude/projects" in p and p.count("/memory/") > 1 for p in s.files),
      "no doubled path segments")

MEM = "/Users/bra0002h/.claude/projects/-Users-bra0002h/memory"
s = scan_records([rec_delta(MEM, "memory/MEMORY.md"), rec_delta(MEM, "memory/MEMORY.md")])
eq(s.files[f"{MEM}/MEMORY.md"], 2, "repeat edits raise the version count on ONE path")

print("== macOS /private prefix aliasing ==")
eq(A.canon("/tmp/x/y"), "/private/tmp/x/y", "/tmp is normalised to /private/tmp")
eq(A.canon("/var/folders/z"), "/private/var/folders/z", "/var is normalised")
eq(A.canon("/Users/x/tmp/y"), "/Users/x/tmp/y", "a mid-path 'tmp' is NOT rewritten")
# Without this, a temp file recorded resolved by file-history and unresolved by the tool call
# appeared in BOTH the changed list and the "no change record" list.
s = scan_records([rec_write("/tmp/a.txt"), rec_delta("/private/tmp", "tmp/a.txt")])
eq(len(s.files), 1, "the same file spelled /tmp and /private/tmp is ONE entry")

print("== Read is not a change ==")
s = scan_records([rec_read("/Users/x/never-written.md")])
eq(s.files.get("/Users/x/never-written.md"), None,
   "a Read does not register the file at all")
s = scan_records([rec_write("/Users/x/w.md")])
check("/Users/x/w.md" in s.files, "a Write registers the file")
eq(s.files["/Users/x/w.md"], 0,
   "a Write with no delta record registers at count 0 (cross-check, not a change claim)")

# --------------------------------------------------------------------------- classification

print("== surface classification ==")
for path, want in [
    (f"{MEM}/some-fact.md", "memory"),
    ("/Users/x/.claude/plans/PLAN-thing.md", "plans"),
    ("/Users/x/.claude/waypoints.json", "waypoints"),
    ("/Users/x/.claude/CLAUDE.md", "claude-md"),
    ("/Users/x/.claude/settings.json", "settings"),
    ("/Users/x/repo/hooks/hooks.json", "hooks"),
    ("/Users/x/Library/LaunchAgents/com.thing.plist", "automation"),
    ("/Users/x/repo/skills/foo/SKILL.md", "skills"),
    ("/Users/x/repo/src/main.rs", "other"),
]:
    eq(A.classify(path), want, f"{want:<10} ← {os.path.basename(path)}")

# memory files live UNDER ~/.claude, so an earlier generic rule would swallow them -- this is the
# ordering the SURFACES list exists to guarantee.
check(A.classify(f"{MEM}/x.md") == "memory",
      "a memory file is not captured by a broader ~/.claude rule")

# --------------------------------------------------------------------------- heredoc handling

print("== heredoc bodies are data, not shell code ==")
# The body deliberately puts the tool names at the START of a line -- i.e. at what LOOKS like a
# command position. A body that only mentions them mid-sentence is rejected by the anchor alone, so
# a weaker fixture here passed even with heredoc stripping switched off entirely.
COMMIT = """cd ~/ClaudeWorkspace/thing && git add -A && git commit -q -F - <<'MSG' && git push
Install the LaunchAgent installer

The installer runs:
launchctl bootstrap gui/501 ~/Library/LaunchAgents/x.plist
rm -rf ~/Library/Caches/stale
git push --force is never used here.
MSG"""
so = A.shell_only(COMMIT)
check("launchctl bootstrap" not in so, "a heredoc body is stripped before matching")
check("git commit" in so, "the shell code around the heredoc survives stripping")
eq(cmds([rec_bash(COMMIT)], "automation"), [],
   "prose in a commit message does NOT register as automation")
eq(cmds([rec_bash(COMMIT)], "destructive"), [],
   "prose in a commit message does NOT register as destructive")
eq(cmds([rec_bash(COMMIT)], "git-commit"), ["thing: Install the LaunchAgent installer"],
   "the commit subject is read FROM the heredoc body")

# The subject sits on the line AFTER the marker; the marker's own line continues the pipeline. An
# earlier version flattened first and reported "&& git push" as the subject.
check(A._subject_of(COMMIT) == "Install the LaunchAgent installer",
      "subject comes from the body's first line, not the marker's line")

eq(cmds([rec_bash('cd ~/r && git commit -m "Quoted subject here"')], "git-commit"),
   ["r: Quoted subject here"], "a -m quoted subject is extracted too")

check(A.shell_only("echo plain") == "echo plain", "a command with no heredoc is untouched")
UNTERM = "cat <<'EOF'\nbody line mentioning launchctl bootstrap\n"
check("launchctl" not in A.shell_only(UNTERM),
      "an UNTERMINATED heredoc treats the remainder as body (under-detect in data, safely)")

# --------------------------------------------------------------------------- command detection

print("== planted positives: each detector must actually fire ==")
POSITIVES = [
    ("automation",  "launchctl bootstrap gui/501 ~/Library/LaunchAgents/x.plist"),
    ("automation",  "/bin/launchctl bootout gui/501/com.x",),
    ("automation",  "sudo launchctl enable system/com.x"),
    ("automation",  "crontab mycrontab.txt"),
    ("waypoints",   "waypoints.py done some-item"),
    ("waypoints",   "waypoints resolve"),
    ("git-commit",  'git commit -m "x"'),
    ("git-push",    "git push origin main"),
    ("git-tag",     "git tag -a v1.0.0 -m x"),
    ("release",     "gh release create v1.0.0"),
    ("plugin",      "claude plugin update waypoints"),
    ("destructive", "rm -rf /some/dir"),
    ("destructive", "git push --force origin main"),
    ("destructive", "git reset --hard origin/main"),
    ("destructive", "waypoints.py rm x --delete --confirm"),
]
for cat, cmd in POSITIVES:
    got = scan_records([rec_bash(cmd)]).cmds.get(cat, [])
    check(bool(got), f"{cat:<12} fires on: {cmd[:52]}")

print("== negatives: read-only work must NOT be reported as a change ==")
NEGATIVES = [
    ("automation",  "launchctl print gui/501/com.x"),
    ("automation",  "launchctl list | grep thing"),
    ("automation",  "crontab -l"),
    ("git-commit",  "git status --porcelain"),
    ("git-commit",  "git log --oneline -5"),
    ("git-push",    "git rev-list --count HEAD --not --remotes"),
    ("waypoints",   "waypoints --help"),
    ("destructive", "echo 'rm -rf is dangerous'"),
]
for cat, cmd in NEGATIVES:
    got = scan_records([rec_bash(cmd)]).cmds.get(cat, [])
    eq(got, [], f"{cat:<12} silent on: {cmd[:52]}")

# ...but silence must be COUNTED, or "no automation section" and "automation was only inspected"
# become the same finding.
s = scan_records([rec_bash("launchctl print gui/501/com.x"), rec_bash("crontab -l")])
eq(s.readonly_automation, 2, "read-only automation probes are counted, not discarded")
s = scan_records([rec_bash("git status"), rec_bash("git log")])
eq(s.readonly_git, 2, "read-only git commands are counted, not discarded")

print("== condensing ==")
eq(A.condense("git-push", "cd ~/r && git push --force origin main"),
   "r: push origin main  ⚠️ FORCED", "a forced push is flagged in the condensed line")
eq(A.condense("git-tag", "cd ~/r && git tag -a v0.4.0 -m x"), "r: tag v0.4.0",
   "a tag condenses to repo + tag name")
eq(A.condense("release", "cd ~/r && gh release create v0.4.0 --notes x"),
   "r: gh release create v0.4.0", "a release condenses to repo + verb + tag")
# Compared against a LITERAL, not against A.MAX_CMD: measuring the output against the very
# constant that produced it passes no matter how large the cap becomes.
long_subject = A.condense("git-commit", 'cd ~/r && git commit -m "' + "x" * 900 + '"')
check(len(long_subject) <= 200, f"a condensed commit line stays short (got {len(long_subject)})")
long_raw = A.condense("waypoints", "waypoints.py add \"" + "y" * 900 + "\"")
check(len(long_raw) <= 200, f"a raw-kept command is truncated too (got {len(long_raw)})")

# ------------------------------------------------- prose in a quoted argument (dogfooding fixes)

# Everything in this section was found by running the finished scanner on the session that built
# it. All four defects FABRICATED facts rather than missing them, which in an audit is the worse
# failure: a reader has no way to tell an invented entry from a real one.

print("== multi-line quoted prose is data, not shell code ==")
NOTES = ('cd ~/r && gh release create v0.5.0 --notes "$(python3 -c "\n'
         'print(1)\nclaude plugin update thing\nlaunchctl bootstrap gui/501 x.plist\n'
         '")" && git push origin main')
m = A.mask_prose(NOTES)
check("claude plugin update" not in m, "prose inside a quoted --notes payload is masked")
check("launchctl bootstrap" not in m, "so is automation named in that prose")
check("gh release create v0.5.0" in m and "git push origin main" in m,
      "the real commands around it survive")
# The segment rule is what makes this work: a data frame is blanked BETWEEN its quotes and any
# substitution inside it, so masking the prose does not swallow the `$(python3 -c` that produced it.
check("python3 -c" in m, "a $( ) substitution inside the quotes is code and survives")
# ...and the split has to happen at the OPENING of the substitution, not only at its close: prose
# sitting BEFORE a `$( )` in the same quoted argument is otherwise never blanked, because the data
# segment gets restarted after the substitution and the earlier run is forgotten.
LEADING = ('gh release create v1 --notes "release notes:\n'
           'claude plugin update thing\nbuilt $(date)\nend"')
lm = A.mask_prose(LEADING)
check("claude plugin update" not in lm, "prose BEFORE a substitution is masked too")
check("$(date)" in lm, "and the substitution itself still survives")
eq(cmds([rec_bash(LEADING)], "plugin"), [], "so it does not register as a plugin install")
# The mirror of the same requirement: data has to RESUME after the substitution closes, or prose
# following a `$( )` inside the same argument stays unmasked.
TRAILING = 'gh release create v1 --notes "built $(date)\nlaunchctl bootstrap gui/501 x.plist\nend"'
check("launchctl bootstrap" not in A.mask_prose(TRAILING), "prose AFTER a substitution is masked too")
eq(cmds([rec_bash(TRAILING)], "automation"), [], "so it does not register as an automation change")
eq(cmds([rec_bash(NOTES)], "plugin"), [], "a changelog mentioning `claude plugin update` is not an install")
eq(cmds([rec_bash(NOTES)], "automation"), [], "...nor is one mentioning launchctl an automation change")
check(bool(cmds([rec_bash(NOTES)], "release")), "but the release it actually performed IS reported")

eq(A.mask_prose('git commit -m "short subject"'), 'git commit -m "short subject"',
   "a SAME-LINE quoted argument is left alone")
eq(A.mask_prose("echo hi"), "echo hi", "a command with no quotes is untouched")
check("git tag -a v1" in A.mask_prose('git push origin main &&\n  git tag -a v1 -m "x"'),
      "a command split over several LINES is code, not prose")
check("launchctl bootstrap" not in A.mask_prose('echo "start\nlaunchctl bootstrap x'),
      "an unterminated quote treats the remainder as data (under-detect in data, safely)")

print("== a long commit message cannot truncate the operative commands away ==")
# The original defect: the RAW command was stored, so a 30-line commit message ate the retention
# budget and the `git push`/`git tag`/`gh release` after it were cut off. The digest then reported
# `push` with no target and `tag ?` with no version -- entries that looked like findings.
LONG = ("cd ~/thing && git commit -q -F - <<'MSG'\nShip the thing\n\n"
        + "\n".join("body line %d that pads this message well past the retention cap" % i
                    for i in range(40))
        + "\nMSG\ngit push -q origin HEAD && git tag -a v0.9.0 -m x && gh release create v0.9.0")
check(len(LONG) > A.RAW_CMD_KEEP, f"the fixture really does exceed the cap ({len(LONG)} chars)")
eq(cmds([rec_bash(LONG)], "git-push"), ["thing: push origin HEAD"],
   "the push target survives a message longer than the retention cap")
eq(cmds([rec_bash(LONG)], "git-tag"), ["thing: tag v0.9.0"], "so does the tag name")
eq(cmds([rec_bash(LONG)], "release"), ["thing: gh release create v0.9.0"], "so does the release")
eq(cmds([rec_bash(LONG)], "git-commit"), ["thing: Ship the thing"],
   "and the subject is still recovered, carried explicitly rather than re-parsed")
marked = A.condense("waypoints", "waypoints.py list" + A.SUBJ_MARK + "a subject")
check("audit-scan-subject" not in marked and "a subject" not in marked,
      f"the internal subject marker never reaches the digest (got {marked!r})")

print("== a raw-kept command is shown FROM the match, not from its head ==")
# A shell one-liner routinely carries the operative call last. Dogfooding showed `claude plugin
# update` entries displayed as the `git add && git commit` that opened the same line: the entry was
# true and the evidence printed under it belonged to a different command.
TAIL = ("cd ~/thing && git add -- a b c && " + "echo padding && " * 12
        + "claude plugin update audit-loose-ends")
shown = cmds([rec_bash(TAIL)], "plugin")[0]
check("claude plugin update audit-loose-ends" in shown, f"the matching call is visible (got {shown!r})")
check(shown.startswith("… "), "and the fragment is marked as starting mid-command")
check("git add" not in shown, "the unrelated head of the line is not what gets shown")
# The anchor deliberately matches the OPERATOR before the command, so the fragment has to step over
# it -- otherwise every such entry reads "… && claude plugin update", which looks like a fragment of
# something rather than the command that ran.
eq(shown, "… claude plugin update audit-loose-ends",
   "the fragment starts at the command, not at the operator the anchor matched")
# ...but a command that matches at its START must not gain a spurious leading ellipsis.
eq(cmds([rec_bash("waypoints.py done thing")], "waypoints"), ["waypoints.py done thing"],
   "a command matching at position 0 is shown verbatim")
long_tail = cmds([rec_bash("cd ~/r && " + "echo x && " * 30 + "rm -rf /some/dir " + "y" * 900)],
                 "destructive")[0]
check(len(long_tail) <= A.MAX_CMD + 4, f"the from-the-match fragment is still capped ({len(long_tail)})")
check("rm -rf /some/dir" in long_tail, "and it still contains the destructive call itself")

# Third facet of the same truncation defect: the retained slice must be guaranteed to CONTAIN the
# match, or the display falls back to the head and shows an unrelated command as the evidence.
# The padding must be real shell CODE: heredoc bodies are stripped before the cap is applied, so a
# fixture padded with a heredoc never exceeds it and the test passes without exercising anything.
FAR = "cd ~/thing && " + "echo padding-here && " * 60 + "claude plugin update audit-loose-ends"
check(len(A.shell_only(FAR)) > A.RAW_CMD_KEEP + A.MAX_CMD,
      f"the fixture puts the match well past the cap ({len(A.shell_only(FAR))} chars of code)")
far = cmds([rec_bash(FAR)], "plugin")[0]
check("claude plugin update audit-loose-ends" in far,
      f"a match beyond the retention cap is still what gets shown (got {far!r})")
check("padding-here" not in far, "and the retained head is not shown instead")
# The anchor accepts a NEWLINE as a command position, so a call that begins its own line must be
# found too -- and it is only findable before the text is flattened. This is the shape the digest
# actually produced: a ship one-liner whose `claude plugin update` sat on a later line.
NL = "cd ~/thing &&\n" + "echo padding-here\n" * 60 + "claude plugin update audit-loose-ends"
nl = cmds([rec_bash(NL)], "plugin")[0]
check("claude plugin update audit-loose-ends" in nl,
      f"a match anchored on a NEWLINE past the cap is shown (got {nl!r})")
check("padding-here" not in nl, "and not the head of the command")
eq(A.condense("git-commit", "cd ~/thing && x" + " " * A.RAW_CMD_KEEP + 'git commit -m "Late subject"'),
   "thing: Late subject", "the repo name still comes from the retained head")

# ...and it must survive alongside a COMMIT SUBJECT. condense() cuts the stored value at the subject
# marker, so a match window appended after that marker is invisible. Both earlier fixtures happened
# to contain no commit, which is why a real ship one-liner still displayed its head after the fix.
BOTH = ("cd ~/thing && git commit -q -F - <<'MSG'\nShip it\nMSG\n" + "echo padding-here && " * 60
        + "claude plugin update audit-loose-ends")
both = cmds([rec_bash(BOTH)], "plugin")[0]
check("claude plugin update audit-loose-ends" in both,
      f"a late match survives alongside a commit subject (got {both!r})")
eq(cmds([rec_bash(BOTH)], "git-commit"), ["thing: Ship it"], "and the subject is still recovered")

print("== `git tag` with no operand LISTS tags ==")
for cmd in ("git tag", "git tag | tail -3", "cd ~/r; git tag | head", "git tag -l 'v*'"):
    eq(cmds([rec_bash(cmd)], "git-tag"), [], f"a listing is not a tag creation: {cmd}")
s_ro = scan_records([rec_bash("cd ~/r; git tag | head")])
eq(s_ro.readonly_git, 1, "and the listing is counted as read-only git rather than dropped")
# Boundary placement, not vocabulary: with a trailing `\b` on the whole alternation, every
# alternative ending at `$` or a shell operator can never match, because there is no word
# character to bound against. `git tag` and `git branch` were silently uncounted.
for cmd in ("git tag", "git branch", "git tag -l 'v*'"):
    eq(scan_records([rec_bash(cmd)]).readonly_git, 1, f"counted read-only: {cmd}")
for cmd in ("git tag -a v1 -m x", "git branch -D old"):
    eq(scan_records([rec_bash(cmd)]).readonly_git, 0, f"NOT read-only: {cmd}")
check(bool(cmds([rec_bash("git tag -a v1.0.0 -m x")], "git-tag")),
      "an actual tag creation still fires")

eq(A.condense("git-tag", "cd ~/ClaudeWorkspace/r; git tag -a v1 -m x"), "r: tag v1",
   "trailing shell punctuation is not part of the repo name")

# --------------------------------------------------------------------------- redaction

print("== redaction ==")
check(A._RED is not None and A._RED_PATTERN is not None,
      "redact-secret loaded AND its bytes pattern compiled")
# The pattern in redact-secret is raw BYTES, not compiled. Passing it through uncompiled raises
# AttributeError, which the fail-closed path turns into "[REDACTION FAILED]" on EVERY line --
# safe, but silently useless, and it shipped that way once.
secret = "sk-" + "a1b2c3d4e5f6g7h8i9j0"
red = A.redact(f"export TOKEN={secret} && echo done")
check(secret not in red, "a real token is removed", red)
check("[REDACTED]" in red, "the removal is marked", red)
check("REDACTION FAILED" not in red, "redaction does not fail closed on valid input", red)
check("echo done" in red, "surrounding text survives redaction", red)
eq(A.redact("just some ordinary prose"), "just some ordinary prose",
   "prose with no secret is returned unchanged")
# A secret in a command must not survive into the digest.
out = "\n".join(A.report([scan_records([rec_bash(f"curl -H 'Authorization: Bearer {secret}'")])],
                         None).splitlines())
check(secret not in out, "a secret in a command never reaches the digest")

# --------------------------------------------------------------------------- robustness

print("== robustness ==")
s = scan_records([rec_bash("git status"), "NOT JSON AT ALL", "{unclosed", "[]",
                  rec_write("/x/y.md")])
eq(s.bad_lines, 2, "each line that fails to PARSE is counted as unparseable")
eq(s.odd_records, 1, "valid JSON that is not a record is counted SEPARATELY (`[]`)")
eq(s.lines, 5, "and none of them aborts the scan")
check(s.files.get("/x/y.md") == 0, "a record after both kinds of bad line still lands")
check("/x/y.md" in s.files, "records after a bad line are still processed")

s = scan_records([{"type": "assistant", "message": {"content": "a plain string, not a list"}}])
eq(s.bad_lines, 0, "an unexpected content shape is not an error")

s = scan_records([{"type": "file-history-delta", "trackingPath": "x.md", "backup": {}}])
eq(sorted(s.files), ["x.md"], "a delta with no realParentDir and no cwd still records the path")

# --------------------------------------------------------------------------- the digest contract

print("== the digest stays small, and says what it cannot know ==")
big = []
for i in range(400):
    big.append(rec_delta("/Users/x/repo/src", f"src/file{i}.rs"))
    big.append(rec_bash(f'cd ~/repo && git commit -m "change {i}"'))
body = A.report([scan_records(big)], None)
check(len(body) < 12000, f"400 files + 400 commits still digest to <12 KB (got {len(body)})")
# The collapse must be asserted by what it REPLACES, not by total size: with 40-per-section capping
# also in play, a size check alone passes whether or not the collapse happens.
check("/Users/x/repo/src/  — 400 file(s)" in body,
      "a large same-directory set collapses to one per-directory count line")
check("file137.rs" not in body,
      "and the individual filenames are NOT spelled out in the digest")
multi = ([rec_delta("/Users/x/repo/a", f"a/f{i}.rs") for i in range(12)]
         + [rec_delta("/Users/x/repo/b", f"b/g{i}.rs") for i in range(9)])
mbody = A.report([scan_records(multi)], None)
check("/Users/x/repo/a/  — 12 file(s)" in mbody and "/Users/x/repo/b/  — 9 file(s)" in mbody,
      "the collapse is per-directory, so which repo areas were touched is still visible")
# The `other` surface collapses per-directory, so it never exercises the per-section cap. A
# durable surface like `memory` is listed file-by-file ON PURPOSE -- naming which memories changed
# is the point -- which makes it the section that MUST still be capped, or one runaway session
# reproduces its own file listing in full.
many_mem = [rec_delta(MEM, f"memory/fact-{i}.md") for i in range(400)]
mem_body = A.report([scan_records(many_mem)], None)
check(mem_body.count("fact-") <= A.MAX_PER_SECTION + 1,
      f"an uncollapsed surface is still capped per section (listed {mem_body.count('fact-')})")
check("more (--json for all)" in mem_body,
      "and the digest says how many entries it withheld rather than truncating silently")
check(len(mem_body) < 8000, f"so the digest stays small (got {len(mem_body)})")

check("GAPS" in body, "the digest states what it cannot determine")
check("git status" in body, "the gaps name the check the scan cannot substitute for")
check("ECONOMY" in body, "the digest reports its own compression, so the claim is measured")

# --------------------------------------------------------------------------- cli, end to end

print("== cli ==")
with tempfile.TemporaryDirectory() as td:
    tf = os.path.join(td, "sess.jsonl")
    with open(tf, "w") as fh:
        for r in [rec_bash("waypoints.py done thing"), rec_delta(MEM, "memory/x.md"),
                  rec_bash("launchctl bootstrap gui/501 x.plist")]:
            fh.write(json.dumps(r) + "\n")

    r = subprocess.run([sys.executable, SCRIPT, tf], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, "exits 0 on a valid transcript", r.stderr[:300])
    check("waypoints.py done thing" in r.stdout, "the waypoints command reaches the digest")
    check("launchctl bootstrap" in r.stdout, "the automation command reaches the digest")
    check("memory" in r.stdout, "the memory surface is named")

    r = subprocess.run([sys.executable, SCRIPT, tf, "--json"], capture_output=True, text=True,
                       timeout=60)
    payload = json.loads(r.stdout)
    check(isinstance(payload, list) and payload, "--json emits a parseable list")
    check("commands" in payload[0] and "files" in payload[0], "--json carries the structured facts")
    check(payload[0]["redaction"].startswith("active"), "--json reports redaction status")

    r = subprocess.run([sys.executable, SCRIPT, tf, "--quote", "launchctl"],
                       capture_output=True, text=True, timeout=60)
    check("launchctl" in r.stdout, "--quote finds a matching record")
    check(":" in r.stdout, "--quote prints a line address")

    r = subprocess.run([sys.executable, SCRIPT, tf, "--quote", "zzz-no-such-thing"],
                       capture_output=True, text=True, timeout=60)
    check("no record matched" in r.stdout, "--quote says so when nothing matched")
    check("is a RESULT" in r.stdout,
          "--quote frames an empty result as a finding, not a failure")

    r = subprocess.run([sys.executable, SCRIPT, tf, "--quote", ".", "--budget", "200"],
                       capture_output=True, text=True, timeout=60)
    check("budget" in r.stdout.lower(), "--quote enforces its character budget")
    check(len(r.stdout) < 1200, f"--quote output respects the budget (got {len(r.stdout)})")

    r = subprocess.run([sys.executable, SCRIPT, tf, "--list"], capture_output=True, text=True,
                       timeout=60)
    check("sess.jsonl" in r.stdout, "--list names the selected transcript")

    # read-only guarantee: the transcript must be byte-identical after every mode above
    before = open(tf, "rb").read()
    for extra in ([], ["--json"], ["--quote", "."], ["--list"]):
        subprocess.run([sys.executable, SCRIPT, tf] + extra, capture_output=True, timeout=60)
    check(open(tf, "rb").read() == before, "the scanner never modifies the transcript")

    r = subprocess.run([sys.executable, SCRIPT, "--project", "no-such-project-xyz"],
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 1, "an empty selection exits non-zero rather than pretending success")

# ------------------------------------------------- shell-written durable records (the 09-08 miss)

print("== shell-written durable records: the scan's own blind spot ==")
# MEASURED 2026-09-08: a session modified three memory files and the digest reported ONE. The two
# it missed were written by a heredoc and by `sed -i` — neither produces a file-history delta nor a
# Write/Edit record. An auto-mode session is instructed to prefer exactly those, so the sessions
# most likely to be audited this way were the ones it was blindest on.
MEM = "/Users/bra0002h/.claude/projects/-Users-bra0002h/memory"
SHELL_WRITE_POSITIVES = [
    (f"cat >> {MEM}/a-fact.md <<'EOF'\nbody\nEOF",        f"{MEM}/a-fact.md",  "heredoc append"),
    (f"cat > {MEM}/b-fact.md <<'EOF'\nbody\nEOF",         f"{MEM}/b-fact.md",  "heredoc create"),
    (f"sed -i '' 's/x/y/' {MEM}/MEMORY.md",                f"{MEM}/MEMORY.md",  "sed -i in place"),
    (f"echo hi | tee -a {MEM}/c-fact.md",                  f"{MEM}/c-fact.md",  "tee -a"),
    (f"cp /tmp/draft.md {MEM}/d-fact.md",                  f"{MEM}/d-fact.md",  "cp onto a record"),
    ("printf x > ~/.claude/settings.json",     "/Users/bra0002h/.claude/settings.json", "settings"),
]
for cmd, want, label in SHELL_WRITE_POSITIVES:
    got = scan_records([rec_bash(cmd)]).shell_writes
    check(any(os.path.normpath(want) == k for k in got),
          f"shell-write fires: {label}", f"cmd={cmd[:40]!r} got={list(got)}")

print("== shell-write negatives: noise must NOT be reported as a durable change ==")
SHELL_WRITE_NEGATIVES = [
    ("echo x > /tmp/scratch.txt",                    "a temp file is not a durable record"),
    ("ls -l > /dev/null 2>&1",                       "/dev/null and 2>&1 are not paths"),
    ("python3 script.py 2>&1 | tail -5",             "a stderr dup is not a redirect target"),
    (f"cat {MEM}/a-fact.md",                         "READING a record is not writing it"),
    (f"grep -c foo {MEM}/MEMORY.md",                 "grepping a record is not writing it"),
    ("git commit -m 'update MEMORY.md and memory/x.md'",
     "a path inside a COMMIT MESSAGE is not a write"),
]
for cmd, label in SHELL_WRITE_NEGATIVES:
    got = scan_records([rec_bash(cmd)]).shell_writes
    check(not got, f"shell-write quiet: {label}", f"cmd={cmd[:46]!r} got={list(got)}")

# The stronger evidence must WIN: a file with a real delta record must not also be listed as a
# lower-confidence shell write, or one change reads as two.
_out = render([rec_bash(f"cat >> {MEM}/both.md <<'EOF'\nx\nEOF"),
               rec_delta(MEM, "both.md")])
check(_out.count(f"{MEM}/both.md") == 1,
      "a file with a delta record is not double-reported as a shell write")

# GAPS must name the SPECIFIC uncertainty. The old line fired unconditionally and was printed on
# the very session that had three shell-written memory files, telling the reader nothing.
_g = render([rec_bash(f"cat >> {MEM}/e-fact.md <<'EOF'\nx\nEOF")])
check("were really MODIFIED" in _g, "GAPS names the shell-written paths it actually saw")
_g2 = render([rec_bash("git status --porcelain")])
check("shell redirect with no tool record" in _g2,
      "GAPS keeps the generic line when no shell write was seen")

# A relative path must resolve against the cwd IN EFFECT, not the session's most common one.
# Found by dogfooding: the digest named cost-tracker/scripts/audit-scan.py, a file in neither
# repo, because the session's dominant cwd was the other project. Inventing a path is worse than
# omitting one — it sends the reader to audit something that does not exist.
_r1 = dict(rec_bash("sed -i '' s/a/b/ scripts/audit-scan.py"))
_r1["cwd"] = "/Users/bra0002h/ClaudeWorkspace/audit-loose-ends"
_r2, _r3 = dict(rec_bash("echo 1")), dict(rec_bash("echo 2"))
_r2["cwd"] = _r3["cwd"] = "/Users/bra0002h/ClaudeWorkspace/cost-tracker"   # the DOMINANT cwd
_got = list(scan_records([_r2, _r1, _r3]).shell_writes)
check(_got == ["/Users/bra0002h/ClaudeWorkspace/audit-loose-ends/scripts/audit-scan.py"],
      "a relative path resolves against the cwd in effect, not the dominant one",
      f"got={_got}")

print()
if _fail:
    print(f"FAILURES: {_fail}")
    raise SystemExit(1)
print("ALL PASS")
