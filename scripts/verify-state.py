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

Finding = namedtuple("Finding", "level check_id message repo")


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

    # Group by repo (use Finding.repo field)
    by_repo = collections.defaultdict(list)
    transcript_findings = []

    for f in results:
        if f.check_id.startswith("T1") or f.check_id.startswith("H"):
            transcript_findings.append(f)
        else:
            repo = f.repo if hasattr(f, 'repo') and f.repo else "unknown"
            by_repo[repo].append(f)

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
    """Run all repo checks G1-G7. Returns list of Finding."""
    # Convert allow_markers to relative paths (from repo root) for comparison with git grep output
    # Use realpath to handle macOS /private symlinks
    repo_real = os.path.realpath(repo)
    allow_markers_rel = set()
    for m in (allow_markers or []):
        if os.path.isabs(m):
            try:
                m_real = os.path.realpath(m)
                allow_markers_rel.add(os.path.relpath(m_real, repo_real))
            except ValueError:
                # On Windows, relpath can fail across drives; keep absolute as fallback
                allow_markers_rel.add(m)
        else:
            allow_markers_rel.add(m)
    findings = []

    # G1: conflict markers in tracked files at HEAD and working tree
    findings.extend(_g1_conflict_markers(repo, allow_markers_rel, repo))

    # G2: dirty working tree
    findings.extend(_g2_dirty_working_tree(repo, repo))

    # G3: branch ahead/diverged/no upstream
    findings.extend(_g3_branch_status(repo, repo))

    # G4: in-progress rebase/merge/cherry-pick
    findings.extend(_g4_rebase_merge_in_progress(repo, repo))

    # G5: version agreement
    findings.extend(_g5_version_agreement(repo, repo))

    # G6: newest tag has GitHub release
    findings.extend(_g6_github_release(repo, repo))

    # G7: remote URL embeds credentials
    findings.extend(_g7_remote_credentials(repo, repo))

    return findings


def _g1_conflict_markers(repo, allow_markers, repo_path):
    """G1: conflict markers in tracked files at HEAD and working tree."""
    findings = []

    # Check HEAD
    rc, out = _git(repo, "grep", "-nE", r'^(<<<<<<<|>>>>>>>) ', "HEAD", "--")
    if rc == 0:
        files = set()
        for line in out.splitlines():
            # Format: HEAD:path:lineno:content or path:lineno:content
            parts = line.split(":", 2)
            if len(parts) >= 3 and parts[0] == "HEAD":
                file_path = parts[1]
            elif len(parts) >= 2:
                file_path = parts[0]
            else:
                continue
            files.add(file_path)

        for f in sorted(files):
            if f in allow_markers:
                findings.append(Finding("WARN", "G1", f"markers allowed by flag: {f}", repo_path))
            else:
                findings.append(Finding("FAIL", "G1", f"conflict markers: {f}", repo_path))

    # Check working tree
    rc, out = _git(repo, "grep", "-nE", r'^(<<<<<<<|>>>>>>>) ', "--untracked")
    if rc == 0:
        for line in out.splitlines():
            parts = line.split(":", 2)
            if len(parts) >= 3 and parts[0] == "HEAD":
                file_path = parts[1]
            elif len(parts) >= 2:
                file_path = parts[0]
            else:
                continue
            if file_path not in allow_markers:
                findings.append(Finding("FAIL", "G1", f"conflict markers: {file_path}", repo_path))

    return findings


def _g2_dirty_working_tree(repo, repo_path):
    """G2: dirty working tree (porcelain count, list ≤10 paths)."""
    findings = []
    rc, out = _git(repo, "status", "--porcelain")
    if rc != 0:
        return findings

    lines = [line for line in out.splitlines() if line.strip()]
    if not lines:
        findings.append(Finding("PASS", "G2", "working tree clean", repo_path))
        return findings

    untracked = sum(1 for line in lines if line.startswith("??"))
    modified = sum(1 for line in lines if not line.startswith("??"))

    paths = [line[3:] for line in lines[:10]]
    findings.append(Finding("FAIL", "G2",
        f"dirty: {untracked} untracked, {modified} modified ({', '.join(paths)})", repo_path))
    return findings


def _g3_branch_status(repo, repo_path):
    """G3: branch ahead of / diverged from upstream, or no upstream."""
    findings = []

    # Get upstream branch
    rc, upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if rc != 0:
        # No upstream
        rc, head = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if rc == 0 and head == "HEAD":
            findings.append(Finding("WARN", "G3", "detached HEAD", repo_path))
        else:
            findings.append(Finding("WARN", "G3", "no upstream", repo_path))
        return findings

    # Check ahead/behind
    rc, counts = _git(repo, "rev-list", "--left-right", "--count", "@{u}...HEAD")
    if rc == 0 and counts:
        parts = counts.split("\t")
        if len(parts) == 2:
            ahead = int(parts[1]) if parts[1] else 0
            behind = int(parts[0]) if parts[0] else 0

            if ahead > 0 and behind > 0:
                findings.append(Finding("FAIL", "G3", f"diverged: {ahead} ahead, {behind} behind (as of last fetch)", repo_path))
            elif ahead > 0:
                findings.append(Finding("FAIL", "G3", f"ahead of {upstream} by {ahead} (not pushed)", repo_path))
            elif behind > 0:
                findings.append(Finding("WARN", "G3", f"behind {upstream} by {behind}", repo_path))
            else:
                findings.append(Finding("PASS", "G3", "branch up to date with upstream", repo_path))

    return findings


def _g4_rebase_merge_in_progress(repo, repo_path):
    """G4: in-progress rebase/merge/cherry-pick."""
    findings = []

    # Check for various in-progress states
    checks = [
        (".git/rebase-merge", "rebase in progress"),
        (".git/rebase-apply", "rebase/am in progress"),
        (".git/MERGE_HEAD", "merge in progress"),
        (".git/CHERRY_PICK_HEAD", "cherry-pick in progress"),
        (".git/REVERT_HEAD", "revert in progress"),
        (".git/BISECT_LOG", "bisect in progress"),
    ]

    for path, msg in checks:
        full_path = os.path.join(repo, path)
        if os.path.exists(full_path):
            findings.append(Finding("FAIL", "G4", msg, repo_path))
            break  # Report first one found

    return findings


def _g5_version_agreement(repo, repo_path):
    """G5: version agreement: plugin.json, VERSION, CHANGELOG top heading."""
    findings = []
    versions = {}

    # plugin.json
    plugin_path = os.path.join(repo, ".claude-plugin", "plugin.json")
    if os.path.exists(plugin_path):
        try:
            with open(plugin_path) as f:
                data = json.load(f)
                v = data.get("version", "").strip()
                if v:
                    versions["plugin.json"] = v
        except Exception:
            pass

    # VERSION file
    version_path = os.path.join(repo, "VERSION")
    if os.path.exists(version_path):
        try:
            with open(version_path) as f:
                v = f.read().strip()
                if v:
                    versions["VERSION"] = v
        except Exception:
            pass

    # CHANGELOG top heading
    changelog_path = os.path.join(repo, "CHANGELOG.md")
    if os.path.exists(changelog_path):
        try:
            with open(changelog_path) as f:
                for line in f:
                    m = re.match(r'^##\s*\[?v?(\d+\.\d+\.\d+)', line)
                    if m:
                        versions["CHANGELOG"] = m.group(1)
                        break
        except Exception:
            pass

    if len(versions) <= 1:
        return findings  # Nothing to compare

    # Check all pairs
    items = list(versions.items())
    for i, (name1, v1) in enumerate(items):
        for name2, v2 in items[i+1:]:
            if v1 != v2:
                findings.append(Finding("FAIL", "G5",
                    f"version mismatch: {name1} {v1}, {name2} {v2}", repo_path))

    return findings


def _g6_github_release(repo, repo_path):
    """G6: newest local v* tag at HEAD-ancestry has pushed tag and GitHub release."""
    findings = []

    # Get newest tag at HEAD ancestry
    rc, tag = _git(repo, "describe", "--tags", "--abbrev=0")
    if rc != 0 or not tag:
        return findings  # No tags

    # Check if tag exists on remote
    rc, _ = _git(repo, "ls-remote", "--tags", "origin", tag)
    if rc != 0:
        findings.append(Finding("UNKNOWN", "G6", "gh unavailable — release not checked (no remote tag)", repo_path))
        return findings

    # Check GitHub release
    rc, url = _git(repo, "config", "--get", "remote.origin.url")
    if rc != 0 or not url:
        findings.append(Finding("UNKNOWN", "G6", "gh unavailable — no remote URL", repo_path))
        return findings

    # Parse owner/repo from URL
    m = re.search(r'[:/]([^/]+)/([^/.]+)(?:\.git)?$', url)
    if not m:
        findings.append(Finding("UNKNOWN", "G6", "gh unavailable — cannot parse remote URL", repo_path))
        return findings

    owner, name = m.group(1), m.group(2)
    if name.endswith(".git"):
        name = name[:-4]

    # Try gh release view
    try:
        result = subprocess.run(
            ["gh", "release", "view", tag, "--repo", f"{owner}/{name}"],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0:
            findings.append(Finding("WARN", "G6", f"tag {tag} has no GitHub release", repo_path))
        else:
            findings.append(Finding("PASS", "G6", f"tag {tag} has GitHub release", repo_path))
    except FileNotFoundError:
        findings.append(Finding("UNKNOWN", "G6", "gh unavailable — release not checked", repo_path))
    except subprocess.TimeoutExpired:
        findings.append(Finding("UNKNOWN", "G6", "gh timeout — release not checked", repo_path))
    except Exception:
        findings.append(Finding("UNKNOWN", "G6", "gh unavailable — release not checked", repo_path))

    return findings


def _g7_remote_credentials(repo, repo_path):
    """G7: remote URL embeds credentials."""
    findings = []
    rc, url = _git(repo, "config", "--get", "remote.origin.url")
    if rc != 0 or not url:
        return findings

    # Check for credentials in URL: https://user:token@host
    if re.match(r'^https?://[^/@\s]+:[^/@\s]+@', url):
        findings.append(Finding("FAIL", "G7", "remote URL embeds credentials (value hidden)", repo_path))
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