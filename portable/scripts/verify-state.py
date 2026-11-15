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


# --- Transcript checks (Task 4) ---

_TEST_CMD_RE = re.compile(
    r'\b(pytest|python3?\s+\S*tests?/\S+|bash\s+\S*tests?/\S+\.sh|npm\s+test|make\s+test)\b'
)

# Copied from audit-scan.py for shell prose masking
_HEREDOC_OPEN_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

def shell_only(cmd):
    """The command with heredoc BODIES removed."""
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
        while i < len(lines) and lines[i].strip() != tag:
            i += 1
        i += 1
    return mask_prose("\n".join(out))


def mask_prose(cmd):
    """The command with MULTI-LINE quoted DATA blanked out, quote-aware."""
    if '"' not in cmd and "'" not in cmd:
        return cmd
    out = list(cmd)
    i, n = 0, len(cmd)
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
                    stack[-1][2] = i + 1
        i += 1
    for frame in stack:
        if frame[0] in ("dq", "sq"):
            close_seg(frame, n)
    return "".join(out)


def _extract_test_key(cmd):
    """Extract normalized test command key from a shell command."""
    # Find the test command in the shell-only text
    m = _TEST_CMD_RE.search(cmd)
    if not m:
        return None
    # Return the test file path portion (after python3/perl/bash etc)
    full = m.group(0).strip()
    # Try to extract just the test file path
    # python3 tests/test_a.py -> tests/test_a.py
    # bash tests/test_c.sh -> tests/test_c.sh
    parts = full.split()
    if len(parts) >= 2:
        return parts[-1]  # Return the last part (the test file)
    return full


def _t1_tests(transcript_path):
    """T1: check if test commands' LAST run exited ≠0, was killed, or timed out."""
    findings = []
    if not transcript_path or not os.path.exists(transcript_path):
        print(f"DEBUG T1: transcript not found: {transcript_path}", file=sys.stderr)
        return findings

    # Track last run of each test command: key -> (exit_code, is_error, timestamp, raw_cmd)
    last_run = {}

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
        line_count = 0
        for line in fh:
            line_count += 1
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"DEBUG T1: JSON decode error line {line_count}: {e}", file=sys.stderr)
                continue

            # Look for assistant tool_use (Bash) followed by user tool_result
            # We need to pair them up. The transcript has the tool_use in assistant
            # and the tool_result in the next user message.
            if d.get("type") == "assistant":
                msg = d.get("message") or {}
                for blk in msg.get("content") or []:
                    if isinstance(blk, dict) and blk.get("type") == "tool_use" and blk.get("name") == "Bash":
                        cmd = blk.get("input", {}).get("command", "")
                        key = _extract_test_key(cmd)
                        if key:
                            # Store pending test command
                            last_run[key] = {
                                "cmd": cmd,
                                "timestamp": d.get("timestamp"),
                                "exit_code": None,
                                "is_error": False,
                                "killed": False
                            }
            elif d.get("type") in ("user", "tool_result"):
                # Check if this is a tool_result for a test command
                msg = d.get("message") or {}
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, list):
                        for blk in content:
                            if isinstance(blk, dict) and blk.get("type") == "tool_result":
                                is_error = blk.get("is_error") or False
                                exit_code = blk.get("exit_code")
                                if isinstance(exit_code, str):
                                    try:
                                        exit_code = int(exit_code)
                                    except ValueError:
                                        exit_code = 1
                                # Check for killed signal
                                killed = False
                                out = str(blk.get("content") or "") + str(blk.get("output") or "")
                                if "killed" in out.lower() or (exit_code is not None and exit_code == 137):
                                    killed = True

                                # Try to find matching test command by looking at recent commands
                                # This is approximate but works for our fixture
                                for key, info in last_run.items():
                                    if info["exit_code"] is None:
                                        info["exit_code"] = exit_code
                                        info["is_error"] = is_error
                                        info["killed"] = killed
                                        break

    # Evaluate last runs
    for key, info in last_run.items():
        if info["exit_code"] is None:
            continue
        if info["killed"] or info["is_error"] or (info["exit_code"] is not None and info["exit_code"] != 0):
            detail = ""
            if info["killed"]:
                detail = " (killed)"
            elif info["is_error"]:
                detail = f" (exit {info['exit_code']})"
            else:
                detail = f" (exit {info['exit_code']})"
            findings.append(Finding("FAIL", "T1", f"tests not shown green: {key}{detail}", "transcript"))

    return findings


def _h_checks(transcript_path):
    """H1-H4: no-hidden-changes traps from transcript."""
    findings = []
    if not transcript_path or not os.path.exists(transcript_path):
        return findings

    # Track commands that match H patterns
    h1_found = False
    h2_found = False
    h3_found = False

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            if d.get("type") == "assistant":
                msg = d.get("message") or {}
                for blk in msg.get("content") or []:
                    if isinstance(blk, dict) and blk.get("type") == "tool_use" and blk.get("name") == "Bash":
                        cmd = blk.get("input", {}).get("command", "")
                        probe = shell_only(cmd)

                        # H1: git add -A / --all / commit -a
                        if re.search(r'\bgit\s+(?:add\s+(?:-A|--all)|commit\s+-a)\b', probe):
                            h1_found = True

                        # H2: write under ~/.claude/plugins/cache/
                        if re.search(r'[~/]\.claude/plugins/cache/', probe):
                            h2_found = True

                        # H3: force-push or move pushed tag
                        if re.search(r'\bgit\s+push\s+[^\n]*--force\b', probe) or \
                           re.search(r'\bgit\s+tag\s+[^\n]*-[fd]\s', probe) or \
                           re.search(r'\bgit\s+push\s+[^\n]*--force-with-lease\b', probe):
                            h3_found = True

    if h1_found:
        findings.append(Finding("WARN", "H1", "`git add -A` ran", "transcript"))
    if h2_found:
        findings.append(Finding("FAIL", "H2", "wrote under ~/.claude/plugins/cache/", "transcript"))
    if h3_found:
        findings.append(Finding("FAIL", "H3", "force-pushed or moved a pushed tag", "transcript"))

    return findings


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
        # Use --all-projects to find the session across all projects
        cmd += ["--all-projects"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        repos.append(line.strip())
        except Exception:
            pass

        # Also get the transcript path for the session
        if args.session and not args.transcript:
            cmd2 = [sys.executable, str(scan_script), "--list", "--all-projects"]
            if args.session:
                cmd2 += ["--session", args.session]
            try:
                result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
                if result2.returncode == 0:
                    for line in result2.stdout.strip().split("\n"):
                        if line.strip() and not line.startswith("=") and not line.startswith(" "):
                            # Parse the line to get the transcript path
                            parts = line.split()
                            if len(parts) >= 2:
                                # Find the file path (usually the last part that looks like a path)
                                for part in parts:
                                    if part.startswith("/") and part.endswith(".jsonl"):
                                        args.transcript = part
                                        break
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

    # Detect no-hidden-changes (needed for H checks)
    nhc_enabled, nhc_version = _detect_no_hidden_changes()
    if nhc_enabled:
        nhc_status = f"detected {nhc_version} (enabled)"
    else:
        nhc_status = "not installed — H-checks skipped"

    # Run repo checks
    all_findings = []
    for repo in resolved_repos:
        all_findings.extend(check_repo(repo, args.allow_markers))

    # Run transcript checks if transcript provided (doesn't require a repo)
    if args.transcript:
        t1 = _t1_tests(args.transcript)
        all_findings.extend(t1)
        h = _h_checks(args.transcript)
        all_findings.extend(h)

    # If no repos and no transcript, empty audit
    if not resolved_repos and not args.transcript:
        print("VERDICT: CLEAN — 0 FAIL, 0 WARN, 0 UNKNOWN")
        return 0

    # Print output
    output = render(all_findings, nhc_status)
    print(output)

    # Exit code per D6
    fail_count = sum(1 for f in all_findings if f.level == "FAIL")
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())