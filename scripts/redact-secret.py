#!/usr/bin/env python3
"""Redact a secret from named files, in place, cheaply.

Design goals, in order:

1. CHEAP. It touches exactly the files you name. There is no directory walk, no
   glob expansion of its own, no "while I'm here" audit. Widening the scope is a
   separate decision that belongs to the human, not to this tool.
2. SAFE FOR LIVE FILES. Every hit is overwritten with a same-length placeholder
   at the same byte offset, so the inode, the byte size and the mode are all
   unchanged. That matters because Claude Code appends to the current session's
   transcript through an open file handle: a `sed -i`-style rewrite would leave
   the CLI writing to an orphaned inode. Never redact a live transcript by
   rewrite-and-rename.
3. THE SECRET NEVER ENTERS argv. A secret passed on the command line lands in
   shell history, in `ps` output, and in the transcript of whatever agent ran
   it. Pass it on stdin, in a file, or identify it by sha256 prefix instead.
4. FEW ENOUGH FALSE POSITIVES TO BE BELIEVED. A scan that cries wolf gets
   replaced by an improvised `grep`, and an improvised grep has no filtering at
   all. See "Why the layers" below.

Usage
-----
  # by value, from stdin (does not appear in argv/history)
  pbpaste | redact-secret.py --secret - FILE...

  # by value, from a file
  redact-secret.py --secret-file /path/to/key.txt FILE...

  # by sha256 prefix, when you never want to type the value at all
  redact-secret.py --sha256 2f859c50 FILE...

  # everything token-shaped (review with --scan-only first)
  redact-secret.py --all-matches FILE...

  # look, change nothing -- this is the wrap-up "did I leak anything" sweep
  redact-secret.py --scan-only FILE...

  # show the near-misses and why each was suppressed
  redact-secret.py --scan-only --explain-filtered FILE...

  # prove the filter still catches every known key shape
  redact-secret.py --self-test

Why the layers
--------------
Hand-rolled greps for `sk-[A-Za-z0-9]{8}|password|bearer` produce hits like
"task-specific", "on-disk-cache", "--password" (a flag NAME) and
"MAX_OUTPUT_TOKENS=8192". Each layer below kills one of those classes, and each
is chosen so it cannot suppress a real credential:

  L1 left boundary   `(?<![A-Za-z0-9])` -- "sk" inside taSK/diSK/aSK can never
                     start a match. Zero false-negative risk: no real key is
                     glued to the back of a word.
  L2 vendor shapes   A documented prefix (sk-ant-apiNN-, sk-proj-, ghp_, AKIA,
                     AIza, glpat-, hf_, xoxb- ...) is accepted on shape alone,
                     with no further test. This is what makes L3 safe.
  L3 diversity gate  Applied ONLY to the ambiguous generic `sk-`/`sk_`
                     catch-all: the body must be >=20 chars and draw on >=2 of
                     {lower, upper, digit} -- OR be one unbroken >=32-char run.
                     Prose slugs ("sk-prefixed-keys-are-recognizable") are
                     all-lowercase and hyphenated, so they fail both; a random
                     40-char key confined to a single character class has
                     probability ~(26/62)**40, and would in any case have been
                     accepted at L2.
  L4 assignments     Credential KEYWORDS are matched only as `key=value` /
                     `key: value`, never bare. So `--password` as a flag name is
                     silent, while `--password=hunter2` is not.
  L5 value sanity    An assignment value that is numeric, a known non-secret
                     ("local", "changeme"), an interpolation ($VAR, ${X}, {{x}}),
                     a path, or a placeholder (REDACTED/EXAMPLE/xxxx) is not a
                     credential. This is what keeps MAX_OUTPUT_TOKENS=8192 and
                     ANTHROPIC_AUTH_TOKEN=local quiet.

Suppression is never silent: filtered near-misses are counted in every report
and `--explain-filtered` prints each one with its reason. `--self-test` runs a
must-match / must-not-match corpus (seeded with the real historical false
positives) through the same scan_bytes() the tool itself uses, so "no false
negatives" is a property that can fail a test rather than a claim. That corpus
lives in tests/fixtures/scan-corpus.txt, NOT in this file, so sweeping this repo
does not keep re-reporting the fixtures themselves. It declares itself with a
magic first line and is reported as SKIPPED -- out loud, in the output, and only
until you pass --no-corpus-skip.

Assignment hits (L4) are REPORT-ONLY by default. Overwriting the value in a live
config breaks that config, which is sometimes exactly right but always
deliberate: pass --include-assignments to redact them too.

Exit status: 0 = done (or nothing to do), 1 = a verification failure was rolled
back or a self-test failed, 2 = bad invocation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

# --- L2: documented vendor shapes. Accepted on shape alone, no entropy test. ---
VENDOR_SHAPES = (
    rb"sk-ant-api\d{2}-",
    rb"sk-ant-sid\d{2}-",
    rb"sk-proj-",
    rb"sk-svcacct-",
    rb"sk-admin-",
    rb"sk-or-v1-",
    rb"sk_live_",
    rb"sk_test_",
    rb"ghp_",
    rb"gho_",
    rb"ghu_",
    rb"ghr_",
    rb"ghs_",
    rb"github_pat_",
    rb"xox[baprs]-",
    rb"AKIA",
    rb"ASIA",
    rb"AIza",
    rb"glpat-",
    rb"hf_",
)
VENDOR_RE = re.compile(rb"(?:" + rb"|".join(VENDOR_SHAPES) + rb")")

# L1 + candidate shapes. The generic sk-/sk_ arm is deliberately loose here and
# is narrowed afterwards by L3, so the two tests stay readable and testable.
DEFAULT_PATTERN = (
    rb"(?<![A-Za-z0-9])"
    rb"(?:sk-|sk_|ghp_|gho_|ghu_|ghr_|ghs_|github_pat_|xox[baprs]-|AKIA|ASIA|AIza|glpat-|hf_)"
    rb"[A-Za-z0-9_\-]{15,}"
)

MIN_SECRET_LEN = 12
GENERIC_MIN_BODY = 20   # chars after a bare sk-/sk_
OPAQUE_RUN_MIN = 32     # an unbroken run this long is never prose

# Markers are all >=7 chars on purpose: the chance a random 95-char base62 key
# contains any one of them by accident is ~95*(1/62)**7, i.e. ~1e-11.
PLACEHOLDER_MARKERS = (
    b"redacted", b"example", b"placeholder", b"your_key", b"your-key",
    b"yourkey", b"key_here", b"key-here", b"notreal", b"xxxxxxxx",
    b"........",  # NB: no "12345678"/"abcdefgh" -- a real Slack/AWS token
                 # can contain a sequential run, and an FN is worse than an FP.
)

# --- L4: credential keywords, only ever as key=value / key: value. ---
_ASSIGN_KEY = (
    rb"(?:pass(?:wd|word|phrase)"          # password / passwd / passphrase
    rb"|pass(?![A-Za-z])"                  # bare pass=, but NOT passes/passed/passing
    rb"|secret|api[_-]?key|auth[_-]?token|access[_-]?token|token|credential)"
)
ASSIGNMENT_RE = re.compile(
    rb"(?<![A-Za-z0-9_])"
    rb"[A-Za-z0-9_.\-]{0,24}" + _ASSIGN_KEY + rb"[A-Za-z0-9_.\-]{0,24}"
    rb"[ \t]*[:=][ \t]*"
    rb"(\"[^\"\r\n]{6,160}\"|'[^'\r\n]{6,160}'|[^\s\"',;)}\]]{6,160})",
    re.IGNORECASE,
)
BEARER_RE = re.compile(rb"(?<![A-Za-z0-9])[Bb]earer[ \t]+([A-Za-z0-9_\-.=]{16,})")

# --- L5: values that are structurally incapable of being the secret itself. ---
SOURCE_REF_RE = re.compile(
    rb"\.(?:swift|py|sh|zsh|js|ts|tsx|jsx|json|jsonl|md|txt|ya?ml|toml|log|conf|cfg"
    rb"|ini|go|rs|rb|java|kt|c|h|cpp|hpp|plist|patch|diff|bak)\b",
    re.IGNORECASE,
)

BENIGN_VALUES = frozenset((
    b"local", b"none", b"null", b"nil", b"true", b"false", b"changeme",
    b"password", b"passwort", b"secret", b"token", b"example", b"test",
    b"dummy", b"fake", b"sample", b"placeholder", b"todo", b"tbd", b"unset",
    b"empty", b"required", b"optional", b"stdin", b"prompt", b"disabled",
    b"enabled", b"default", b"redacted", b"hidden", b"omitted",
))


def _char_classes(s: bytes) -> int:
    return sum(bool(re.search(c, s)) for c in (rb"[a-z]", rb"[A-Z]", rb"[0-9]"))


def token_reason(tok: bytes) -> str | None:
    """None = credible credential. A string = why this hit is a false positive."""
    low = tok.lower()
    for marker in PLACEHOLDER_MARKERS:
        if marker in low:
            return "placeholder/example (contains %r)" % marker.decode()
    if VENDOR_RE.match(tok):
        return None                                     # L2: documented shape
    body = tok[3:]                                      # past a bare sk- / sk_
    if len(body) < GENERIC_MIN_BODY:
        return "generic sk- body %d < %d chars" % (len(body), GENERIC_MIN_BODY)
    if b"-" not in body and b"_" not in body and len(body) >= OPAQUE_RUN_MIN:
        return None                                     # L3: opaque run
    if _char_classes(body) < 2:
        return "one character class over %d chars (prose-shaped, not key-shaped)" % len(body)
    return None


def value_reason(val: bytes) -> str | None:
    """None = the value could be a live credential. A string = why it cannot."""
    v = val.strip()
    if len(v) >= 2 and v[:1] == v[-1:] and v[:1] in (b'"', b"'"):
        v = v[1:-1]
    v = v.rstrip(b".,;:!?)]}")
    if len(v) < 8:
        return "value under 8 chars"
    if v.isdigit():
        return "numeric (a limit or count, not a credential)"
    if v.lower() in BENIGN_VALUES:
        return "known non-secret value %r" % v.decode("ascii", "replace")
    if v[:2] in (b"{{", b"${", b"%(", b"./") or v[:1] in (b"$", b"<", b"-", b"%", b"/", b"~", b"@"):
        return "interpolation, flag or path -- not a literal"
    low = v.lower()
    for marker in PLACEHOLDER_MARKERS + (b"***", b"redact"):
        if marker in low:
            return "placeholder value"
    if b"(" in v or b"[" in v:
        return "a call/subscript expression, not a literal"
    if SOURCE_REF_RE.search(v):
        return "a source/file reference, not a credential"
    if re.search(rb"\s", v) and _char_classes(v) < 2:
        return "prose (whitespace, single character class)"
    if _char_classes(v) < 2 and len(v) < 16:
        return "low-entropy short value (%d chars, one character class)" % len(v)
    return None


def scan_bytes(data: bytes, pattern: re.Pattern, include_assignments: bool = True):
    """The one detection path. Returns (accepted, filtered).

    accepted: [(offset, token_bytes, kind)]  kind is "token" or "assignment"
    filtered: [(offset, token_bytes, reason)]
    """
    accepted: list[tuple[int, bytes, str]] = []
    filtered: list[tuple[int, bytes, str]] = []

    for m in pattern.finditer(data):
        tok = m.group(0)
        reason = token_reason(tok)
        (filtered if reason else accepted).append(
            (m.start(), tok, reason) if reason else (m.start(), tok, "token")
        )

    if include_assignments:
        taken = [(off, off + len(t)) for off, t, _ in accepted]

        def overlaps(a: int, b: int) -> bool:
            return any(a < end and start < b for start, end in taken)

        for rx, group in ((ASSIGNMENT_RE, 1), (BEARER_RE, 1)):
            for m in rx.finditer(data):
                raw = m.group(group)
                start, end = m.span(group)
                if len(raw) >= 2 and raw[:1] == raw[-1:] and raw[:1] in (b'"', b"'"):
                    start, end, raw = start + 1, end - 1, raw[1:-1]
                if overlaps(start, end):
                    continue                     # already caught as a token
                reason = value_reason(raw)
                if reason:
                    filtered.append((start, raw, reason))
                else:
                    accepted.append((start, raw, "assignment"))
                    taken.append((start, end))

    accepted.sort(key=lambda s: s[0])
    filtered.sort(key=lambda s: s[0])
    return accepted, filtered


def placeholder_for(token: bytes) -> bytes:
    """Same-length stand-in that keeps any recognisable prefix."""
    for prefix in (b"sk-", b"sk_", b"ghp_", b"github_pat_", b"glpat-", b"AKIA", b"AIza", b"hf_"):
        if token.startswith(prefix):
            head = prefix + b"REDACTED"
            break
    else:
        head = b"REDACTED"
    if len(head) >= len(token):
        return b"x" * len(token)
    return head + b"x" * (len(token) - len(head))


def read_secret(args: argparse.Namespace) -> bytes | None:
    if args.secret == "-":
        return sys.stdin.buffer.read().strip()
    if args.secret_file:
        with open(args.secret_file, "rb") as fh:
            return fh.read().strip()
    return None


def verify(path: str, original: bytes, new: bytes, before: os.stat_result) -> str | None:
    """Return None if the edit is sound, else a reason string."""
    if len(new) < len(original):
        return "file shrank (%d -> %d)" % (len(original), len(new))
    after = os.stat(path)
    if (before.st_mode & 0o777) != (after.st_mode & 0o777):
        return "mode changed %o -> %o" % (before.st_mode & 0o777, after.st_mode & 0o777)
    if before.st_ino != after.st_ino:
        return "inode changed (a live writer would now be orphaned)"
    if path.endswith((".jsonl", ".json")):
        for i, line in enumerate(new.split(b"\n"), 1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except Exception as exc:
                return "line %d no longer parses as JSON (%s)" % (i, exc)
            if path.endswith(".json"):
                break  # whole-file JSON: one parse of the first chunk is not enough
        if path.endswith(".json"):
            try:
                json.loads(new)
            except Exception as exc:
                return "file no longer parses as JSON (%s)" % exc
    return None


def process(path: str, args: argparse.Namespace, secret: bytes | None,
            pattern: re.Pattern) -> tuple[int, int, str]:
    """Returns (redactable_hits, report_only_hits, note)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except (OSError, IOError) as exc:
        return 0, 0, "skipped (%s)" % exc

    if declares_corpus(data) and not args.no_corpus_skip:
        return 0, 0, "SKIPPED: declared test corpus (--no-corpus-skip to scan it anyway)"

    spans: list[tuple[int, bytes]] = []
    report_only: list[tuple[int, bytes, str]] = []
    filtered: list[tuple[int, bytes, str]] = []

    if secret:
        start = 0
        while True:
            idx = data.find(secret, start)
            if idx < 0:
                break
            spans.append((idx, secret))
            start = idx + len(secret)
    else:
        accepted, filtered = scan_bytes(data, pattern, include_assignments=True)
        for off, tok, kind in accepted:
            if args.sha256 and not hashlib.sha256(tok).hexdigest().startswith(args.sha256.lower()):
                continue
            if kind == "assignment" and not args.include_assignments:
                report_only.append((off, tok, kind))
                continue
            spans.append((off, tok))

    tail = ""
    if filtered:
        tail += "; %d shape-alike filtered" % len(filtered)
        if not args.explain_filtered:
            tail += " (--explain-filtered to see why)"
    if report_only:
        tail += "; %d assignment hit(s) REPORT-ONLY (--include-assignments to redact)" % len(report_only)

    if args.explain_filtered:
        for off, tok, reason in filtered:
            print("      filtered @%-9d %-28s %s"
                  % (off, tok[:26].decode("ascii", "replace"), reason))
    for off, tok, _ in report_only:
        print("      assignment @%-7d %-28s sha=%s"
              % (off, tok[:6].decode("ascii", "replace") + b"\xe2\x80\xa6".decode(),
                 hashlib.sha256(tok).hexdigest()[:8]))

    if not spans:
        return 0, len(report_only), ("clean" + tail if tail else "clean")
    if args.scan_only:
        shapes = sorted({(t[:6].decode("ascii", "replace"), len(t), hashlib.sha256(t).hexdigest()[:8])
                         for _, t in spans})
        return len(spans), len(report_only), "would redact %d: %s%s" % (
            len(spans),
            ", ".join("%s… len=%d sha=%s" % s for s in shapes),
            tail,
        )

    before = os.stat(path)
    fd, backup = tempfile.mkstemp(prefix="redact-", suffix=".bak")
    os.close(fd)
    shutil.copy2(path, backup)
    os.chmod(backup, 0o600)
    try:
        with open(path, "r+b") as fh:
            for off, tok in spans:
                repl = placeholder_for(tok)
                assert len(repl) == len(tok)
                fh.seek(off)
                fh.write(repl)
            fh.flush()
            os.fsync(fh.fileno())
        with open(path, "rb") as fh:
            new = fh.read()
        reason = verify(path, data, new, before)
        if reason is None and secret and secret in new:
            reason = "secret still present after write"
        if reason is not None:
            shutil.copy2(backup, path)
            return 0, 0, "ROLLED BACK: %s" % reason
        return len(spans), len(report_only), "redacted %d (mode %o, inode intact)%s" % (
            len(spans), before.st_mode & 0o777, tail)
    finally:
        os.unlink(backup)


# --------------------------------------------------------------------------- #
# Self-test corpus. It lives OUTSIDE this file (tests/fixtures/scan-corpus.txt)
# so that sweeping this repo does not keep reporting the fixtures' own
# credential-shaped samples. The corpus file declares itself with a magic first
# line; a file carrying that line is reported as SKIPPED rather than scanned --
# visibly, in the output, and only until you pass --no-corpus-skip. Nothing is
# ever silently excluded from a secret scan.
#
# The MUST-NOT-MATCH half is self-policing: anything credible parked there fails
# the self-test as a false positive, so a real key cannot hide in that section.
# The MUST-MATCH half holds TEMPLATES, not literals (see expand_sample below), so
# it cannot hold one either -- and tests/ enforces that by scanning the corpus
# with --no-corpus-skip and requiring zero token hits.
# --------------------------------------------------------------------------- #
CORPUS_MAGIC = b"#!redact-secret-corpus"

# Corpus samples carry key SHAPES as templates ({A:n} etc.), never as literal
# key-shaped runs. Three reasons, in order of how much they bit:
#   1. GitHub push protection rejected this very file when the shapes were
#      literal -- it read the synthetic sk_live_/xoxb- fixtures as a live Stripe
#      and Slack key. A test corpus you cannot push is not a test corpus.
#   2. A file that holds no key-shaped literal cannot hold a leaked credential,
#      which removes the one place a real key could have hidden here.
#   3. Any other secret scanner (a CI job, a pre-commit hook, this tool itself)
#      is likewise free of false alarms on our fixtures.
# The expansion is deterministic, so the bytes the self-test scans are fixed.
_TEMPLATE_ALPHABETS = {
    b"A": b"aB3cD4eF5gH6iJ7kL8mN9pQ0rS1tU2vW",   # mixed: >=2 char classes
    b"U": b"QWERTYUIOPASDFGHJKLZXCVBNM",         # upper, as AWS uses
    b"L": b"qwertyuiopasdfghjklzxcvbnm",         # lower only, for the opaque-run case
    b"D": b"9174035826",                         # digits, deliberately non-sequential
    b"H": b"9a1f7b3e5c2d8046",                   # lowercase hex
}
_TEMPLATE_RE = re.compile(rb"\{([AULDH]):(\d{1,3})\}")


def expand_sample(sample: bytes) -> bytes:
    """Expand {A:n}/{U:n}/{L:n}/{D:n}/{H:n} into deterministic filler."""
    def sub(m: "re.Match[bytes]") -> bytes:
        alphabet = _TEMPLATE_ALPHABETS[m.group(1)]
        n = int(m.group(2))
        reps = -(-n // len(alphabet))
        return (alphabet * reps)[:n]
    return _TEMPLATE_RE.sub(sub, sample)
DEFAULT_CORPUS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
    "tests", "fixtures", "scan-corpus.txt",
)
_MUST_MATCH_HEADER = b"MUST-MATCH"
_MUST_NOT_HEADER = b"MUST-NOT-MATCH"


def declares_corpus(data: bytes) -> bool:
    """True if these bytes open with the corpus magic line."""
    return data[:200].lstrip().startswith(CORPUS_MAGIC)


def load_corpus(path: str) -> tuple[list[bytes], list[bytes]]:
    """Parse the corpus file into (must_match, must_not_match).

    Raises rather than returning empty lists: a missing or unparsable corpus must
    fail the self-test loudly, never turn it into a vacuous pass.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    if not declares_corpus(data):
        raise ValueError("%s does not open with %s" % (path, CORPUS_MAGIC.decode()))
    must, must_not, bucket = [], [], None
    for raw in data.split(b"\n"):
        line = raw.rstrip(b"\r")
        stripped = line.lstrip()
        if stripped.startswith(b"#"):
            if _MUST_NOT_HEADER in line:
                bucket = must_not
            elif _MUST_MATCH_HEADER in line:
                bucket = must
            continue
        if not stripped:
            continue
        if bucket is None:
            raise ValueError("sample before any MUST-MATCH/MUST-NOT-MATCH header: %r" % line[:40])
        bucket.append(expand_sample(line))
    if not must or not must_not:
        raise ValueError("corpus is missing a whole section (%d must-match, %d must-not-match)"
                         % (len(must), len(must_not)))
    return must, must_not


def self_test(corpus_path: str) -> int:
    pattern = re.compile(DEFAULT_PATTERN)
    fails: list[str] = []
    try:
        must_match, must_not_match = load_corpus(corpus_path)
    except (OSError, ValueError) as exc:
        print("self-test CANNOT RUN: %s" % exc, file=sys.stderr)
        return 1

    for sample in must_match:
        accepted, _ = scan_bytes(sample, pattern)
        if not accepted:
            fails.append("FALSE NEGATIVE (missed a key): %s"
                         % sample[:44].decode("ascii", "replace"))

    for sample in must_not_match:
        accepted, _ = scan_bytes(sample, pattern)
        if accepted:
            fails.append("FALSE POSITIVE: %-46s -> flagged %s"
                         % (sample[:44].decode("ascii", "replace"),
                            accepted[0][1][:30].decode("ascii", "replace")))

    print("self-test: %d must-match, %d must-not-match, %d failure(s)  [%s]"
          % (len(must_match), len(must_not_match), len(fails), corpus_path))
    for f in fails:
        print("  " + f)
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Redact a secret in place from the files you name. No directory walking, ever.",
        epilog="The secret is never taken as an argument: use --secret - (stdin), --secret-file, or --sha256.",
    )
    ap.add_argument("files", nargs="*", metavar="FILE")
    ap.add_argument("--secret", choices=["-"], help="read the literal secret from stdin")
    ap.add_argument("--secret-file", help="read the literal secret from this file")
    ap.add_argument("--sha256", help="redact tokens whose sha256 hex starts with this prefix")
    ap.add_argument("--all-matches", action="store_true", help="redact every token-shaped match")
    ap.add_argument("--pattern", help="override the token regex (bytes regex)")
    ap.add_argument("--scan-only", action="store_true", help="report what would change; write nothing")
    ap.add_argument("--include-assignments", action="store_true",
                    help="also redact password=/token= VALUES (report-only by default)")
    ap.add_argument("--explain-filtered", action="store_true",
                    help="list near-misses that were suppressed, with the reason")
    ap.add_argument("--self-test", action="store_true",
                    help="run the must-match / must-not-match corpus and exit")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS,
                    help="path to the self-test corpus (default: %(default)s)")
    ap.add_argument("--no-corpus-skip", action="store_true",
                    help="scan a declared test-corpus file instead of reporting it SKIPPED")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test(args.corpus)
    if not args.files:
        print("no files named (or pass --self-test)", file=sys.stderr)
        return 2

    secret = read_secret(args)
    if secret is not None and len(secret) < MIN_SECRET_LEN:
        print("refusing: secret shorter than %d bytes would match too much" % MIN_SECRET_LEN, file=sys.stderr)
        return 2
    if secret is None and not (args.sha256 or args.all_matches or args.scan_only):
        print("nothing to look for: pass --secret -, --secret-file, --sha256, --all-matches or --scan-only", file=sys.stderr)
        return 2

    pattern = re.compile(args.pattern.encode() if args.pattern else DEFAULT_PATTERN)

    total, reported, failures = 0, 0, 0
    for path in args.files:
        if os.path.isdir(path):
            print("  %-58s skipped (a directory — name the files you mean)" % path)
            continue
        n, r, note = process(path, args, secret, pattern)
        total += n
        reported += r
        if note.startswith("ROLLED BACK"):
            failures += 1
        print("  %-58s %s" % (path if len(path) < 58 else "…" + path[-57:], note))

    verb = "would redact" if args.scan_only else "redacted"
    print("%s %d occurrence(s) across %d named file(s)%s%s"
          % (verb, total, len(args.files),
             "; %d report-only assignment hit(s)" % reported if reported else "",
             "; %d rolled back" % failures if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
