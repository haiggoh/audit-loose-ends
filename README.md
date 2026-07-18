# audit-loose-ends

A Claude Code plugin that reconciles your **durable records** at the end of a task or session, so
nothing is left **redundant, orphaned, or falsely flagged as to-do when it's already done**. A
SessionStart nudge keeps the rule in view; a bundled skill holds the full procedure.

## Why

Storing progress isn't enough — the *records* of it drift. A finished task stays flagged "pending"
in a memory; a note describes a plan that already shipped; a follow-up never gets tracked. Left
alone, a future session (or a startup banner) re-surfaces settled ground as if it were open. `audit-loose-ends`
is the recurring end-of-task pass that keeps records honest.

## What it does

At session start it injects a **model-only** one-line reminder (no user-facing banner). The reminder
fires the reconciliation when:
- you signal a wrap-up — "wrap up", "audit", "tidy up", "close out" — or
- the session **created or changed durable records** (memories, project notes, reminders/crons, the
  task list, or the [`waypoints`](https://github.com/haiggoh/waypoints) store).

It is **not length-based**: a long read-only task needs no audit; a short task that closed a tracked
to-do does. The procedure (in `skills/audit/SKILL.md`) scans each surface, distinguishes a
*historical completion record* (keep) from a *stale pending flag* (fix), marks finished items done
(`waypoints done <id>`), captures genuinely-open follow-ups as waypoints, and confirms touched repos
are clean.

## Relationship to the siblings

- **waypoints** — *stores* the open items; `audit-loose-ends` *maintains* that store (one of the surfaces it
  reconciles). waypoints saves; audit checks.
- **no-hidden-changes** — reconciles a *rule* against your setup **once, at first run**; `audit-loose-ends`
  reconciles your *records* **recurringly, at wrap-up**. Same verb family, different trigger + target.
- **resume-interrupted** — recovers an *accidentally* cut-off session; `audit-loose-ends` tidies the records of
  a *deliberately* concluded one.

## Install

```
/plugin marketplace add haiggoh/get-haiggoh
/plugin install audit-loose-ends@haiggoh
```

## Optional / disabling

It's a plugin — disable or uninstall via `/plugin` if you don't want the reminder.

## Tests

```
bash tests/test_nudge.sh
```

## License

MIT — see [LICENSE](LICENSE).
