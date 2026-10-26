#!/usr/bin/env bash
# link-shortcuts.sh — put this plugin's two scripts on the machine, as SHIMS.
#
# WHY SHIMS AND NOT SYMLINKS: a symlink is frozen at install time, so it names a
# version directory the next update leaves behind, and the entry point silently keeps
# running the OLD copy until somebody re-runs this script by hand. A shim resolves its
# plugin dir on every invocation, so a plugin update takes effect with no re-wiring.
#
# This plugin owns exactly two entry points, both consumed by OTHER plugins' flows
# (the audit runs redact-secret.py; the memory-index sweep runs memory-index-audit.py):
#   ~/.claude/scripts/redact-secret.py
#   ~/.claude/scripts/memory-index-audit.py
#
# WHAT IT CHANGES: those two paths. Nothing else — not settings.json, not PATH, not
# the .zshrc. SAFETY: every replaced file is copied to a timestamped backup dir first
# with its mode preserved; a plain file this plugin did not write is REFUSED (exit 1)
# unless --force, because overwriting a file someone else owns is not this script's
# call to make. A symlink or an existing shim is replaced like any other change.
#
# Unlike cost-tracker's wire-statusline.sh, this script needs no resolver step: a
# shim's body is identical whichever copy it resolves to, so there is nothing to bake
# in at install time. That is the point.
set -uo pipefail

usage() {
    cat <<'EOF'
Usage: link-shortcuts.sh [--dry-run] [--force] [--help]

Install ~/.claude/scripts/{redact-secret.py,memory-index-audit.py} as shims that
resolve the installed plugin copy on every call, so a plugin update takes effect
without re-running this script.

With no arguments it CHECKS and FIXES (backups first). Safe to re-run: when both
entry points are already this plugin's shims it changes nothing.

Options:
  --dry-run    report what is wrong and what would change; write nothing
  --force      replace a FOREIGN file (one this plugin did not write). Without it
               such a file is refused, not overwritten.
  -h, --help   show this help and exit

Environment:
  HOME         everything is resolved under $HOME/.claude
  CLAUDE_PLUGINS_DIR   where the plugin cache and installed_plugins.json live
                       (default $HOME/.claude/plugins) — a test seam

Exit status: 0 wired (or already wired, or dry run), 1 refused or failed,
2 bad usage.
EOF
}

DRY=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        -h|--help) usage; exit 0 ;;
        --dry-run|-n) DRY=1 ;;
        --force) FORCE=1 ;;
        *) printf 'link-shortcuts.sh: unknown argument: %s\n' "$arg" >&2
           printf 'usage: link-shortcuts.sh [--dry-run] [--force] [--help]\n' >&2
           exit 2 ;;
    esac
done

HERE="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$HERE/shim-template.sh"
LINKS="redact-secret.py memory-index-audit.py"
SCRIPTS="$HOME/.claude/scripts"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$HOME/.claude/backups/audit-loose-ends-link-$STAMP"

say() { printf '%s\n' "$*"; }

if [ ! -f "$TEMPLATE" ]; then
    say "link-shortcuts.sh: the shim template is missing: $TEMPLATE"
    exit 1
fi

say "scripts: $SCRIPTS"
say ""

# --- check ----------------------------------------------------------------------
NEED=0
FOREIGN=""
for f in $LINKS; do
    live="$SCRIPTS/$f"
    if [ -f "$live" ] && head -n 3 "$live" 2>/dev/null | grep -q '^# haiggoh-shim v1 plugin=audit-loose-ends target=scripts/'; then
        say "  already wired   scripts/$f (shim)"
        continue
    fi
    NEED=1
    if [ -L "$live" ]; then
        say "  REPLACE symlink scripts/$f -> $(readlink "$live")"
    elif [ -e "$live" ]; then
        say "  FOREIGN         scripts/$f is a plain file this plugin did not write"
        FOREIGN="$FOREIGN $f"
    else
        say "  MISSING live    scripts/$f (will be created as a shim)"
    fi
done

if [ -n "$FOREIGN" ] && [ "$FORCE" != "1" ]; then
    say ""
    say "REFUSING: scripts/ has files this plugin did not write:$FOREIGN"
    say "Overwriting a file someone else owns is not this script's call to make."
    say "Re-run with --force to back each one up (timestamped) and replace it with a"
    say "shim, or move them aside first."
    exit 1
fi

if [ "$NEED" = "0" ]; then
    say ""
    say "Nothing to do — both entry points already resolve this plugin per call."
    exit 0
fi

if [ "$DRY" = "1" ]; then
    say ""
    say "DRY RUN — nothing written. Run without --dry-run to back up to"
    say "  $BACKUP"
    say "and install the shims above."
    exit 0
fi

# --- apply ----------------------------------------------------------------------
mkdir -p "$BACKUP" "$SCRIPTS" || { say "cannot create $BACKUP"; exit 1; }
CHANGED=""
for f in $LINKS; do
    live="$SCRIPTS/$f"
    if [ -f "$live" ] && head -n 3 "$live" 2>/dev/null | grep -q '^# haiggoh-shim v1 plugin=audit-loose-ends target=scripts/'; then
        continue
    fi
    if [ -e "$live" ] || [ -L "$live" ]; then
        # -p keeps mode and timestamps: one of these is a 600 file on some setups,
        # and a backup that widens permissions is its own incident.
        cp -p "$live" "$BACKUP/$f" || { say "backup failed for $f"; exit 1; }
    fi
    /usr/bin/sed -e 's|@PLUGIN@|audit-loose-ends|g' \
                 -e 's|@OVERRIDE@|AUDIT_LOOSE_ENDS_PLUGIN|g' \
                 -e "s|@REL@|scripts/$f|g" "$TEMPLATE" > "$live.new" \
        || { say "could not render the shim for $f"; rm -f "$live.new"; exit 1; }
    chmod 755 "$live.new"
    mv "$live.new" "$live" || { say "could not install the shim for $f"; rm -f "$live.new"; exit 1; }
    CHANGED="$CHANGED $f"
    say "  wired  scripts/$f (shim)"
done

say ""
say "Both entry points now resolve the installed copy on every call, so a plugin"
say "update lands here without re-running this script."
say "Backup of everything replaced: $BACKUP"
