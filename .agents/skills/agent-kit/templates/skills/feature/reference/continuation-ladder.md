# Continuation ladder (cycle-3 exhaustion)

When `goal.md`'s `phases.ladder` is `auto` (loop-created goals set it; interactive
goals default to `escalate`, where the user is offered the ladder as an explicit
option), this ladder applies after **cycle-3 exhaustion** (NEEDS FIXES after three
implement→evaluate cycles without PASS). **Early arbitration at detection** is the
exception — see below. Apply rungs in order; every ladder fix attempt is
re-evaluated — there is no exception.

## Early `criteria-defect` routing (detection)

`criteria-defect` stops fix cycles at detection on any cycle: with `ladder: auto` run rung 5 arbitration now; with `ladder: escalate` escalate with arbitration offered as option 1.
Early arbitration costs no implementation attempt; criteria-defective, or any arbiter/primary disagreement, escalates to the user, a criterion correction the user approves is a criterion-correction amendment, and a criterion the user upholds resumes the task at its next fix cycle.
The unanimity heuristic does **not** gate this path. Pass the verdict(s) so far into
arbitration. `criteria-defect` routing wins over line-patch-only resume.

## Rung 5 — arbitration (unanimity check)

If all three evaluator verdicts in the orchestration log flagged the same
required-fix item (unanimous-failure heuristic — compare items with their trailing
`[line-patch]` / `[structural]` tags stripped, so a tag change across cycles does not
make the same item count as different), spawn `evaluator` in
**arbitration mode** on `{{MODEL_FRONTIER_ALT_FAMILY}}` with the task file
(including its Acceptance Criteria), all three verdicts, and all three implementer
reports. Outcomes:
`criteria-defective` → escalate to the user carrying the named defective criterion
**verbatim**; arbiter/primary disagreement → escalate (never auto-resolve);
`criteria-sound` → continue to rung 4.

## Rung 4 — diagnosis-first

Spawn `diagnostician` with the task file (including its Acceptance Criteria), all
three implementer reports and evaluator verdicts, and the targeted verification
command. If its
**Signature Declaration** matches a previously tried fix signature → skip to rung 6
if it recommended a split, else escalate. Otherwise run **ONE** diagnosis-driven
implementation attempt: fresh `implementer` on `{{MODEL_FRONTIER}}` using the
diagnostician's **Rewritten Required-Fixes** list; then mandatory re-evaluation.

## Rung 6 — decomposition + selective retry

Only on a diagnostician split recommendation. Derive subtask files with ownership
contracts whose write sets are subsets of the parent task's, from the **failing
pieces only** — unflagged work from earlier cycles stays as-is, is not re-run, and
gets no separate evaluation. Each derived subtask gets one implement→evaluate
cycle; the parent task completes when every derived subtask has an evaluator PASS;
evaluator spawns never consume the attempt budget — only implementation attempts do.

## Terminal escalation

Escalate to the user with the full ladder history.

## Hard guards

Character-consistent with `{{IDE_DIR}}/ORCHESTRATION.md`:

- At most **3 additional implementation attempts** after cycle 3, summed across rungs 4
  and 6.
- The diagnosis-driven implementation attempt costs 1 of the 3. Each rung-6 subtask
  implement→evaluate cycle costs 1 of the 3. Before splitting, compare the
  failing-subtask count against the remaining budget — if the count exceeds the
  remaining budget, escalate instead of splitting.
- A **repeated failure signature** stops the ladder immediately: the evaluator's
  required-fixes list as recorded in the orchestration log, identical to an earlier
  cycle's list item-for-item after normalizing whitespace and list numbering and
  stripping trailing `[line-patch]` / `[structural]` tags from each item (signature
  identity ignores those tags).
- Every rung transition, spawn, and guard trip is an orchestration-log entry recording
  the rung name.

Token/cost budgets are not a guard in interactive mode (no harness exposes true usage to the
orchestrator); the headless loop records real usage per iteration via
`LOOP_USAGE_FORMAT` — gating on it is a future knob, not this ladder's.
