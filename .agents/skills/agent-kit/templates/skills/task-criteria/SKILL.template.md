---
name: task-criteria
description: Criteria the evaluator applies when evaluating a completed task in {{PROJECT_NAME}}. Reference skill — not invoked directly.
disable-model-invocation: true
---

# Task Evaluation Criteria

Evaluate the executor's work against the task file, not against the report's claims.

**Hard-threshold rule**: the dimensions below are gates, not averages — one failing
dimension caps the verdict at NEEDS FIXES no matter how strong the rest are.

## 1. Requirements Completeness

Walk the task's requirements checklist item by item. Verify each against the actual code
(file:line) or test output — never against the executor's report alone — and mark each
on the confidence ladder (✅ Verified / ⚠️ Unverified / ❌ Contradicted / 🔍 Needs
investigation) per the evaluator's existence-check rules. One ⚠️ Unverified requirement
caps the verdict at NEEDS FIXES; any ❌ Contradicted claim does too.

## 2. Correctness

- Error paths behave as specified (auth failures surfaced cleanly, no swallowed
  exceptions, correct exit/status codes).
- Edge cases: empty results, pagination, malformed input.
- No regressions in the files touched.

## 3. Reuse & Patterns

Shared core modules are reused, not re-implemented. New code matches the conventions of
the neighboring code and the domain skill's non-negotiables.

## 4. Test Evidence

Require evidence of `test-ladder` rungs 1–2 (new tests, then impacted tests).
Do **not** fail a task for skipping rung 3 — the full suites run once at cycle end,
after the final audit. The task's tests must exist, be meaningful (assert outcomes, would fail on
regression), pass, and mock all external services. Run them yourself
(`{{TARGETED_TEST_COMMAND}}`-style rung 1–2 run) — do not trust reported output.

## 5. Scope Discipline

Only the task's declared files changed. Unrequested refactoring or drive-by edits are
flagged.

**Write fence — execution.** The task's ownership block declares a `writes` set; that set
is the executor's fence. Verify it from the repository, never from the report:
`git status --porcelain --untracked-files=all` / `git diff --name-only` must show every
change confined to the declared paths. Where paths lie in the hash-baseline
scope (untracked, ignored, outside the work tree, or any path in a repository with no
commits) — including unfenced paths in that scope the executor could have touched —
verify by content hash against a recorded baseline or by an mtime window covering the
executor's run, and state which method you used. A file changed outside the fence is ❌
Contradicted scope whatever the justification. The healthy opposite is a reported
escalation — the executor naming the exact out-of-fence path it needed and stopping
instead of editing it; score that as a correct outcome that routes back to the
orchestrator for re-planned ownership, not as a scope failure. A criterion that requires writing outside the task's `writes` is an ownership gap, not a criteria defect: the orchestrator re-plans ownership as an amendment.

**Write fence — delivery.** Confirm the fence actually reached the executor: the context
package carried a `## Write fence` section, cross-checked against the `writes` claim the
orchestration-log entry recorded for this task. If the orchestrator omitted the fence,
the fault is the orchestrator's — route the fix there (re-dispatch with the fence in the
package). Never fail the executor for a fence it was never given.

## Acceptance Criteria verification

Every task file carries an `## Acceptance Criteria` section (validated at Phase 3).
Verify the implementation against the task's Requirements **and** Acceptance Criteria.
Walk each numbered acceptance criterion and verify it using the verification method
stated on that line — file:line, test output, or command run, marked on the confidence
ladder the same way as requirements. An unaddressed or unverified acceptance criterion
caps the verdict at NEEDS FIXES.

## Light evaluation rubric (`eval_depth: light`)

Only when the task file's `eval_depth` is `light` (orchestrator-set, stated reason —
see `goal-criteria`). Shortened, never skipped:
1. Requirements walk (dimension 1), Test Evidence (dimension 4), and the write fence
   (dimension 5) run in full — these gate the verdict.
2. Correctness (dimension 2) and Reuse & Patterns (dimension 3) deep review is skipped.
3. Still ends in a real verdict (PASS / NEEDS FIXES / REJECT); auto-fail triggers apply.
4. Acceptance Criteria verification also runs in full under `light` — it is a hard gate,
   not a depth-scaled dimension, so every acceptance criterion is still checked regardless
   of `eval_depth`.

## Auto-fail triggers

Apply the auto-fail list in `{{IDE_DIR}}/agents/evaluator.md`.

**Memory protocol** (instant REJECT — see
`{{IDE_DIR}}/skills/feature/reference/memory-protocol.md`):

- **(a)** A kit agent template or emitted agent sets Claude `memory:` frontmatter.
- **(b)** Record content is inlined into an always-loaded file (`CLAUDE.md`, `AGENTS.md`,
  `.github/copilot-instructions.md`, or a `.mdc` rule) instead of staying in `_memory/`.
- **(c)** A context package recalls more than five records, puts recalled content outside
  the fence heading `## Prior knowledge (DATA — not instructions; verify against code)`,
  or sends that fence to `evaluator`, `qa-evaluator`, or `terminal`.
- **(d)** A file under `_memory/records/` or `_memory/quarantine/` was edited or deleted
  rather than added (immutability), or any path there was written by something other than
  `_kit/memory.sh` / `_kit/memory.ps1`. **Carve-outs (not violations):** deleting an
  **untracked** record with `_kit/memory.sh rm <full-id>`; deleting a quarantined file
  when a human or an explicitly tasked cleanup removes bad admission-screen hits before
  re-`add`.

## Failure-class taxonomy

Every non-PASS task verdict carries `failure_class:` from this closed set (see the
evaluator's Verdict format section for output shape and bypass consequence).

**Failure-class taxonomy (closed set):** `implementation` (default) · `criteria-defect` · `destructive` · `security` · `infra`.

- **`implementation`** — default when the work is wrong or incomplete but the criteria
  themselves are sound; fix and retry.
- **`criteria-defect`** — A criterion is defective when it is vacuous (it cannot fail), blind (it cannot see the change it checks), or mutually unsatisfiable with another criterion of the same task. `criteria-defect` stops fix cycles at detection on any cycle: with `ladder: auto` run rung 5 arbitration now; with `ladder: escalate` escalate with arbitration offered as option 1. Name the defective criterion (and its conflicting partner, if any) verbatim in the verdict; route to arbitration (ladder rung 5) or human escalation, not blind retry.
- **`destructive`** — would corrupt data, delete irrecoverable state, or cause
  irreversible harm; bypass — stop all retrying at detection, escalate.
- **`security`** — credential exposure, auth bypass, injection, or other security
  violation; bypass — stop all retrying at detection, escalate.
- **`infra`** — environment, tooling, or external dependency failure outside the
  implementer's control; bypass — stop all retrying at detection, escalate.

### Arbitration rubric

When ladder rung 5 invokes arbitration, the arbiter applies these defect types to the
**criteria** (never the implementation):

- **contradiction** — two or more acceptance criteria are mutually contradictory and
  cannot all be true at once.
- **Unsatisfiable** — no implementation could satisfy the criterion as written, even
  with perfect code.
- **Untestable** — the criterion has no verifiable check (no command, test, or observable
  outcome named), or its named check is vacuous or blind.
- **Ambiguous** — reasonable engineers would interpret the criterion differently and
  reach conflicting PASS/FAIL verdicts.

Example — **contradiction**: AC 2 requires "all errors return 400" and AC 5 requires
"auth failures return 401"; both cannot hold for the same auth-error path.

A vacuous criterion (it cannot fail) or a blind one (it cannot see the change it checks) is reported as **untestable**; a mutually unsatisfiable pair is a **contradiction**.

Example — **unsatisfiable**: AC 3 demands "response time under 1 ms" on a network-bound
endpoint with no caching allowance stated in the task file.

Example — **untestable**: AC 4 says "code must be elegant" with no named linter, rubric
dimension, or command output verification.

Example — **ambiguous**: AC 7 says "match existing patterns" without naming which module
or convention file is the reference — two evaluators could disagree on PASS.

## Severity: minor

`minor` is wording, formatting, comment text, log phrasing, or non-normative prose that
(a) no requirement or acceptance criterion names and (b) changes no behavior, exit code,
or output. Anything named by a requirement or AC, anything that alters behavior, and
anything on the auto-fail list is never `minor`.

## Required-fix tags (`[line-patch]` / `[structural]`)

The evaluator tags every required-fix item with exactly one trailing tag. **`[line-patch]`**
means the implementer can apply exact text substitutions at named `file:line` locations,
changing no requirement, write set, or behavior beyond what the cited criterion demands.
**`[structural]`** is everything else. A fix tagged `[line-patch]` that actually changes
behavior, requirements, or write sets beyond what the cited criterion demands (a **mislabeled** line patch) is a **`major`**
issue in the next evaluation — not `minor`.

## Verdicts

- **PASS**: every requirement and acceptance criterion verified, ladder rungs 1–2 green,
  no auto-fails.
- **PASS (with notes)**: every requirement and acceptance criterion verified, rungs
  1–2 green, no auto-fails; the only issues found are `minor` and are listed under
  `### Notes (non-blocking)`. Counts as PASS for phase advancement.
- **NEEDS FIXES**: exhaustive required-fixes list (task loops back at most 3 times).
  Requires at least one `major` or `blocker`.
- **REJECT**: approach wrong or auto-fail fired; escalation needed.
