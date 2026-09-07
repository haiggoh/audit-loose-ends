#!/usr/bin/env python3
"""Extract the audit-relevant facts from Claude Code session transcripts, without reading them.

THE PROBLEM THIS SOLVES. The reconciliation pass needs to know what a session actually changed:
which durable records it touched, what it closed, whether the repos it edited are committed. The
obvious way to find that out is to resume the session and ask — but a long session's context is
the single most expensive thing in the system, and resuming a 300k-token one purely to tidy up has
cost several dollars in one swoop. The facts the audit needs are a few hundred bytes; the context
they arrive in is megabytes.

So this reads the transcript from OUTSIDE, streaming, and emits a digest. Nothing about the
session enters a model's context except the digest. The audit then runs in a fresh, cheap session.

WHY NOT THE EXISTING DISTILLER. `cc-transcript` already compacts a transcript, and it is the right
tool when you need to READ a session — a faithful, line-addressable chronology. It is the wrong
tool here, and the numbers say so: on a 4.8 MB transcript it produces a 352 KB capsule, roughly
88k tokens, which is still a dollar or so just to load. This produces a few KB. They are different
artifacts for different questions: preservation versus reconciliation. When the digest raises a
question that needs real chronology, that is the moment to reach for the distiller — or for
`--quote` below.

THE DESIGN THAT MAKES IT CHEAP. Claude Code already records every file it modified as a tiny
`file-history-delta` record carrying just a path. So the authoritative "what did this session
change" answer costs one small record per file version — no need to parse the Edit/Write arguments,
which are the largest payloads in the file and the reason a naive scan would be as expensive as the
thing it replaces. Tool arguments are read only for the few tools whose ARGUMENTS are themselves
the fact (a `git commit`, a `waypoints.py done`), and truncated hard even then.

`--quote PATTERN` is the second half of the idea. The digest is a MAP, deliberately too terse to
answer follow-ups. When it points at something you need to see, quote just that: a regex, a hard
character budget, and line numbers into the raw file. That is what keeps this cheaper than the
wrap it replaces — you pay for the one thread you actually pursue instead of the whole session.

READ-ONLY. This never writes to a transcript, a store, or a repo.
"""

import argparse
import collections
import fnmatch
import glob
import importlib.util
import json
import os
import re
import sys

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

# Hard caps. A digest that can grow without bound defeats the entire purpose -- the failure mode
# to design against is not "too little detail", it is silently reproducing the transcript.
MAX_CMD = 160            # chars of any single quoted command, at DISPLAY time
RAW_CMD_KEEP = 900       # chars of SHELL CODE retained so condense() can reach a
                         # heredoc subject, which sits on the line AFTER the marker
MAX_PROMPT = 400         # chars of a quoted user prompt
MAX_PER_SECTION = 40     # distinct entries listed in any one section before it summarises
DEFAULT_QUOTE_BUDGET = 4000

# --------------------------------------------------------------------------- classification
#
# Ordered most-specific first: the memory directory lives under ~/.claude, so a generic
# claude-config rule placed earlier would swallow it and the digest would under-report the surface
# the audit most cares about.
SURFACES = [
    ("memory",      ["*/memory/*.md", "*/memory/MEMORY.md"]),
    ("plans",       ["*/.claude/plans/*", "*/plans/*.md"]),
    ("waypoints",   ["*/waypoints.json", "*/waypoints-archive.json",
                     "*/waypoints-journal.jsonl"]),
    ("claude-md",   ["*/CLAUDE.md", "*/AGENTS.md", "*/.claude/CLAUDE.md"]),
    ("settings",    ["*/.claude/settings*.json", "*/settings.local.json"]),
    ("hooks",       ["*/hooks/*", "*/hooks.json"]),
    ("automation",  ["*/LaunchAgents/*", "*/Library/LaunchAgents/*", "*/crontab*"]),
    ("scripts",     ["*/.claude/scripts/*", "*/scripts/*"]),
    ("skills",      ["*/skills/*/SKILL.md"]),
    ("docs",        ["*.md", "*.txt", "*.rst"]),
]

# Bash commands whose ARGUMENTS are the audit fact, so they are worth the cost of reading.
# A command POSITION: start of input, a new line, or just after a shell operator. Anchoring here
# is what stops the word "launchctl" inside a commit MESSAGE from registering as automation --
# without it, every commit whose prose mentions a tool lands in that tool's section, and the
# sections the audit is meant to trust become the noisiest ones in the digest.
_CMDPOS = r"(?:^|\n|&&|\|\||;|\||\(|`|\$\()\s*(?:sudo\s+)?(?:[\w./~-]*/)?"

CMD_PATTERNS = [
    ("waypoints",  re.compile(_CMDPOS + r"waypoints(?:\.py)?\s+(?!--help|-h\b)\S+")),
    ("git-commit", re.compile(_CMDPOS + r"git\s[^\n|;&]*\bcommit\b")),
    ("git-push",   re.compile(_CMDPOS + r"git\s[^\n|;&]*\bpush\b")),
    # A tag OPERAND is required. `git tag` / `git tag | tail` LISTS tags and changes nothing;
    # without this the digest reported a listing as a release tag, complete with `tag |` as the
    # tag name -- a fabricated fact, which is worse in an audit than a missing one.
    ("git-tag",    re.compile(_CMDPOS + r"git\s[^\n|;&]*\btag\s+(?:-\S+\s+)*[^\s|;&<>()'\"-]")),
    ("release",    re.compile(_CMDPOS + r"gh\s+release\s+\w+")),
    ("automation", re.compile(
        _CMDPOS + r"(?:launchctl\s+(?:bootstrap|bootout|load|unload|enable|disable|kickstart|"
                  r"remove|submit|setenv|unsetenv)\b|crontab\s+(?!-l\b)\S)")),
    ("plugin",     re.compile(_CMDPOS + r"claude\s+plugin\s+\w+")),
    ("destructive", re.compile(_CMDPOS + r"(?:rm\s+-[rRf]{1,2}f?\s|git\s+push\s+[^\n]*--force|"
                               r"git\s+reset\s+--hard|DROP\s+TABLE|"
                               r"waypoints(?:\.py)?\s+rm\s[^\n]*--delete)")),
]

CAT_PATTERNS = dict(CMD_PATTERNS)

# Read-only git plumbing. Recording `git status` as "git activity" would inflate every digest with
# the one command that by definition changed nothing.
AUTOMATION_READONLY = re.compile(
    _CMDPOS + r"(?:launchctl\s+(?:print|list|dumpstate|procinfo|examine)\b|"
    r"crontab\s+-l\b)")

# NOTE the boundary placement: a trailing `\b` on the whole group is WRONG, because the
# alternatives that end at `$` or at a shell operator have no word character to bound against, so
# they silently never match. `git tag` and `git branch` went uncounted for exactly that reason.
GIT_READONLY = re.compile(
    r"\bgit\b[^|;&]*\b(?:(?:status|log|diff|show|rev-parse|rev-list|remote\s+-v)\b"
    r"|(?:branch|tag)\s*(?:$|(?=[|;&>]))"
    r"|tag\s+(?:-l\b|--list\b))")


# macOS ships /tmp, /var and /etc as symlinks into /private. Claude Code records a tool argument
# as the user typed it but a file-history path as resolved, so the SAME file arrives spelled two
# ways -- which made the cross-check report every temp file as both "changed" and "no change
# record". Normalising the prefix is enough; a full realpath() would be wrong here because the
# file may no longer exist by the time the scan runs.
_PREFIX_ALIASES = (("/tmp/", "/private/tmp/"), ("/var/", "/private/var/"), ("/etc/", "/private/etc/"))


def canon(path):
    p = os.path.normpath(str(path))
    for short, real in _PREFIX_ALIASES:
        if p.startswith(short):
            return real + p[len(short):]
    return p


# --- condensing a git command into the fact the audit wants ------------------------------------
# A real git line in this workflow is a compound: `cd repo && git add -A && git commit -F - <<MSG
# subject… && git push && git log`. Quoting it whole costs ~160 chars to say one thing, and the
# same line lands in COMMITS, PUSHES and TAGS looking identical in all three. So each category
# extracts only its own fact. This is the single biggest lever on digest size after file collapsing.
_CD_RE = re.compile(r"\bcd\s+(\S+)")
_MSG_Q_RE = re.compile(r"-m\s+(['\"])(.+?)\1", re.S)
# The marker is followed by the REST OF ITS LINE (often `&& git log …`); the body starts on the
# next line. Capture the first non-empty body line, which for a commit is the subject.
_HEREDOC_RE = re.compile(r"<<-?\s*'?[A-Za-z_][A-Za-z0-9_]*'?[^\n]*\n\s*(\S[^\n]*)")
_PUSH_RE = re.compile(r"\bpush\b((?:\s+--?\S+)*)\s*(\S+)?\s*(\S+)?")
_TAG_RE = re.compile(r"\btag\b(?:\s+-\S+)*\s+(\S+)")
_REL_RE = re.compile(r"\bgh\s+release\s+(\w+)\s+(\S+)?")
# What is stored per command is the SHELL CODE, with the commit subject appended under this marker.
# Storing the raw command instead meant a 30-line commit message consumed the whole retention
# budget and the operative `git push`/`git tag`/`gh release` that followed it was cut off -- the
# digest then reported "push" with no target and "tag ?" with no version. Found by running this
# scanner on the session that shipped it.
SUBJ_MARK = "\n#audit-scan-subject# "
_SUBJ_MARK_RE = re.compile(re.escape(SUBJ_MARK) + r"(.*)")


_HEREDOC_OPEN_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def shell_only(cmd):
    """The command with heredoc BODIES removed.

    Prose reaches a command two ways -- as a heredoc body and as a long quoted argument -- so
    this also runs `mask_prose`, and callers get one function that answers "which part of this was
    actually shell code".

    A heredoc body is data, not shell code — and in this workflow it is usually a commit message,
    which is prose about the very tools being detected. Matching patterns against it is why a
    commit whose message mentioned `launchctl` was reported as having run launchctl. Stripping the
    bodies fixes that class of false positive at the source, for every category at once, instead of
    per-pattern. The body is still available to the subject extractor, which reads the raw command.
    """
    if "<<" not in cmd:
        return mask_prose(cmd)
    out = []
    lines = cmd.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = _HEREDOC_OPEN_RE.search(line)
        i += 1
        if not m:
            continue
        tag = m.group(2)
        # Skip forward to the terminator. An unterminated heredoc (a truncated command) means the
        # rest is body, which is the safe reading: better to under-detect in data than to
        # over-detect prose as commands.
        while i < len(lines) and lines[i].strip() != tag:
            i += 1
        i += 1  # drop the terminator line too
    return mask_prose("\n".join(out))


def mask_prose(cmd):
    """The command with MULTI-LINE quoted DATA blanked out, quote-aware.

    The heredoc pass above only covers prose delivered as a heredoc. The same prose also
    arrives as a long quoted argument -- `gh release create --notes "..."`, whose body is a
    changelog describing the very commands being detected. Because the anchor treats the start
    of a line as a command position, a changelog line beginning "claude plugin update ..."
    registered as an actual plugin update: two fabricated entries in the digest, found by
    running this scanner on the session that built it.

    Only regions spanning a NEWLINE are blanked, because those are the prose payloads; a short
    same-line argument is left alone. `$(...)` inside double quotes is live code and is
    followed as such, so masking never swallows a real command -- that nesting is exactly the
    shape of the false positive, since the prose sat inside a substitution inside quotes.
    """
    if '"' not in cmd and "'" not in cmd:
        return cmd
    out = list(cmd)
    i, n = 0, len(cmd)
    # Frames: ["code"|"dq"|"sq", open_index, segment_start]. The bottom frame is shell code; a quote
    # pushes a DATA frame, and `$(` inside a data frame pushes CODE back on top. A data frame is
    # blanked SEGMENT by segment -- the runs between its quotes and any substitution inside it --
    # so masking `--notes "$(cmd "prose")"` removes the prose without touching the `$(cmd` around it.
    stack = [["code", 0, None]]

    def blank(a, b):
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    def close_seg(frame, end):
        a = frame[2]
        if a is not None and "\n" in cmd[a:end]:
            blank(a, end)
        frame[2] = None

    while i < n:
        c = cmd[i]
        top = stack[-1]
        if top[0] == "sq":
            if c == "'":
                close_seg(top, i)
                stack.pop()
        elif top[0] == "dq":
            if c == "\\":
                i += 2
                continue
            if cmd.startswith("$(", i):
                close_seg(top, i)
                stack.append(["code", i + 2, None])
                i += 2
                continue
            if c == '"':
                close_seg(top, i)
                stack.pop()
        else:
            if c == "\\":
                i += 1
            elif c == "'":
                stack.append(["sq", i, i + 1])
            elif c == '"':
                stack.append(["dq", i, i + 1])
            elif c == ")" and len(stack) > 1:
                stack.pop()
                if stack[-1][0] in ("dq", "sq"):
                    stack[-1][2] = i + 1      # data resumes after the substitution
        i += 1
    # An UNCLOSED region means a truncated command; treat the remainder as data, the same safe
    # reading the heredoc pass uses -- better to under-detect in data than to report prose as a
    # command that ran.
    for frame in stack:
        if frame[0] in ("dq", "sq"):
            close_seg(frame, n)
    return "".join(out)


def _repo_of(cmd):
    m = _CD_RE.search(cmd)
    # Trailing shell punctuation is not part of the directory name: `cd ~/ClaudeWorkspace;`
    # was reported as the repo "ClaudeWorkspace;".
    return os.path.basename(m.group(1).rstrip("/;&|\"'")) if m else ""


def _subject_of(cmd):
    m = _SUBJ_MARK_RE.search(cmd)
    if m:
        return m.group(1).strip()
    m = _MSG_Q_RE.search(cmd)
    if m:
        return m.group(2).strip().splitlines()[0]
    m = _HEREDOC_RE.search(cmd)
    if m:
        return m.group(1).strip()
    return ""


def condense(cat, cmd):
    """The audit-relevant fact, or the raw command when the command IS the fact."""
    repo = _repo_of(cmd)
    pre = f"{repo}: " if repo else ""
    if cat == "git-commit":
        subj = _subject_of(cmd)
        return (pre + (subj or "(subject not recoverable from the command line)"))[:MAX_CMD]
    if cat == "git-push":
        m = _PUSH_RE.search(cmd)
        if m:
            target = " ".join(x for x in (m.group(2), m.group(3)) if x and not x.startswith("-"))
            forced = "--force" in cmd or "-f " in cmd
            return f"{pre}push {target or '(default)'}" + ("  ⚠️ FORCED" if forced else "")
        return (pre + "push")[:MAX_CMD]
    if cat == "git-tag":
        m = _TAG_RE.search(cmd)
        return (pre + "tag " + (m.group(1) if m else "?"))[:MAX_CMD]
    if cat == "release":
        m = _REL_RE.search(cmd)
        return (pre + f"gh release {m.group(1)} {m.group(2) or ''}".strip()) if m else pre + "gh release"
    # waypoints, automation, plugin, destructive: the command text IS the fact, so it is kept --
    # but flattened and truncated here, since it was stored whole for the condensers above.
    #
    # Truncate from the MATCH, not from the start of the command. These sections are the ones the
    # audit is supposed to trust, and a shell one-liner routinely carries the operative call at the
    # end: dogfooding showed `claude plugin update` entries displayed as the `git add && git commit`
    # that happened to open the same line, and destructive entries showing a `mktemp` instead of the
    # `rm`. The entry was true and the evidence shown for it was somebody else's.
    # Locate the match BEFORE flattening. The anchor accepts a newline as a command position, so
    # flattening first removes the very character that makes a match possible -- which silently
    # undid the 0.5.3 fix for any command whose operative call began a line rather than following
    # an `&&`, and sent the display back to the head.
    raw = cmd.split(SUBJ_MARK)[0]
    pat = CAT_PATTERNS.get(cat)
    m = pat.search(raw) if pat else None
    if m and m.start() > 0:
        # Step over the operator the anchor matched, so the fragment starts at the command itself.
        # `split()` already drops leading whitespace, so only the operators need stripping.
        head = " ".join(raw[m.start():].lstrip("&|;`( \t").split())
        return "… " + head[:MAX_CMD] + ("…" if len(head) > MAX_CMD else "")
    one = " ".join(raw.split())
    return one[:MAX_CMD] + ("…" if len(one) > MAX_CMD else "")


def classify(path):
    low = path
    for name, globs in SURFACES:
        for g in globs:
            if fnmatch.fnmatch(low, g) or fnmatch.fnmatch("/" + low.lstrip("/"), g):
                return name
    return "other"


# --------------------------------------------------------------------------- redaction


def _load_redactor():
    """Reuse the plugin's own scanner rather than hand-rolling a pattern.

    The digest quotes real commands, and a command can carry a token. An improvised regex here
    would have none of redact-secret's word-boundary, shape and value filtering, which is exactly
    the mistake its own documentation warns about. If it cannot be loaded, redaction is reported as
    UNAVAILABLE rather than silently skipped -- quietly emitting raw text would be the worst of
    the three outcomes.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(here, "redact-secret.py")
    if not os.path.exists(target):
        return None
    try:
        spec = importlib.util.spec_from_file_location("_redact_secret", target)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_RED = _load_redactor()
# DEFAULT_PATTERN in redact-secret is the raw BYTES pattern, not a compiled one -- scan_bytes takes
# a compiled pattern and calls .finditer on it. Compile once here rather than per call; getting
# this wrong is silent, because the resulting AttributeError is caught by the fail-closed path and
# every quoted line comes out as "[REDACTION FAILED]" -- safe, but useless, and easy to ship.
_RED_PATTERN = None
if _RED is not None:
    try:
        _RED_PATTERN = re.compile(_RED.DEFAULT_PATTERN)
    except Exception:
        _RED_PATTERN = None


def redact(text):
    """Scrub before anything is printed. Never print-then-scrub: the print is the leak."""
    if _RED is None or _RED_PATTERN is None or not text:
        return text
    try:
        data = text.encode("utf-8", "replace")
        # scan_bytes returns (accepted, filtered) where accepted is [(offset, token, kind)].
        # Only `accepted` is substituted: `filtered` is what its five-layer filter already judged
        # NOT to be a secret (placeholders, benign values, prose), and redacting those would bury
        # the real finding in noise -- the exact failure its own docs warn about.
        accepted, _filtered = _RED.scan_bytes(data, _RED_PATTERN)
        if not accepted:
            return text
        out = bytearray()
        last = 0
        for offset, token, _kind in accepted:
            if offset < last:            # overlapping spans: keep the first, skip the rest
                continue
            out += data[last:offset] + b"[REDACTED]"
            last = offset + len(token)
        out += data[last:]
        return out.decode("utf-8", "replace")
    except Exception as e:
        # A redactor that errors must NEVER be treated as a redactor that found nothing: that
        # would turn a bug into a leak. Fail closed, and name the reason so it gets fixed.
        return f"[REDACTION FAILED ({type(e).__name__}) - value withheld]"


def redaction_status():
    if _RED is None or _RED_PATTERN is None:
        return "UNAVAILABLE (redact-secret.py not importable/compilable) — quoted text is RAW"
    return "active (redact-secret.py)"


# --------------------------------------------------------------------------- selection


def project_slug(path):
    """Claude Code's own directory naming: the absolute path with separators as dashes."""
    return path.replace("/", "-")


def find_transcripts(args):
    if args.file:
        return [os.path.abspath(f) for f in args.file]
    roots = []
    if args.all_projects:
        roots = sorted(glob.glob(os.path.join(PROJECTS_DIR, "*")))
    elif args.project:
        cand = os.path.join(PROJECTS_DIR, args.project)
        roots = [cand] if os.path.isdir(cand) else sorted(
            glob.glob(os.path.join(PROJECTS_DIR, f"*{args.project}*")))
    else:
        roots = [os.path.join(PROJECTS_DIR, project_slug(os.getcwd()))]
    files = []
    for r in roots:
        files.extend(glob.glob(os.path.join(r, "*.jsonl")))
    if args.session:
        files = [f for f in files
                 if os.path.basename(f).startswith(args.session)
                 or args.session in os.path.basename(f)]
    if args.exclude:
        files = [f for f in files
                 if not any(os.path.basename(f).startswith(x) for x in args.exclude)]
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    if args.since:
        files = [f for f in files if _mtime_date(f) >= args.since]
    if args.last and not args.session and not args.file:
        files = files[:args.last]
    return files


def _mtime_date(f):
    import datetime
    return datetime.datetime.fromtimestamp(os.path.getmtime(f)).date().isoformat()


# --------------------------------------------------------------------------- the scan


class Scan:
    def __init__(self, path):
        self.path = path
        self.bytes = os.path.getsize(path)
        self.lines = 0
        self.bad_lines = 0        # did not parse as JSON at all
        self.odd_records = 0      # parsed, but not a usable object
        self.session_ids = set()
        self.cwds = collections.Counter()
        self.branches = collections.Counter()
        self.versions = set()
        self.first_ts = None
        self.last_ts = None
        self.turns = collections.Counter()
        self.files = collections.Counter()       # abs path -> version count
        self.tools = collections.Counter()
        self.cmds = collections.defaultdict(list)   # category -> [command]
        self.readonly_git = 0
        self.readonly_automation = 0
        self.tasks = {}
        self.prompts = []
        self.api_errors = []
        self.denials = collections.Counter()
        self.stop_reasons = collections.Counter()
        self.subagents = 0
        self.plugins = set()
        self.skills = set()

    # -- per-record handling, ordered by how often each type appears so the common case is cheap
    def feed(self, d):
        t = d.get("type")
        self.turns[t] += 1

        ts = d.get("timestamp")
        if ts:
            if self.first_ts is None or ts < self.first_ts:
                self.first_ts = ts
            if self.last_ts is None or ts > self.last_ts:
                self.last_ts = ts
        for key in ("sessionId", "session_id"):
            if d.get(key):
                self.session_ids.add(d[key])
        if d.get("cwd"):
            self.cwds[d["cwd"]] += 1
        if d.get("gitBranch"):
            self.branches[d["gitBranch"]] += 1
        if d.get("version"):
            self.versions.add(d["version"])
        if d.get("isSidechain"):
            self.subagents += 1
        if d.get("attributionPlugin"):
            self.plugins.add(str(d["attributionPlugin"]))
        if d.get("attributionSkill"):
            self.skills.add(str(d["attributionSkill"]))
        if d.get("toolDenialKind"):
            self.denials[str(d["toolDenialKind"])] += 1
        if d.get("isApiErrorMessage") or d.get("apiErrorStatus"):
            self.api_errors.append(str(d.get("apiErrorStatus") or "error"))

        if t == "file-history-delta":
            # The cheap authoritative answer. `realParentDir` + `trackingPath` reconstruct the
            # absolute path; the version count tells you edited-once from edited-repeatedly.
            b = d.get("backup") or {}
            tp = d.get("trackingPath") or ""
            if not tp:
                return
            # `realParentDir` is already the file's PARENT directory, while `trackingPath` is
            # relative to the session cwd. Joining the two doubles the middle of the path
            # (".../memory/.claude/projects/.../memory/MEMORY.md"), which then fails to match the
            # same file seen via a tool call -- so every file was double-counted AND reported as
            # having no change record. Take the parent from the backup and only the basename from
            # the tracking path.
            parent = b.get("realParentDir")
            if parent:
                self.files[canon(os.path.join(parent, os.path.basename(tp)))] += 1
            elif self.cwds:
                self.files[canon(os.path.join(self.cwds.most_common(1)[0][0], tp))] += 1
            else:
                self.files[canon(tp)] += 1
            return

        if t == "assistant":
            msg = d.get("message") or {}
            if msg.get("stop_reason"):
                self.stop_reasons[msg["stop_reason"]] += 1
            for blk in msg.get("content") or []:
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    self._tool(blk)
            return

        if t == "last-prompt" and d.get("lastPrompt"):
            p = d["lastPrompt"]
            if isinstance(p, str) and p.strip():
                self.prompts.append(p.strip())

    def _tool(self, blk):
        name = blk.get("name") or "?"
        self.tools[name] += 1
        inp = blk.get("input") or {}
        if not isinstance(inp, dict):
            return

        # WRITING tools are a CROSS-CHECK on file-history, not the primary source: a file written
        # by a Bash heredoc has no delta record, and a delta with no tool call means an external
        # change. Disagreement between the two is itself worth reporting. Read is excluded --
        # it also carries file_path, and listing what was merely READ under a heading about
        # changes is a false positive in the one section the audit acts on.
        if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            for key in ("file_path", "notebook_path"):
                if inp.get(key):
                    self.files.setdefault(canon(inp[key]), 0)

        if name == "Bash":
            self._bash(str(inp.get("command") or ""))
        elif name in ("TaskCreate", "TaskUpdate"):
            tid = str(inp.get("task_id") or inp.get("id") or f"t{len(self.tasks)}")
            rec = self.tasks.setdefault(tid, {"desc": "", "state": ""})
            if inp.get("description") or inp.get("prompt"):
                rec["desc"] = str(inp.get("description") or inp.get("prompt"))[:120]
            if inp.get("state") or inp.get("status"):
                rec["state"] = str(inp.get("state") or inp.get("status"))

    def _bash(self, cmd):
        if not cmd:
            return
        if GIT_READONLY.search(shell_only(cmd)) and not any(
                p.search(shell_only(cmd)) for k, p in CMD_PATTERNS if k.startswith("git-")):
            self.readonly_git += 1
            return
        probe = shell_only(cmd)
        subj = _subject_of(cmd)
        subj_tail = SUBJ_MARK + " ".join(subj.split())[:200] if subj else ""
        if AUTOMATION_READONLY.search(probe):
            self.readonly_automation += 1
        for cat, pat in CMD_PATTERNS:
            m = pat.search(probe)
            if m:
                # Stored as SHELL CODE plus the subject, generously capped: condense() needs the
                # line structure, and the display truncation happens at report time instead.
                #
                # The retained head must be guaranteed to CONTAIN this category's match. A long
                # one-liner can push the matching call past the cap, and then the display falls back
                # to the head -- which is how a `claude plugin update` entry ended up showing the
                # `python3 - <<PY` that opened the same line. The head is kept for the leading `cd`
                # (that is where the repo name comes from), and the match window is appended.
                code = probe[:RAW_CMD_KEEP]
                if m.end() > RAW_CMD_KEEP:
                    code += "\n" + probe[m.start():m.start() + MAX_CMD + 40]
                # The subject tail goes LAST: condense() cuts the value at the marker, so anything
                # appended after it is invisible -- which is where the match window was going.
                self.cmds[cat].append(code + subj_tail)

    def run(self):
        with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                self.lines += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    self.bad_lines += 1
                    continue
                if not isinstance(d, dict):
                    # Valid JSON that is not a record (a bare list or scalar). Counted separately
                    # from a decode failure because the two mean different things about the file,
                    # and a single "malformed" tally would hide which one you are looking at.
                    self.odd_records += 1
                    continue
                try:
                    self.feed(d)
                except Exception:
                    # One malformed record must never abort a scan whose whole value is that it
                    # is cheaper than the alternative. Count it and keep going.
                    self.odd_records += 1
        return self


# --------------------------------------------------------------------------- reporting


def _uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _section(out, title, rows, empty=None):
    if not rows:
        if empty:
            out.append(f"\n{title}\n  {empty}")
        return
    out.append(f"\n{title}")
    for r in rows[:MAX_PER_SECTION]:
        out.append(f"  {r}")
    if len(rows) > MAX_PER_SECTION:
        out.append(f"  … {len(rows) - MAX_PER_SECTION} more (--json for all)")


def report(scans, args):
    out = []
    total_raw = sum(s.bytes for s in scans)

    for s in scans:
        sid = ", ".join(sorted(s.session_ids)) or os.path.basename(s.path)[:8]
        out.append("=" * 72)
        out.append(f"SESSION {sid}")
        out.append(f"  transcript  {s.path}")
        out.append(f"  span        {s.first_ts or '?'} → {s.last_ts or '?'}")
        out.append(f"  size        {s.bytes/1024:.0f} KB, {s.lines} records"
                   + (f", {s.bad_lines} unparseable" if s.bad_lines else "")
                   + (f", {s.odd_records} unusable shape" if s.odd_records else ""))
        if s.cwds:
            out.append(f"  cwd         {'; '.join(p for p, _n in s.cwds.most_common(3))}")
        if s.branches:
            out.append(f"  branch      {'; '.join(b for b, _n in s.branches.most_common(3))}")
        if s.versions:
            out.append(f"  cc version  {', '.join(sorted(s.versions))}")
        if s.subagents:
            out.append(f"  subagents   {s.subagents} sidechain record(s)")

        # --- durable records, grouped by surface: this is the section the audit acts on ---
        touched = {p: n for p, n in s.files.items() if n > 0}
        by_surface = collections.defaultdict(list)
        for p, n in sorted(touched.items()):
            by_surface[classify(p)].append(f"{p}" + (f"  (v{n})" if n > 1 else ""))
        rows = []
        for surf, _globs in SURFACES + [("other", [])]:
            group = by_surface.get(surf)
            if not group:
                continue
            rows.append(f"[{surf}]")
            if surf == "other" and len(group) > 8:
                # Collapse to per-directory counts. A durable record is worth naming individually;
                # thirty source files in one repo are one fact ("that repo was worked on"), and
                # spelling them out is how a digest quietly becomes the transcript again.
                per_dir = collections.Counter(os.path.dirname(x.split("  (v")[0])
                                             for x in group)
                for dirname, n in per_dir.most_common():
                    rows.append(f"  {dirname}/  — {n} file(s)")
                rows.append(f"  (--json lists all {len(group)} individually)")
            else:
                rows.extend("  " + x for x in group)
        _section(out, f"DURABLE RECORDS MODIFIED ({len(touched)} file(s))", rows,
                 empty="none recorded — the session changed no tracked file")

        mentioned_only = sorted(p for p, n in s.files.items() if n == 0 and p not in touched)
        if mentioned_only:
            _section(out, "FILES NAMED BY A TOOL BUT WITH NO CHANGE RECORD "
                          "(read, or written via a shell redirect)",
                     mentioned_only)

        for cat in ("waypoints", "git-commit", "git-push", "git-tag", "release",
                    "plugin", "automation", "destructive"):
            if s.cmds.get(cat):
                label = {"waypoints": "WAYPOINTS COMMANDS RUN",
                         "git-commit": "COMMITS", "git-push": "PUSHES", "git-tag": "TAGS",
                         "release": "RELEASES", "plugin": "PLUGIN INSTALLS/UPDATES",
                         "automation": "AUTOMATION (launchctl / crontab)",
                         "destructive": "⚠️  DESTRUCTIVE COMMANDS"}[cat]
                _section(out, label, _uniq(redact(condense(cat, c)) for c in s.cmds[cat]))

        if s.tasks:
            _section(out, "TASK LIST AT END",
                     [f"{v.get('state') or '?':<12} {v.get('desc') or k}"
                      for k, v in s.tasks.items()])

        if s.prompts:
            _section(out, "USER PROMPTS (first and last, truncated)", [
                redact(p[:MAX_PROMPT].replace("\n", " ⏎ ")) for p in
                _uniq([s.prompts[0], s.prompts[-1]] if len(s.prompts) > 1 else s.prompts[:1])
            ])

        # --- ending state: the audit needs to know whether the session finished ---
        ending = []
        if s.stop_reasons:
            ending.append("stop reasons: " + ", ".join(f"{k}×{v}" for k, v in
                                                       s.stop_reasons.most_common()))
        if s.api_errors:
            ending.append(f"⚠️  {len(s.api_errors)} API error record(s): "
                          + ", ".join(_uniq(s.api_errors)[:5]))
        if s.denials:
            ending.append("tool denials: " + ", ".join(f"{k}×{v}"
                                                       for k, v in s.denials.most_common()))
        _section(out, "ENDING", ending, empty="no error or denial records")

        if s.tools:
            out.append("\nTOOL USE  " + ", ".join(f"{k}×{v}" for k, v in s.tools.most_common(12)))
            extra = []
            if s.readonly_git:
                extra.append(f"{s.readonly_git} read-only git")
            if s.readonly_automation:
                extra.append(f"{s.readonly_automation} read-only launchctl/crontab")
            if extra:
                # Reported rather than silent: "no automation section" and "automation was only
                # ever INSPECTED" are different findings, and a bare absence cannot tell them apart.
                out.append(f"  ({', '.join(extra)} command(s) not listed above — they changed "
                           f"nothing)")

        # --- what this scan CANNOT tell you. Stated, not implied. ---
        out.append("\nGAPS — this scan cannot determine:")
        out.append("  · whether a repo is currently clean (run `git status` yourself; a commit")
        out.append("    here is not evidence of a clean tree afterwards)")
        out.append("  · whether a memory/plan edit is CORRECT, only that it happened")
        out.append("  · anything from a file written by a shell redirect with no tool record")
        out.append("  · the session's reasoning or intent — use --quote, or cc-transcript, for that")
        if _RED is None:
            out.append("  · ⚠️  redaction was UNAVAILABLE, so quoted text above is unfiltered")

    body = "\n".join(out)
    econ = (f"\n{'=' * 72}\n"
            f"ECONOMY  scanned {total_raw/1024:.0f} KB of transcript → emitted "
            f"{len(body)/1024:.1f} KB of digest "
            f"({(len(body)/total_raw*100) if total_raw else 0:.2f}% — roughly "
            f"{max(1, total_raw//max(len(body), 1))}× smaller)\n"
            f"REDACTION  {redaction_status()}\n"
            f"NEXT  --quote '<regex>' to read only the section a finding points at")
    return body + econ


# --------------------------------------------------------------------------- quoting


def quote(paths, pattern, budget):
    """Pull only the records matching a regex, with line addresses and a hard budget.

    This is the half that keeps the whole approach honest. The digest is deliberately too terse to
    answer follow-ups, so without a targeted way to go deeper the only option would be loading the
    session — which is the cost this exists to avoid. Line numbers are printed so a genuinely
    unavoidable deep dive can be aimed at an exact offset.
    """
    rx = re.compile(pattern, re.I)
    spent = 0
    hits = 0
    for path in paths:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                if not rx.search(line):
                    continue
                hits += 1
                try:
                    d = json.loads(line)
                except Exception:
                    d = {}
                text = _flatten(d) or line
                for m in rx.finditer(text):
                    lo = max(0, m.start() - 120)
                    hi = min(len(text), m.end() + 200)
                    snip = " ".join(text[lo:hi].split())
                    chunk = (f"{os.path.basename(path)}:{n}  [{d.get('type', '?')}] "
                             f"…{redact(snip)}…")
                    if spent + len(chunk) > budget:
                        print(f"\n(budget {budget} chars reached after {hits} matching record(s) "
                              f"— raise it with --budget, or narrow the pattern)")
                        return 0
                    print(chunk)
                    spent += len(chunk)
                    break
    if not hits:
        print(f"(no record matched /{pattern}/ — the pattern found nothing, which is a RESULT: "
              f"it is not evidence the scan failed)")
    else:
        print(f"\n({hits} matching record(s), {spent} chars emitted)")
    return 0


def _flatten(d):
    """Everything a human would want to grep, as one string. Kept out of the digest path — this
    runs only for records already known to match, so its cost is bounded by the hit count."""
    parts = []
    for key in ("lastPrompt", "content"):
        v = d.get(key)
        if isinstance(v, str):
            parts.append(v)
    msg = d.get("message") or {}
    cont = msg.get("content")
    if isinstance(cont, str):
        parts.append(cont)
    elif isinstance(cont, list):
        for b in cont:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                parts.append(str(b.get("text") or ""))
            elif b.get("type") == "tool_use":
                parts.append(f"[{b.get('name')}] {json.dumps(b.get('input') or {})[:2000]}")
            elif b.get("type") == "thinking":
                parts.append(str(b.get("thinking") or "")[:2000])
    tr = d.get("toolUseResult")
    if isinstance(tr, str):
        parts.append(tr[:2000])
    return "\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- cli


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="audit-scan.py",
        description="Extract audit-relevant facts from Claude Code transcripts without loading "
                    "them into context. Read-only.")
    p.add_argument("file", nargs="*", help="explicit transcript path(s); overrides selection")
    p.add_argument("--project", help="project dir under ~/.claude/projects (substring ok); "
                                     "default is the one for $PWD")
    p.add_argument("--all-projects", action="store_true")
    p.add_argument("--session", help="session id or its prefix")
    p.add_argument("--last", type=int, default=1, metavar="N",
                   help="the N most recently modified transcripts (default 1)")
    p.add_argument("--since", metavar="YYYY-MM-DD", help="only transcripts modified on/after this")
    p.add_argument("--exclude", action="append", default=[], metavar="SESSION_ID",
                   help="skip a session id prefix — use it to exclude the CURRENT session, "
                        "which has not finished and so cannot be reconciled yet")
    p.add_argument("--list", action="store_true", help="list the selected transcripts and stop")
    p.add_argument("--json", action="store_true", help="the full structured facts, unabridged")
    p.add_argument("--quote", metavar="REGEX",
                   help="print only records matching REGEX, with line addresses and a budget")
    p.add_argument("--budget", type=int, default=DEFAULT_QUOTE_BUDGET,
                   help=f"max chars --quote may emit (default {DEFAULT_QUOTE_BUDGET})")
    args = p.parse_args(argv)

    paths = find_transcripts(args)
    if not paths:
        print("no transcripts selected. Try --all-projects, --project <slug>, or pass a path.",
              file=sys.stderr)
        return 1

    if args.list:
        for f in paths:
            print(f"{_mtime_date(f)}  {os.path.getsize(f)/1024:>8.0f} KB  {f}")
        return 0

    if args.quote:
        return quote(paths, args.quote, args.budget)

    scans = [Scan(f).run() for f in paths]

    if args.json:
        print(json.dumps([{
            "transcript": s.path, "bytes": s.bytes, "records": s.lines,
            "unparseable": s.bad_lines, "unusable": s.odd_records,
            "session_ids": sorted(s.session_ids), "first": s.first_ts, "last": s.last_ts,
            "cwds": dict(s.cwds), "branches": dict(s.branches),
            "versions": sorted(s.versions),
            "files": {p: n for p, n in sorted(s.files.items())},
            "surfaces": {p: classify(p) for p in sorted(s.files)},
            "tools": dict(s.tools),
            "commands": {k: _uniq(redact(condense(k, c)) for c in v) for k, v in s.cmds.items()},
            "commands_raw": {k: _uniq(redact(c) for c in v) for k, v in s.cmds.items()},
            "readonly_git": s.readonly_git, "readonly_automation": s.readonly_automation,
            "tasks": s.tasks, "stop_reasons": dict(s.stop_reasons),
            "api_errors": s.api_errors, "denials": dict(s.denials),
            "plugins": sorted(s.plugins), "skills": sorted(s.skills),
            "redaction": redaction_status(),
        } for s in scans], indent=1))
        return 0

    print(report(scans, args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
