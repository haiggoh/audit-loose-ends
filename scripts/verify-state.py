#!/usr/bin/env python3
"""verify-state.py — deterministic repo state verification for audit-loose-ends.

Reads LIVE state (git repos, tests evidence, no-hidden-changes traps) and prints a
fixed-format VERDICT block with exit code 0/1. Zero writes.
"""

import argparse
import collections
import json
import os
import re
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

Finding = namedtuple("Finding", "level check_id message")


def _git(repo, *args, timeout=20):
    """Run git command in repo, prepend --no-optional-locks. Returns (rc, stdout)."""
    cmd = ["git", "-C", repo, "--no-optional-locks"] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, ""
    except Exception:
        return -1, ""


def _detect_no_hidden_changes():
    """Detect if no-hidden-changes is installed and enabled."""
    try:
        plugins_path = os.path.expanduser("~/.claude/plugins/installed_plugins.json")
        settings_path = os.path.expanduser("~/.claude/settings.json")

        with open(plugins_path) as f:
            plugins = json.load(f)

        with open(settings_path) as f:
            settings = json.load(f)

        for key in plugins:
            if key.startswith("no-hidden-changes@"):
                enabled = settings.get("enabledPlugins", {}).get(key, False)
                if enabled:
                    version = key.split("@")[1] if "@" in key else "unknown"
                    return True, version
        return False, None
    except Exception:
        return False, None


def render(results, nhc_status=""):
    """Render findings in fixed format per D7."""
    lines = ["VERIFY-STATE  (read-only)"]

    # Group by repo
    by_repo = collections.defaultdict(list)
    transcript_findings = []

    for f in results:
        if f.check_id.startswith("T1") or f.check_id.startswith("H"):
            transcript_findings.append(f)
        else:
            # Extract repo from message (format: "repo <path> ...")
            match = re.search(r'repo\s+(\S+)', f.message)
            if match:
                by_repo[match.group(1)].append(f)
            else:
                by_repo["unknown"].append(f)

    for repo, findings in sorted(by_repo.items()):
        lines.append(f"  repo {repo}")
        for f in findings:
            lines.append(f"    {f.level} {f.check_id} {f.message}")

    if transcript_findings:
        lines.append("  transcript")
        for f in transcript_findings:
            lines.append(f"    {f.level} {f.check_id} {f.message}")

    if nhc_status:
        lines.append(f"  nhc: {nhc_status}")

    # Count FAIL/WARN/UNKNOWN
    fail_count = sum(1 for f in results if f.level == "FAIL")
    warn_count = sum(1 for f in results if f.level == "WARN")
    unknown_count = sum(1 for f in results if f.level == "UNKNOWN")

    if fail_count == 0:
        verdict = f"VERDICT: CLEAN — 0 FAIL, {warn_count} WARN, {unknown_count} UNKNOWN"
    else:
        verdict = f"VERDICT: NOT CLEAN — {fail_count} FAIL, {warn_count} WARN, {unknown_count} UNKNOWN"

    lines.append(verdict)
    return "\n".join(lines)


def check_repo(repo, allow_markers=None):
    """Run all repo checks. Returns list of Finding."""
    findings = []
    # Placeholder - will implement G1-G7 in Task 3
    return findings


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="verify-state.py",
        description="Verify repo state for audit-loose-ends. Read-only. Prints a VERDICT: line with FAIL/WARN/UNKNOWN counts.",
        add_help=True
    )
    p.add_argument("--repo", action="append", default=[], help="repo path to check")
    p.add_argument("--from-scan", action="store_true", help="get repos from audit-scan.py --repos-only")
    p.add_argument("--transcript", help="transcript path for T1 checks")
    p.add_argument("--session", help="session ID for --from-scan")
    p.add_argument("--allow-markers", action="append", default=[], help="paths to allow conflict markers")
    p.add_argument("--json", action="store_true", help="JSON output")

    args = p.parse_args(argv)

    # Collect repos
    repos = list(args.repo)

    if args.from_scan:
        scan_script = Path(__file__).parent / "audit-scan.py"
        cmd = [sys.executable, str(scan_script), "--repos-only"]
        if args.session:
            cmd += ["--session", args.session]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        repos.append(line.strip())
        except Exception:
            pass

    # Resolve to top-level
    resolved_repos = []
    for r in repos:
        rc, out = _git(r, "rev-parse", "--show-toplevel")
        if rc == 0:
            resolved_repos.append(out)
        else:
            # Not a git repo, skip with INFO
            pass

    if not resolved_repos:
        # Empty audit
        print("VERDICT: CLEAN — 0 FAIL, 0 WARN, 0 UNKNOWN")
        return 0

    # Detect no-hidden-changes
    nhc_enabled, nhc_version = _detect_no_hidden_changes()
    if nhc_enabled:
        nhc_status = f"detected {nhc_version} (enabled)"
    else:
        nhc_status = "not installed — H-checks skipped"

    # Run checks (placeholder for now)
    all_findings = []
    for repo in resolved_repos:
        all_findings.extend(check_repo(repo, args.allow_markers))

    # Print output
    output = render(all_findings, nhc_status)
    print(output)

    # Exit code per D6
    fail_count = sum(1 for f in all_findings if f.level == "FAIL")
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())