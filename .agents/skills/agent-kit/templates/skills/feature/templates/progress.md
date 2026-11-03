# Progress: [goal]
updated: [literal ISO timestamp from CURRENT_DATETIME — never guessed]
status: active | waiting-on-user | blocked | done
phase: [current phase — number and name, e.g. 4 — Execution]

> The orchestrator rewrites this whole file from this template on every update. Do not leave placeholder lines such as `TBD` or `(pending)` in a written copy; write `none` for empty sections.

## Next step

[One concrete action — agent to spawn, check to run, or question to ask.]

## Git

- branch: `[branch-name]`
- HEAD at goal creation: `[sha]`
- base commit: `[sha from base-commit.txt]`, or exactly `base commit: not recorded until Phase 4` before Phase 4 when that file does not exist yet
- HEAD at this write: `[sha]`
- commits not pushed: `[sha list]` or `no upstream`

## Tasks

| Task | Group | Cycle | Verdicts | Final | Last spawn |
|------|-------|-------|----------|-------|------------|
| `01-…` | 1 | 1 | … | ⬜ | #01 |

## In flight

`#NN agent (phase)` — SPAWN ledger entries with no OUTCOME yet, or `none`.

## Waiting on user

Open decisions and escalations, quoted, or `none`.

## Deviations and exclusions

Accepted deviations; external commits excluded from the goal (sha and paths); or `none`.

## Orchestration Progress: [Goal Name]

### Phase 1: Alignment (structured discovery — no files created)
- [ ] Discovery questions asked
- [ ] Follow-up questions asked (if needed)
- [ ] Summary presented to user
- [ ] User confirmed understanding ("yes, proceed")

### Phase 2: Goal Creation
- [ ] Goal.md created
- [ ] Decision gates passed (or user decided)
- [ ] Task files created

### Phase 3: Goal Evaluation (must loop until PASS)
- [ ] Evaluator subagent invoked (attempt 1)
- [ ] Verdict: [PASS/NEEDS REVISION/REJECT]
- [ ] Final verdict that allowed progression: PASS

### Phase 4: Execution (each task must loop evaluator until PASS)
See ## Tasks.

### Phase 5: Final Audit (must loop until APPROVED)
- [ ] Audit subagent invoked (attempt 1)
- [ ] Verdict: [APPROVED/ISSUES FOUND]
- [ ] Final verdict that allowed progression: APPROVED
- [ ] Quality checks (ladder rung 3: full suites) passed
- [ ] Optional QA (`qa: run` in goal.md): evidence-collector → qa-evaluator; skipped when `qa: skip`

### Phase 6: Align Docs (must loop until doc audit APPROVED)
- [ ] Change surface + per-doc edit list built
- [ ] Edit plan evaluated PASS
- [ ] Each doc executed + evaluated PASS
- [ ] Final doc audit APPROVED (docs only; _memory/ untouched)

### Phase 7: Pull Request (gated on user approval)
- [ ] PR title + body drafted from branch commits
- [ ] User approved the draft
- [ ] PR/MR created/updated on the project's forge, or hand-over printed — URL or artifact: [link]
