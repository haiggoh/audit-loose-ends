---
name: harvest-lessons
description: Opt-in sub-skill that consumes audit-scan.py --lessons output and promotes validated lessons to the correct layer (CLAUDE.md, memory, or a rule-governing plugin). Budgeted to prevent cost overruns.
---

# harvest-lessons — promote lesson candidates to durable rules

**Opt-in, budgeted sub-skill.** Only runs when the user explicitly invokes it or answers "yes" to the main `audit-loose-ends` skill's one-line offer: "N lesson candidates found — run harvest-lessons? (~N×1.5K budgeted)".

**Trigger:** User says "run harvest-lessons" / "harvest lessons" / "yes" to the offer, or invokes directly.

## Procedure

### 1. Run the scanner for lesson candidates

```sh
"$CLAUDE_PLUGIN_ROOT/scripts/audit-scan.py" --lessons [--project ...] [--last N] [--all-projects]
```

This emits a `LESSON CANDIDATES` section and a summary line:
```
lessons: N candidates (c corrections, r retries, d decisions, s self-corrections, e schema-errors)
```

**A zero is a claim the scanner must be able to fail first** (obs 0050). The classifier's zero
is bounded by its vocabulary — before reading "0 candidates" as "no lessons happened", run
`"$CLAUDE_PLUGIN_ROOT/scripts/audit-scan.py" --self-test`: it pushes a planted-positive corpus
through the same predicates and exits non-zero if any class can no longer fire. A scanner
that cannot fire certifies nothing.

### 2. For each candidate, fetch context with --quote (budgeted)

The total cost is capped by `candidates × budget`, not by session length.

```sh
"$CLAUDE_PLUGIN_ROOT/scripts/audit-scan.py" --quote '<anchor from candidate>' --budget 1500
```

**State the cap before starting.** If there are more than ~15 candidates, ask which categories to take (corrections, retries, decisions, self-corrections, schema-errors).

### 3. For each candidate, decide its disposition

| Disposition | Action |
|-------------|--------|
| **General rule** | Promote to the layer that owns it: CLAUDE.md (always-on), memory (situational), or a rule-governing plugin (testable, free of always-on bytes). See "Where rules live" memory. |
| **Instance of existing rule** | Update that rule's body ONLY if the instance adds something not already covered. **Verify every "already covered" claim against the cited text** — both CLAUDE.md and memory. |
| **Noise / not actionable** | Skip. No record kept. |

**Promote the GENERAL principle wherever one applies** (standing instruction 2026-09-24). An observation often arrives as one domain's case of a rule that holds everywhere — closing it as "covered" because the instance is recorded leaves the general rule unwritten.

**Match the rule's strength to its reader** — decide it together with the layer, not after. A rule aimed at a zero-context reader (a fresh session, a successor with none of this conversation) earns a blunt, unconditional form ("never do X"): nuance is exactly what such a reader cannot be trusted to re-derive. The same lesson for a reader who understands the mechanism can be scoped ("don't X unless Y, because Z") without loss. A blunt rule placed in a scoped context breeds exceptions; a scoped rule placed where zero-context readers land is silently over-trusted.

**Before inventing a layer, run the ladder** (CLAUDE.md "Where rules live" owns it): hook (mechanically checkable ⇒ a barrier beats prose and costs no context until it fires) → one terse CLAUDE.md line → the body of the EXISTING skill that owns the task → a new lean skill (`disable-model-invocation: true` when only the user triggers it) → a playbook (detailed workflows, worked examples, incident history). Promotion retires the source: a playbook promoted into a skill gets a dated "historical — canonical is X" header the same day, and later edits go to the canonical layer only.

### 4. Skill-improvement lessons → task-observer log (soft dependency)

Locate the log — never assume a path (it is user-scope in task-observer 3.x, per-project before):

```sh
"$CLAUDE_PLUGIN_ROOT/scripts/observation-log.py"   # "per-file\t<dir>", "legacy\t<log.md>", or "none"
```

- `per-file`: create ONE new observation file the way task-observer itself does — its
  `scripts/new-observation.sh <slug>` where it exists (it derives the id), with `status: open`.
  Before creating, check the open titles (`--open`) and extend a matching entry instead.
- `legacy`: append an OPEN `### Observation N:` entry to that `log.md`.
- `none`: no task-observer log — write to memory (or CLAUDE.md if always-on).

### 5. Check memory headroom before writing

The `MEMORY.md` index is silently truncated past ~24,400 bytes. Run:

```sh
"$CLAUDE_PLUGIN_ROOT/scripts/memory-index-audit.py" --dir ~/.claude/projects/$(basename $PWD | sed 's/^/-Users-/;s/\//-/g')/memory
```

If over limit or no headroom, report and do not write.

### 6. Report

For each candidate: **promoted** (where), **reinforced** (which existing rule), or **skipped** (reason).

---

## Flags

- `--budget N` — max tokens to spend (default 3000 ≈ 2 candidates at 1.5K each)
- `--dry-run` — show what would be done without writing
- `--categories CORRECTIONS,RETRIES,...` — limit to specific types

---

## Integration with audit-loose-ends

The main skill (Step 0) runs `audit-scan.py --lessons` and, if N>0, prints one line:
```
N lesson candidates found (c corrections, r retries, d decisions, s self-corrections) — run harvest-lessons? (~N×1.5K budgeted)
```

The main skill never runs harvest-lessons automatically — it only offers.