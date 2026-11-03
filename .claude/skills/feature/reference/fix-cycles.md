# Fix cycles (Phase 4 step 4)

Read this before acting on **NEEDS FIXES**, **REJECT**, a verdict tagged `destructive`/`security`/`infra`, `failure_class: criteria-defect`, or Phase 4 cycle-3 exhaustion.

## Cycle cap

- Max 3 evaluation cycles per phase/task; on Phase 4 cycle-3 exhaustion, read
  `phases.ladder` (`escalate` default or key absent → escalate with "Run the
  continuation ladder" as option 1; `auto` → continuation ladder). Other phases escalate.

## Executor resume

Implementer MAY be resumed for fix cycle 1; cycles 2–3 fresh spawns
(rotation applies) except line-patch-only (Phase 4 step 4).

## Line-patch-only

**Line-patch-only** (all `[line-patch]`): resume same executor (`implementer`/`test-writer`) apply-verbatim any cycle (fresh spawn on same model if harness can't resume), no rotation, counts toward 3, re-evaluated; any `[structural]` → normal fix with patches verbatim. `NOT APPLIED` → re-evaluate; next cycle normal.

## Criteria-defect and bypass

**`criteria-defect`** (not bypass): route at detection per `reference/continuation-ladder.md`. **Bypass at detection (every verdict, cycles 1–3).** Verdicts tagged `destructive`,
`security`, or `infra` stop all cycles immediately and escalate — from cycle 1.

## On cycle-3 exhaustion

**On cycle-3 exhaustion**, read `goal.md`'s `phases.ladder`: `escalate` (default, or
key absent) → escalate with "Run the continuation ladder" as option 1 (log "ladder:
escalate per goal.md"); `auto` → Read `reference/continuation-ladder.md` and follow
it. Every ladder fix attempt is re-evaluated.

## Fix-cycle model rotation

**Fix-cycle model rotation**: cycle 1 normal; cycle 2 **different family** at comparable tier; cycle 3
**frontier** (model map). Log each rotation (skipped on line-patch-only).
