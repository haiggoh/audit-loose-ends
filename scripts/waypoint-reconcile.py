#!/usr/bin/env python3
"""waypoint-reconcile.py — deterministic waypoint reconciliation for audit-loose-ends.

Reads the audit-scan.py digest for the session, cross-references with waypoints.json,
and outputs a deterministic list of actions (done, add, release, prune).
The model only relays the script's output verbatim — never authors the verdict.

Usage:
    python3 waypoint-reconcile.py [--session SESSION_ID] [--transcript PATH] [--repo PATH...]
    python3 waypoint-reconcile.py --help
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# waypoints is a SOFT dependency: nothing is imported at load time, so --help and argument errors never
# depend on it, and a machine without waypoints gets "nothing to reconcile", never a crash or a stall.
# The module used to be imported here from one machine's checkout path (ModuleNotFoundError elsewhere,
# even for --help — found 2026-10-31).


def find_waypoints_core():
    """Directory holding the INSTALLED waypoints_core.py, or None when waypoints is not installed.

    WAYPOINTS_CORE_DIR, when set, must hold it (a set-but-wrong override fails loudly, exit 2); otherwise
    the newest waypoints version in the plugin cache — never an older copy left beside it."""
    explicit = os.environ.get("WAYPOINTS_CORE_DIR")
    if explicit is not None:
        if not os.path.isfile(os.path.join(explicit, "waypoints_core.py")):
            print(f"WAYPOINTS_CORE_DIR={explicit} holds no waypoints_core.py", file=sys.stderr)
            raise SystemExit(2)
        return explicit

    def vkey(p):
        return tuple(int(x) if x.isdigit() else 0 for x in p.name.split("."))
    cache = Path(os.path.expanduser("~/.claude/plugins/cache"))
    found = [d for d in cache.glob("*/waypoints/*") if (d / "waypoints_core.py").is_file()]
    return str(max(found, key=vkey)) if found else None


def import_waypoints_core():
    d = find_waypoints_core()
    if d is None:
        return None
    sys.path.insert(0, d)
    import waypoints_core
    return waypoints_core

WAYPOINTS_STORE = os.path.expanduser("~/.claude/waypoints.json")


def run_cmd(cmd, cwd=None, capture=True):
    """Run command and return (rc, stdout, stderr)."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True, timeout=60)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def find_session_transcript(session_id):
    """Find transcript file for session_id."""
    for root in Path(PROJECTS_DIR).glob("*"):
        cand = root / f"{session_id}.jsonl"
        if cand.is_file():
            return str(cand)
    return None


def run_audit_scan(session_id=None, project=None, all_projects=False):
    """Run audit-scan.py and return repos touched and transcript path."""
    script = Path(__file__).parent / "audit-scan.py"
    cmd = ["python3", str(script), "--repos-only"]
    if session_id:
        cmd += ["--session", session_id]
    if project:
        cmd += ["--project", project]
    # Use --all-projects to find session across all projects
    cmd += ["--all-projects"]
    rc, out, err = run_cmd(["python3", str(script), "--repos-only", "--all-projects"])
    if rc != 0:
        return [], None
    repos = [line.strip() for line in out.strip().split("\n") if line.strip()]
    # Also get transcript path
    transcript = None
    if session_id:
        transcript = find_session_transcript(session_id)
    return repos, transcript


def main():
    parser = argparse.ArgumentParser(
        prog="waypoint-reconcile.py",
        description="Reconcile waypoints with audit session work. Outputs deterministic action list.",
        add_help=True
    )
    parser.add_argument("--session", help="session ID for --from-scan")
    parser.add_argument("--transcript", help="explicit transcript path")
    parser.add_argument("--repo", action="append", default=[], help="repo path to check")
    parser.add_argument("--json", action="store_true", help="output JSON instead of text")
    parser.add_argument("--dry-run", action="store_true", help="show what would be done without executing")
    parser.add_argument("--apply", action="store_true", help="actually execute the actions (default is dry-run)")
    args = parser.parse_args()

    # Determine repos and transcript
    repos = list(args.repo)
    transcript_path = args.transcript

    if args.session and not args.repo:
        # Run audit-scan to discover repos and transcript
        repos, transcript = run_audit_scan(session_id=args.session)
        if not transcript_path and transcript:
            transcript_path = transcript

    if not args.repo and not transcript_path:
        print("No repos or transcript specified. Use --repo, --session, or --transcript.", file=sys.stderr)
        return 1

    core = import_waypoints_core()
    if core is None:
        print("waypoints is not installed — nothing to reconcile")
        return 0
    if not os.path.isfile(WAYPOINTS_STORE):
        print(f"no waypoints store at {WAYPOINTS_STORE} — nothing to reconcile")
        return 0
    load_store, save_store = core.load_store, core.save_store
    load_archive, save_archive = core.load_archive, core.save_archive
    promote_landed_waiting, stale_waiting, prune = core.promote_landed_waiting, core.stale_waiting, core.prune

    # Load waypoints
    store = load_store(WAYPOINTS_STORE)
    items = store.get("items", [])

    # 1. Release waiting items whose targets have landed
    archived = load_archive(WAYPOINTS_STORE).get("items", [])
    promoted = promote_landed_waiting(store["items"], archived)
    for it, target, milestone in promoted:
        print(f"  release: [{it['id']}] {it['title']} ← {target} @ {milestone}")

    # 2. Check for stale waiting items
    archived_items = load_archive(WAYPOINTS_STORE).get("items", [])
    stale = stale_waiting(store["items"], archived_items)
    for it, target in stale:
        print(f"  ⚠️ stale: [{it['id']}] {it['title']} → missing target {target}")

    # 2. Prune done items
    kept, archived_batch = prune(store["items"])
    if archived_batch:
        print(f"  prune: {len(archived_batch)} item(s) to archive")

    # If --apply, execute the actions
    if args.apply:
        # Reload fresh
        store = load_store("~/.claude/waypoints.json")

        # Release waiting items whose targets have landed
        archived = load_archive("~/.claude/waypoints.json")["items"]
        promote_landed_waiting(store["items"], archived)

        # Prune done items
        kept, archived_batch = prune(store["items"])
        store["items"] = kept
        # Save archive
        arch = load_archive("~/.claude/waypoints.json")
        existing_ids = {i["id"] for i in arch["items"]}
        for item in archived_batch:
            if item["id"] not in existing_ids:
                arch["items"].append(item)
        save_archive(arch)

        save_store(store)
        print("Actions applied.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())