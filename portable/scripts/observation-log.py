#!/usr/bin/env python3
"""observation-log.py — locate the task-observer observation log, wherever this user keeps it.

task-observer is a SOFT dependency of audit-loose-ends: this resolves its workspace and log layout
so the audit and harvest-lessons steps never hardcode one machine's path. Read-only.

Resolution order (first hit wins):
  1. $TASK_OBSERVER_WORKSPACE/skill-observations/   — an explicitly pinned root
  2. ~/.claude/skill-observations/                   — the user-scope default (task-observer 3.x)
  3. ~/.claude/projects/*/skill-observations/        — the legacy per-project anchor (pre-3.x);
                                                       more than one is reported as a shard

Layout, per workspace:
  per-file  observation-log/NNNN-slug.md, one file per observation (task-observer >= 3.0)
  legacy    a single log.md with "### Observation N:" headers (task-observer < 3.0)

Usage:
  observation-log.py            print "<layout>\\t<path>" (path = the log dir or log.md);
                                prints "none" and exits 0 when there is no workspace at all,
                                so a caller can skip the step silently
  observation-log.py --open     also list OPEN observations (id and title) from that log
  observation-log.py --help     this text

Environment:
  TASK_OBSERVER_WORKSPACE   root holding skill-observations/ (the same variable task-observer's
                            own scripts/new-observation.sh reads)
  HOME                      base for the default and legacy locations

Exit status: 0 when resolved or absent; 2 on an unrecognised option.
"""
import glob
import os
import re
import sys


def candidates():
    pinned = os.environ.get("TASK_OBSERVER_WORKSPACE")
    if pinned:
        yield os.path.join(os.path.expanduser(pinned), "skill-observations")
    home = os.path.expanduser("~")
    yield os.path.join(home, ".claude", "skill-observations")
    for d in sorted(glob.glob(os.path.join(home, ".claude", "projects", "*", "skill-observations"))):
        yield d


def layout_of(ws):
    per_file = os.path.join(ws, "observation-log")
    if os.path.isdir(per_file):
        return "per-file", per_file
    legacy = os.path.join(ws, "log.md")
    if os.path.isfile(legacy):
        return "legacy", legacy
    return None, None


def resolve():
    """(layout, path, extra_legacy_hits). The legacy glob is only consulted when nothing better
    exists, and every further legacy hit is returned so the caller can report the shard."""
    hits = []
    for ws in candidates():
        kind, path = layout_of(ws)
        if kind:
            hits.append((kind, path))
    if not hits:
        return None, None, []
    return hits[0][0], hits[0][1], [p for k, p in hits[1:] if k == "legacy"]


def _frontmatter(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        if fh.readline().strip() != "---":
            return {}
        out = {}
        for line in fh:
            if line.strip() == "---":
                break
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip()] = v.strip().strip('"')
        return out


def open_items(kind, path):
    if kind == "per-file":
        for f in sorted(glob.glob(os.path.join(path, "*.md"))):
            fm = _frontmatter(f)
            if fm.get("status", "open").lower() == "open":  # no status = OPEN, as task-observer rules
                yield fm.get("id", os.path.basename(f)[:4]), fm.get("title", os.path.basename(f))
    else:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for m in re.finditer(r"^### Observation (\d+): (.+?)\n(.*?)(?=^### Observation |\Z)",
                             text, re.S | re.M):
            st = re.search(r"^\*\*Status:\*\*\s*(\w+)", m.group(3), re.M)
            if not st or st.group(1).upper() == "OPEN":
                yield m.group(1), m.group(2).strip()


def main(argv):
    if "--help" in argv or "-h" in argv:
        print((__doc__ or "").strip())
        return 0
    unknown = [a for a in argv if a != "--open"]
    if unknown:
        print("observation-log.py: unrecognised option: %s" % " ".join(unknown), file=sys.stderr)
        print("Try 'observation-log.py --help'.", file=sys.stderr)
        return 2
    kind, path, shards = resolve()
    if not kind:
        print("none")
        return 0
    print(f"{kind}\t{path}")
    for s in shards:
        print(f"shard\t{s}\t(a second legacy log — task-observer's migration consolidates these)")
    if "--open" in argv:
        for oid, title in open_items(kind, path):
            print(f"open\t{oid}\t{title}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
