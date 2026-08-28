#!/usr/bin/env bash
# Framework-free test for scripts/redact-secret.py.
#
# The point of this file is that the scanner's no-false-negative property must be
# VERIFIED, not asserted: the script carries a must-match / must-not-match corpus
# (seeded with real false positives that improvised greps produced) and runs it
# through the same scan_bytes() the tool itself uses. This test also mutates the
# filter to prove the corpus can actually fail.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCANNER="$HERE/../scripts/redact-secret.py"
fail=0
check() { if [ "$1" = 0 ]; then echo "  ok: $2"; else echo "  FAIL: $2"; fail=1; fi; }

# 1) the shipped corpus passes
OUT="$(python3 "$SCANNER" --self-test 2>&1)"; rc=$?
check $rc "--self-test exits 0"
case "$OUT" in *"0 failure(s)"*) check 0 "corpus reports 0 failures";; *) check 1 "corpus reports 0 failures ($OUT)";; esac

# 2) the corpus is non-trivial
python3 - "$SCANNER" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rs", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
must, must_not = m.load_corpus(m.DEFAULT_CORPUS)
assert len(must) >= 20, "must-match corpus too small (%d)" % len(must)
assert len(must_not) >= 20, "must-not-match corpus too small (%d)" % len(must_not)
PY
check $? "corpus has >=20 samples on each side"

# 3) MUTATION: removing the L1 word-boundary must break the corpus. A suite that
#    cannot fail proves nothing.
python3 - "$SCANNER" <<'PY'
import importlib.util, re, sys
spec = importlib.util.spec_from_file_location("rs", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
_, must_not = m.load_corpus(m.DEFAULT_CORPUS)
mutated = re.compile(m.DEFAULT_PATTERN.replace(rb"(?<![A-Za-z0-9])", rb""))
flagged = [s for s in must_not if m.scan_bytes(s, mutated)[0]]
assert flagged, "removing the L1 boundary changed nothing -- the corpus is not exercising it"
PY
check $? "mutating away L1 makes the corpus fail"

# 3b) the corpus file is EXEMPT BUT VISIBLE: announced as SKIPPED, scannable on demand
CORPUS="$HERE/fixtures/scan-corpus.txt"
[ -f "$CORPUS" ]; check $? "corpus file exists at tests/fixtures/scan-corpus.txt"
SKIP="$(python3 "$SCANNER" --scan-only "$CORPUS")"
case "$SKIP" in *"SKIPPED: declared test corpus"*) check 0 "corpus announced as SKIPPED, not silently ignored";; *) check 1 "corpus skip is not announced ($SKIP)";; esac
FORCED="$(python3 "$SCANNER" --scan-only --no-corpus-skip "$CORPUS")"
case "$FORCED" in *"occurrence(s)"*) check 0 "--no-corpus-skip scans it anyway";; *) check 1 "--no-corpus-skip did not scan it ($FORCED)";; esac
# and when scanned, it must contain NO key-shaped literal: shapes are templates,
# so the file cannot hold a leaked credential and cannot trip push protection.
case "$FORCED" in *"would redact 0 occurrence"*) check 0 "corpus holds no key-shaped literal (templates only)";; *) check 1 "corpus contains a literal key-shaped run ($FORCED)";; esac
# the templates must actually expand to the shapes, or the corpus is testing nothing
python3 - "$SCANNER" <<'PYX'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rs", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
assert m.expand_sample(b"sk-{A:48}") != b"sk-{A:48}", "templates are not expanding"
assert len(m.expand_sample(b"AKIA{U:16}")) == 20, "expansion length wrong"
assert m.expand_sample(b"sk-{A:8}") == m.expand_sample(b"sk-{A:8}"), "expansion not deterministic"
PYX
check $? "templates expand deterministically to the right length"

# 3c) a missing or undeclared corpus must FAIL --self-test, never vacuously pass
python3 "$SCANNER" --self-test --corpus /nonexistent/corpus.txt >/dev/null 2>&1
[ $? -ne 0 ]; check $? "a missing corpus fails --self-test loudly"
BADC="$(mktemp -t badcorpus)"
printf 'sk-notdeclared\n' > "$BADC"
python3 "$SCANNER" --self-test --corpus "$BADC" >/dev/null 2>&1
[ $? -ne 0 ]; check $? "an undeclared corpus file fails --self-test"
rm -f "$BADC"

# 4) --scan-only writes nothing, and finds a planted synthetic key
TMP="$(mktemp -t redactprobe)"; trap 'rm -f "$TMP"' EXIT
python3 -c 'print("token is sk-ant-api03-" + "Ab3"*31 + "xy")' > "$TMP"
printf 'task-specific, on-disk cache, --password, max_tokens=8192\n' >> "$TMP"
SUM_BEFORE="$(shasum "$TMP" | cut -d' ' -f1)"
SCAN="$(python3 "$SCANNER" --scan-only "$TMP")"
case "$SCAN" in *"would redact 1"*) check 0 "finds the planted key";; *) check 1 "finds the planted key ($SCAN)";; esac
case "$SCAN" in *"would redact 1:"*) check 0 "does not flag the four known false positives";; *) check 1 "false positives leaked in";; esac
[ "$SUM_BEFORE" = "$(shasum "$TMP" | cut -d' ' -f1)" ]
check $? "--scan-only left the file byte-identical"

# 5) redaction keeps the inode and the mode (safe for a live transcript)
INO_BEFORE="$(stat -f '%i %Lp' "$TMP" 2>/dev/null || stat -c '%i %a' "$TMP")"
python3 "$SCANNER" --all-matches "$TMP" >/dev/null
INO_AFTER="$(stat -f '%i %Lp' "$TMP" 2>/dev/null || stat -c '%i %a' "$TMP")"
[ "$INO_BEFORE" = "$INO_AFTER" ]
check $? "redaction preserved inode and mode"
grep -q 'sk-REDACTED' "$TMP"; check $? "the key was replaced by a same-length placeholder"
python3 "$SCANNER" --scan-only "$TMP" | grep -q 'clean'
check $? "re-scanning a redacted file is clean (no placeholder re-flagging)"

[ "$fail" = 0 ] && echo "ALL PASS" || { echo "FAILURES"; exit 1; }
