#!/usr/bin/env bash
# verify-paths.sh — refuse to run when a path you named does not exist.
#
# WHY. Twice in one session (2026-10-24/25) a shell word-split mangled a path list and handed it to
# a tool that skips missing files SILENTLY, so the tool reported a clean result over input it never
# opened: `git diff --name-only | tr '\0' ' '` turned 27 filenames into 222 paths (three of them
# split mid-name), and a space-mangled parse had earlier read 21 of 27 files as "not in git
# history" when all 27 were there. Both counts were visible in the output; neither was checked.
#
# THE SHAPE THIS GUARDS. A consumer that skips what it cannot find, fed a list you built by
# splitting on whitespace, produces a confident clean result over the wrong set. The tell is always
# the COUNT: the tool says how many files it examined. So: check the paths exist BEFORE the
# consumer, and abort when any does not.
#
# Usage:
#   verify-paths.sh FILE...                    one line per missing path, then exit 1 (0 if all exist)
#   verify-paths.sh --null                     read NUL-delimited paths on stdin (un-splittable)
#   verify-paths.sh --quiet                    exit status only, no listing
#   verify-paths.sh --help
#
# Composable, which is the point:
#   git diff --staged --name-only -z | verify-paths.sh --null
#
# Exit: 0 = every path exists (prints the count); 1 = at least one missing; 2 = usage error.
set -uo pipefail

usage() { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; }

NULL=0 QUIET=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --null) NULL=1; shift ;;
    --quiet|-q) QUIET=1; shift ;;
    --) shift; break ;;
    -*) echo "verify-paths.sh: unrecognised option $1" >&2; usage >&2; exit 2 ;;
    *) break ;;
  esac
done

# Collect the paths. With --null the list arrives NUL-delimited, so a filename containing a space
# cannot be split — which is the failure this exists to stop.
paths=()
if [ "$NULL" = 1 ]; then
  while IFS= read -r -d '' p; do paths+=("$p"); done
else
  [ $# -gt 0 ] || { echo "verify-paths.sh: name the paths to check (or use --null)" >&2; exit 2; }
  paths=("$@")
fi
[ "${#paths[@]}" -gt 0 ] || { echo "verify-paths.sh: no paths given" >&2; exit 2; }

missing=()
for p in "${paths[@]}"; do
  [ -n "$p" ] || continue
  # -e follows symlinks; a dangling link is exactly the "path that looks fine" case.
  if [ ! -e "$p" ] && [ ! -L "$p" ]; then missing+=("$p"); fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  if [ "$QUIET" = 1 ]; then
    echo "verify-paths.sh: ${#missing[@]} of ${#paths[@]} path(s) do not exist" >&2
  else
    echo "verify-paths.sh: ${#missing[@]} of ${#paths[@]} path(s) DO NOT EXIST —" >&2
    echo "  a tool that skips missing files will report a clean result over input it never opened." >&2
    for m in "${missing[@]}"; do echo "    missing: $m" >&2; done
  fi
  exit 1
fi
[ "$QUIET" = 1 ] || echo "verify-paths.sh: all ${#paths[@]} path(s) exist"
exit 0
