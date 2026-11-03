# Resume a goal

A fresh session can continue a half-finished interactive `/feature` goal without trusting stale chat state, spawn reports, or an outdated working tree. Read this reference when the user asks to resume a named goal or picks one during Phase 2.

## When progress.md is written

The orchestrator performs a whole-file rewrite of `_memory/work/goals/[goal]/progress.md` from `templates/progress.md` when the goal folder is created (Phase 2), after every phase transition, every task verdict, every escalation or user decision, and before ending a session with the goal unfinished; each rewrite updates `phase:` (its own line); set `status: done` after the last enabled phase completes. This applies on every install, with or without the kit-file guard; `ORCHESTRATION.md` is never used for progress.

## Unfinished goals (Phase 2)

After Prune and before Recall, list `_memory/work/goals/*/progress.md` whose `status:` is not `done` (each listed goal shows its `phase:` and next step), plus goal folders that have an `orchestration-log.md` but no `progress.md` (list them as "no checkpoint"). Offer them with the harness question tool where available; the user chooses to resume one or to continue the new goal; never resume automatically.

## Resume procedure

Triggered when the user asks to resume a named goal or picks one at Phase 2.

1. Read `progress.md`, `goal.md`, every task file, `orchestration-log.md`, and — when they exist (from Phase 4 on) — `base-commit.txt` and `preexisting-dirty.txt`.
2. **Ledger cross-check.** Every task verdict in `progress.md` has a matching OUTCOME in the log, and the log has no OUTCOME newer than `updated:` that `progress.md` does not reflect. Each SPAWN with no OUTCOME is in flight: apply the Phase 4 silent-success check (artifacts present ⇒ record "report lost, files verified"; absent ⇒ re-spawn as a new numbered entry). Never edit or delete ledger entries.
3. **Repository check.** Confirm each item below; any mismatch is handled in step 4:
   - When a remote exists run `git fetch` (if it fails, log it, say so to the user, and continue on local refs).
   - The current branch is the recorded branch.
   - HEAD equals `HEAD at this write`, or every commit since it is a goal commit or a recorded excluded external commit.
   - The base commit is still an ancestor of HEAD.
   - The unpushed-commit list is recomputed.
   - No PR merged *this goal's* work: a merged PR for the branch is a mismatch only when its head commit descends from, and is not, the recorded base commit — an unknown head commit (`git merge-base --is-ancestor` exit 128) also counts as a mismatch (for example `gh pr list --state merged --head <branch> --json headRefOid` and `git merge-base --is-ancestor <base> <headRefOid>`), so older merged PRs of a reused branch do not count — squash merges create new hashes, so ancestry of HEAD alone cannot show the work is unmerged; when no forge CLI is available, say so to the user and ask whether the branch's work was merged.
   - Working-tree changes are limited to the goal's task fences, `preexisting-dirty.txt` and recorded exclusions.
   - **Before Phase 4** (no `base-commit.txt` yet; `progress.md` shows `base commit: not recorded until Phase 4`): skip the base-ancestry, merged-PR and pre-existing-dirty comparisons and compare HEAD with `HEAD at goal creation` instead.
4. **Any mismatch stops the resume.** Log a note, then escalate (feature skill escalation format) naming each mismatch, with options such as re-baselining `progress.md` to the current state after the user confirms, investigating, or abandoning the goal. Never edit `progress.md` to hide a mismatch.
5. **All checks pass.** Log `RESUMED: <goal> at <phase> — <next step>` with `<phase>` from the `phase:` line, using `_kit/log-spawn.sh note`, rewrite `progress.md` (new `updated:`, resolved in-flight entries), and continue at the next step under the normal phase rules — every evaluator gate still applies.

## Missing checkpoint

A goal folder with a log but no `progress.md` is rebuilt from the ledger and the goal and task files, shown to the user, and continued only after the user confirms; the repository check in step 3 above still runs.

## Scope

Interactive `/feature` goals only. In the autonomous loop — driver-dispatched mode or a manual auto-loop iteration, both of which run feature Phases 2–6 with no user to answer — skip the Phase 2 offer and the resume procedure; the loop owns that state. `progress.md` is still written.
