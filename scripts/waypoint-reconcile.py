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

# Import from waypoints_core for shared functions
# The waypoints_core module is in ~/ClaudeWorkspace/waypoints/
WAYPOINTS_ROOT = os.path.expanduser("~/ClaudeWorkspace/waypoints")
sys.path.insert(0, WAYPOINTS_ROOT)
from waypoints_core import (
    load_store, save_store, load_archive, save_archive,
    promote_landed_waiting, stale_waiting, prune,
)

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


def load_waypoints():
    """Load waypoints store."""
    try:
        return load_store(WAYPOINTS_STORE)
    except Exception:
        return {"version": 1, "items": []}


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