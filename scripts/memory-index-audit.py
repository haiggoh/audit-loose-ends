#!/usr/bin/env python3
"""Audit MEMORY.md: the always-on index budget, orphans, and past-state candidates.

Read-only. Reports; never edits. MEMORY.md is injected every session and is silently
TRUNCATED past a byte limit, so its tail entries stop existing as far as recall is
concerned. This flags what is eating the budget.

Usage:
  memory-index-audit.py [--dir DIR] [--limit BYTES] [--top N] [--stale-desc] [--json]

Options:
  --dir DIR      memory directory (default: derived from cwd; falls back to $HOME)
  --limit BYTES  read limit to measure headroom against (default: 24400)
  --top N        how many longest index lines to list (default: 10)
  --stale-desc   also flag memories whose BODY says CORRECTED/SUPERSEDED but whose
                 frontmatter description does not - recall matches the description, so a
                 stale one means the WRONG version is what gets retrieved
  --reviewed FILE  optional file listing reviewed memory filenames (one per line);
                   also checks frontmatter `metadata.stale_desc_reviewed: <reason>`
  --json         machine-readable output
  -h, --help     this help

Exit: 0 ok, 1 over the limit or orphans found.
"""
import argparse, json, os, re, sys

# a line whose value is mostly dated status rather than a recall hook
PAST_STATE = re.compile(r'\b(SHIPPED|RESOLVED|DONE|SUPERSEDED|RETIRED|FIXED|v?\d+\.\d+\.\d+|'
                        r'commit [0-9a-f]{7}|\d{2}-\d{2})\b')

def project_dir_from_cwd(cwd):
    """Derive the encoded project directory from cwd, same encoding as Claude Code."""
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        rel = cwd[len(home):].lstrip("/")
        if rel:
            encoded = "-Users-" + rel.replace("/", "-")
            return os.path.join(home, ".claude", "projects", encoded)
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", "-Users-" + os.getenv("USER", "user"))

def load_reviewed(path):
    """Load reviewed filenames from a file (one per line, # comments allowed)."""
    reviewed = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                # Strip inline comments first, then whitespace
                line = line.split("#")[0].strip()
                if line:
                    reviewed.add(line)
    except OSError:
        pass
    return reviewed


def load_frontmatter_reviewed(d, on_disk):
    """Load reviewed status from frontmatter of memory files themselves.

    A memory can declare `metadata.stale_desc_reviewed: <reason>` in its frontmatter
    to suppress the stale-desc flag without needing an external file. This keeps
    the reason next to the memory and needs no hidden side file.
    """
    reviewed = set()
    for f in on_disk:
        fp = os.path.join(d, f)
        try:
            with open(fp, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError:
            continue
        # Check frontmatter for stale_desc_reviewed
        if re.search(r'^metadata:\s*$', body, re.M):
            # Look for stale_desc_reviewed under metadata
            if re.search(r'^  stale_desc_reviewed:\s*.+$', body, re.M):
                reviewed.add(f)
    return reviewed

def check_stale_description(d, f, reviewed_set):
    """Check if a memory file has a body correction but description doesn't reflect it."""
    try:
        with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError:
        return False
    m = re.search(r'^description:\s*(.*)$', body, re.M)
    if not m:
        return False
    desc = m.group(1)
    # body announces a correction; does the recall hook mention one?
    if f in reviewed_set:
        return False
    if re.search(r'\b(CORRECTED|SUPERSEDED|NO LONGER|now WRONG|REFUTED)\b', body) and \
       not re.search(r'\b(?:CORRECTED|CORRECTION|SUPERSEDED|RETIRED|RESOLVED)\b|⚠|✅', desc):
        return True
    return False

def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--dir", default=None)  # None means auto-derive
    ap.add_argument("--limit", type=int, default=24400)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stale-desc", action="store_true")
    ap.add_argument("--reviewed", default=None)
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.help:
        print(__doc__); return 0

    # Derive default directory from cwd
    if a.dir:
        d = os.path.expanduser(a.dir)
    else:
        d = os.path.join(project_dir_from_cwd(os.getcwd()), "memory")

    idx_path = os.path.join(d, "MEMORY.md")
    if not os.path.isdir(d) or not os.path.isfile(idx_path):
        print("no memory index at %s" % idx_path, file=sys.stderr); return 1

    print("Resolved memory directory: %s" % d, file=sys.stderr)

    raw = open(idx_path, encoding="utf-8").read()
    size = len(raw.encode("utf-8"))
    lines = raw.split("\n")

    entries, by_type, longest, past = [], {}, [], []
    linked = set()
    for n, l in enumerate(lines, 1):
        m = re.match(r'- .*?\]\(([^)]+\.md)\)', l)
        if not m:
            continue
        f = m.group(1)
        linked.add(f)
        t = "?"
        fp = os.path.join(d, f)
        if os.path.isfile(fp):
            for bl in open(fp, encoding="utf-8", errors="replace"):
                if bl.startswith("  type:"):
                    t = bl.split(":", 1)[1].strip(); break
        else:
            t = "MISSING-FILE"
        w = len(l.encode("utf-8")) + 1
        entries.append((n, f, t, w))
        by_type.setdefault(t, [0, 0])
        by_type[t][0] += 1; by_type[t][1] += w
        longest.append((w, n, f))
        hits = PAST_STATE.findall(l)
        if t == "project" and len(hits) >= 2:
            past.append((w, n, f, sorted(set(hits))[:5]))

    # every inline link, not just entry-position ones
    all_links = set(re.findall(r'\]\(([^)]+\.md)\)', raw))
    on_disk = {f for f in os.listdir(d) if f.endswith(".md") and f != "MEMORY.md"}
    orphans = sorted(on_disk - all_links)
    broken = sorted(f for f in all_links if not os.path.isfile(os.path.join(d, f)))

    # Load reviewed set from file (if provided)
    reviewed_set = set()
    if a.reviewed:
        reviewed_set = load_reviewed(a.reviewed)

    # Also load from frontmatter of memory files
    reviewed_set |= load_frontmatter_reviewed(d, on_disk)

    stale_desc = []
    if a.stale_desc:
        for f in sorted(on_disk):
            result = check_stale_description(d, f, reviewed_set)
            if result:
                stale_desc.append(f)

    longest.sort(reverse=True); past.sort(reverse=True)
    head = size - a.limit

    if a.json:
        print(json.dumps({"bytes": size, "limit": a.limit, "headroom": -head,
                          "entries": len(entries), "by_type": by_type,
                          "orphans": orphans, "broken": broken, "stale_desc": stale_desc,
                          "past_state": [{"line": n, "file": f, "bytes": w, "markers": mk}
                                          for w, n, f, mk in past]}, indent=2))
    else:
        state = "OVER by %d" % head if head > 0 else "%d bytes headroom" % -head
        print("MEMORY.md  %d bytes vs limit %d  -> %s" % (size, a.limit, state))
        print("           %d indexed entries\n" % len(entries))
        print("INDEX WEIGHT BY TYPE (project = most likely past-state)")
        for t, (n, b) in sorted(by_type.items(), key=lambda x: -x[1][1]):
            print("  %-12s %3d entries %6d b  %4.1f%%  (avg %d)"
                  % (t, n, b, 100.0 * b / max(size, 1), b // max(n, 1)))
        print("\nLONGEST INDEX LINES (a line is a recall hook, not a changelog)")
        for w, n, f in longest[:a.top]:
            print("  %4d b  line %3d  %s" % (w, n, f))
        if past:
            print("\nPAST-STATE CANDIDATES: project entries whose line reads as dated status.")
            print("Before trimming, confirm the detail is in the BODY (free, dormant) or the repo.")
            for w, n, f, mk in past[:a.top]:
                print("  %4d b  line %3d  %-46s %s" % (w, n, f, ",".join(mk)))
        if stale_desc:
            print("\n⚠ BODY ANNOUNCES A CORRECTION, DESCRIPTION DOES NOT — recall matches"
                  " the description, so the SUPERSEDED version is what gets retrieved:")
            for f in stale_desc: print("   ", f)
        if orphans:
            print("\n⚠ UNINDEXED (invisible to recall - functionally nonexistent):")
            for f in orphans: print("   ", f)
        if broken:
            print("\n⚠ BROKEN LINKS (no such file):")
            for f in broken: print("   ", f)
        if not orphans and not broken:
            print("\n✓ no orphans, no broken links")
    return 1 if (head > 0 or orphans or broken) else 0

if __name__ == "__main__":
    sys.exit(main())