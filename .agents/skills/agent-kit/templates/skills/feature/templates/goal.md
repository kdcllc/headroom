# Goal: [name]

## Problem Statement

[What is broken/missing, for whom, and why it matters. 2–5 sentences.]

## Discovery Summary (Phase 1 Q&A)

[Condensed record of the alignment questions and the user's answers. The goal evaluator
checks tasks against this — every answered decision must be reflected in a task.]

## Recalled memory

[Record ids picked at recall, or `none`.]

## Success Criteria

- [ ] [Observable, verifiable outcome — behavior, not activity]
- [ ] [...]

## Constraints

- [Must reuse / must not touch / performance / compatibility constraints]

```yaml
phases:
  align_docs: true|false    # recorded from Phase 1 answers; checked after Phase 5 APPROVED (default false)
  pull_request: true|false  # recorded from Phase 1 answers; checked after Phase 5 APPROVED (default true)
  ladder: escalate|auto      # escalate (default): on cycle-3 exhaustion, escalate to the user with the continuation ladder offered; auto: run the ladder (loop-created goals).
  parallel: true|false       # default true; false runs Phase 4 one task at a time
  qa: run|skip               # default skip; run → evidence-collector + qa-evaluator after Phase 5 approval
```

## Out of Scope

- [Explicitly excluded work, so the evaluator can flag scope creep]

## Tasks (dependency order)

| # | Task file | Layer | Depends on |
|---|-----------|-------|------------|
| 01 | `01-[name].md` | [layer] | — |
| 02 | `02-[name].md` | [layer] | 01 |
| NN | `NN-tests.md` | tests | all |

**Contract first.** If this goal touches a shared boundary or interface, the first task
is a dedicated contract/scaffold task — it defines the types, schemas, and port
interfaces and creates the empty file skeletons — and every task that consumes them
lists it in `depends_on`. Consumers then build against that frozen interface instead of
each other's files.
