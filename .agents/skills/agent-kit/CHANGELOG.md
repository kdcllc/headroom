# Changelog

All notable changes to the `agent-kit` skill. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [semantic versioning](https://semver.org) and are released as the git tag `agent-kit/vX.Y.Z`.

The kit version is `metadata.version` in [SKILL.md](SKILL.md); the emitter writes it into each install's `orchestration-kit.manifest.json` as `kitVersion`. Before re-adding with a new tag, read the target version's entry, especially its **Upgrade notes**.

## [Unreleased]

## [1.1.2] - 2026-10-20

### Added

- **Executable acceptance criteria evidence** — pre-flight and goal-criteria require shell-command criteria to be run against the current tree with output recorded in `criteria-evidence.md` (including true-negative and true-positive demonstrations for content-inspecting checks).
- **Reference sweep artifact** — pre-flight check 2 writes `reference-sweep.md`; the Phase 3 evaluator verifies every hit is owned or justified.
- **Corrective tasks reference** — `reference/corrective-tasks.md` defines lettered corrective tasks for defects found in completed tasks' files.
- **Goal-revisions reference** — `reference/goal-revisions.md` covers plan amendments (material vs additive vs criterion correction), cross-reference audit (`xref-audit.md`), and Phase 3 attempt-3 fresh arbiter review.
- **Pre-flight check 5 Stated facts** — verifies prose counts, Files-to-Read coverage, and that `writes` prose matches the task's `writes` YAML block (the block context packages copy verbatim).
- **Phase-boundary cost notes and compaction recommendation** — orchestration log `note` entries record spawn count, dispatch-volume totals, and main-session size; Phase 4 boundaries past ~60% prompt the user to compact or start a fresh session (recommendation only).
- **Existing project agents** — Step 2 inventories agents under each harness's agent paths (plus Codex `[agents.*]` tables), reports name collisions with the seven kit agents and role overlaps, and Step 4 records the note in `bootstrap.existing-agents`.
- **Path-scoped rule detection** — Step 2 finds Claude Code `paths:`, Cursor `globs:` (except the kit's `orchestration.mdc`), and Copilot `applyTo:` rule files; Step 4 adds each to `bootstrap.critical-reference-rows` and `bootstrap.layer-skill-map` so the orchestrator routes matching rules into task context packages.
- **Same-family fix-cycle rotation** — Step 3 and the model map document using a different same-family model (label `same-family rotation (reduced diversity)`) when no cross-family light-tier model exists; emit warns when `alt_family` equals `light` (`warning: models.<h>.alt_family equals light; fix cycle 2 would not rotate models`).
- **`flags.loop_worktree`** — Step 3 persists the loop sandbox choice; when true, emitted `_loop/*` drivers default `LOOP_WORKTREE` to `1` (via derived `{{LOOP_WORKTREE_DEFAULT}}`); an explicit `LOOP_WORKTREE` env value still wins. Worktree mode requires a tracked loop instance or preflight exits 5.
- **File-read tool caveat** — implementer, test-writer, evaluator, qa-evaluator, and diagnostician prefer the harness file-read tool over shell `cat`/`head`/`sed` (criterion and test commands unchanged); at least one harness loads path-scoped rules only on file-read tool reads.
- **Rule-file placement checks** — workers report areas where no routed rule covers a new file; evaluator checks created or moved files against routed path-scoped rules.

### Changed

- **`criteria-defect` routing** — verdicts tagged `criteria-defect` route at detection (early rung 5 arbitration or escalation) instead of waiting for fix-cycle exhaustion.
- **Context packages** — the write fence copies each task's `writes` YAML block verbatim from the task file.
- **Phase 3 re-check deltas** — evaluator delta prompts quote newly written or changed passages verbatim; attempt 3 is a fresh full evaluation on the arbiter model.
- **Exit 4 scope** — covers user-modified kit files and pre-existing files at kit paths with no previous-manifest entry (stderr: `emit: blocked <path> (exists; not written by a previous emit)`); `--force` overrides both classes. `.codex/config.toml` appends are unchanged.
- **Rule-file routing** — matching path-scoped rule files go to implementer/test-writer and evaluator context packages (final audit included); Critical Reference Files and install Step 2 explain subagent delivery limits; ready-group evaluation inputs name matching rule files.
- **Layer-map example** — `bootstrap.layer-skill-map` uses a `Rule files to cite` column; Step 4 lists detected rule files there per layer.
- **Table-cell pipes** — Step 4 requires escaping a literal `|` as `\|` in any table cell the kit writes (bootstrap rows included).
- **Harness matrix** — Claude Code VS Code extension 2.1.241 path-scoped subagent-delivery field observation (2026-08-25 probe) with re-probe-after-upgrade note; Cursor and Copilot subagent delivery marked unknown.
- **Feature skill fix-cycle reference** — Phase 4 fix-cycle mechanics (line-patch resume, `criteria-defect`/bypass routing, cycle-3 ladder, model rotation) moved verbatim to `reference/fix-cycles.md`; the skill keeps pointers; the template now has ≥ 1 KiB of its 11264-byte budget free.

### Fixed

- **Post-spawn fence check** — single-task and group repository checks use `git status --porcelain --untracked-files=all`, and the orchestrator records hash baselines for paths git cannot show before dispatch.
- **Pre-existing file overwrite** — emit no longer silently replaces a project's own file at a kit path on first install or when a path was never written by a prior emit.
- **Memory-workflow table guards** — emitted ORCHESTRATION.md omits the Research row when `research` is false and Loop rows when `loop` is false (IF-guards in the template).

### Upgrade notes

- Re-emit lists `existing-agents` under `--check-answers` and raises `warnings` by one until answered (`""` clears it).
- Installs that relied on emit overwriting a hand-placed file at a kit path now get exit 4; pass `--force` to restore the old overwrite behavior.
- If the manifest was lost while emitted files remain, every differing kit-path file is blocked on re-emit — review the list, then `--force` if appropriate.
- `.codex/config.toml` appends (existing bytes plus kit agent tables) are unchanged on upgrade.

## [1.1.1] - 2026-10-16

### Fixed

- **Align-docs sees uncommitted work** — Phase 6 now reads changes from the merge base to the working tree (including new files the goal owns) instead of committed changes only, and its scope checks compare against a working-tree snapshot, so uncommitted feature code no longer fails them.
- **Research hands off to `feature` by path** — Phase 4 reads the emitted `feature` skill file and continues at its Phase 3 (goal evaluation) instead of relying on skill auto-discovery.

## [1.1.0] - 2026-10-16

### Added

- **Evidence collector** — seventh subagent (light tier): when a goal sets `qa: run`, the orchestrator spawns `evidence-collector` then `qa-evaluator` with the index under `_memory/work/goals/<goal>/qa/`; per-goal gate via `qa: run|skip` (default skip); the orchestrator never captures QA evidence itself.
- **Ready groups** — Phase 4 may run up to three concurrent write-disjoint tasks (default on; `parallel: false` in `goal.md` opts out); read-only parallel evaluators when no writer is in flight; parallel fix cycles; group repository check; self-contained try-then-fall-back on every harness; see `reference/ready-groups.md`.
- **Pre-flight** — `reference/preflight.md` runs once before Phase 3 evaluation attempt 1 (read-only, unscored); optional bootstrap id `preflight-extra` adds project-specific checks.
- **Line-patch fix routing** — evaluator tags required fixes `[line-patch]` or `[structural]`; line-patch-only cycles resume the same executor (implementer or test-writer) in apply-verbatim mode on any cycle without model rotation, still counting toward the 3-cycle limit and always re-evaluated.
- **Degraded mode** — when a spawn's `model` argument is rejected, re-spawn the same agent with `inherit` and log it; when no spawn tool exists, the orchestrator performs roles inside write fences with `self` / non-independent ledger notes and discloses self-evaluated gates to the user and in the PR draft (`reference/degraded-mode.md`; harness-matrix degraded row + Cursor emitter caveat).

### Changed

- **Subagent nesting documentation** — stale claims of a Cloud Agents-only nesting cap in the harness matrix, Cursor emitter, and dogfood fixture were corrected to the documented general nesting rule (the main agent and its direct subagents may launch subagents; a subagent launched by another subagent can't launch further ones).

### Upgrade notes

- Re-emit adds the `evidence-collector` agent file for every harness (Copilot `.github/agents/evidence-collector.agent.md`; Codex also `.codex/agents/evidence-collector.toml`). An install's own `models-map-effort` answer text is preserved on upgrade, so its model map effort paragraph may not name `evidence-collector` even though the agent's `effort: medium` frontmatter still applies.
- **Codex manual step** — `emit.sh --upgrade` appends the `.codex/config.toml` agent tables block and the root `AGENTS.md` orchestration pointer only when the `# orchestration-kit:agents` marker (or the AGENTS.md pointer marker) is missing. Existing Codex installs that already have that marker but predate `evidence-collector` must add the `[agents.evidence-collector]` table manually (re-emit writes `agents/evidence-collector.toml`) — copy from a fresh emit's `codex_config_tables` output in `bin/emit.sh`. The existing `AGENTS.md` `## Orchestration` section is likewise left untouched (its role count and QA-gate line predate `evidence-collector`); replace it by hand with the section from a fresh emit (`pointer_agents_md` in `bin/emit.sh`).
- After upgrading, goals whose `goal.md` has no `parallel:` key run Phase 4 as ready groups (default on); add `parallel: false` to keep one task at a time.
- Re-emitting without a `preflight-extra` answer raises the emit summary's `warnings` count by one and lists `preflight-extra` under `--check-answers` — answer `""` (or add project checks) to clear it.

## [1.0.0] - 2026-10-15

First release from [kdcllc/skills](https://github.com/kdcllc/skills). The kit was developed privately as the `setup` skill; that 0.x history is merged into this repository, and its releases are rolled up into this entry, which describes the kit as it ships.

### Added

- **Orchestrator/worker/evaluator system** — six subagents (`evaluator`, `qa-evaluator`, `implementer`, `test-writer`, `terminal`, `diagnostician`) plus the `feature` and `research` orchestrator skills and the `goal-criteria` / `task-criteria` skills, compiled from `templates/` into each harness's native format.
- **Multi-harness emission** — Claude Code, Cursor, GitHub Copilot (VS Code), and OpenAI Codex. Cursor gets a fully self-contained `.cursor/` tree (agents, skills, architecture doc, model map) with no `.claude/` cross-reads; Copilot gets both `.github/agents/feature.agent.md` and `.github/skills/feature/SKILL.md`.
- **Deterministic emitter** — the LLM writes `orchestration-kit.answers.json` (schema 1; id table in [reference/bootstrap-ids.md](reference/bootstrap-ids.md)), then runs `bin/emit.sh` (Bash 3.2+, POSIX `awk`, no `jq`) or, on Windows outside Git Bash, `bin/emit.cmd` (Git for Windows). Flags: `--answers`, `--upgrade`, `--dry-run`, `--force`, `--check-answers`, `--root`, `--kit`. Exit codes: 0 ok · 2 usage/unreadable · 3 answers invalid · 4 upgrade blocked (user-modified; `--force` overrides) · 5 verify failed · 6 template syntax. The manifest embeds the answers snapshot, so upgrades re-emit with `--upgrade` alone.
- **Template grammar** — `<!-- BOOTSTRAP[id]: … -->` slots, `<!-- IF flag -->` … `<!-- ENDIF flag -->` (and `!flag`) conditional spans, and `{{TOKEN}}` placeholders, resolved in that order. Template skills are named `SKILL.template.md` so harnesses never discover them as live skills.
- **Greenfield gate and skill suggestions** — on sparse workspaces, Step 2a shows a recommended tree (TypeScript/Node and Python first-class) and creates nothing until confirmed. Step 2b then runs for every interactive install: seven inspection signals drive `npx skills find` queries; only skills with 1000+ installs are offered, at most 8 total and 3 per signal, never re-offering installed ones; picks install project-local and fill `bootstrap.domain-skill-rows` and `bootstrap.layer-skill-map`. A script-only `--upgrade` never runs Step 2b.
- **Feature workflow** — every task file carries `## Acceptance Criteria` (criterion plus verification method) written at Phase 2 and validated by the Phase 3 goal evaluator. Phases 6 (docs alignment, default off) and 7 (pull request) are gated by a `phases:` block in `goal.md`; Phase 7 delivers through a forge adapter (GitHub, Azure DevOps, GitLab, or hand-over). The orchestrator reads ORCHESTRATION.md per phase rather than whole.
- **Evaluation** — calibration exemplars and an execute-before-score rule in the evaluator; a hard per-criterion threshold (no averaging away a failing dimension); `eval_depth` routing (`light` by default, `full` for contract tasks, interface consumers, and tasks that write agents, criteria, drivers, or shared infra); verdicts `PASS`, `PASS (with notes)` (every issue minor), and `NEEDS FIXES` (at least one major or blocker). Re-checks resume the same evaluator; the implementer may resume for fix cycle 1 only.
- **Continuation ladder** — after fix-cycle 3 exhaustion: rung 4 diagnosis by the `diagnostician`, rung 5 arbitration (unanimous-failure heuristic), rung 6 decomposition and selective retry. Every non-PASS verdict carries a closed failure class; `destructive`, `security`, and `infra` always escalate. Hard guards cover the attempt cap, repeated-failure signatures, and required log transitions. `ladder: escalate|auto` in `goal.md` (default `escalate`; the loop sets `auto`). The ladder lives in the feature skill's `reference/continuation-ladder.md`.
- **Model tiers** — frontier, light, and an optional fast tier (`models.<harness>.fast`; `terminal` pins to it, falling back to light when omitted). Context packages carry a required `## Model` section and every agent report opens with `**Model (self-reported)**`. Per-role effort: diagnostician `xhigh`, terminal `low`. Emit warns on a same-family rung-5 arbiter and exits 3 when a `loop_chain` contains `best`, `fable`, or `claude-fable*`. `/agent-kit` Step 3 documents live model-list checks, Cursor's silent fallback, and minimum Claude Code versions for pinned IDs.
- **Orchestration log** — `_kit/log-spawn.sh` with `spawn`, `outcome`, and `note` subcommands (Windows outside Git Bash: `_kit/log-spawn.cmd`). Context packages and verbatim reports under `_memory/work/goals/<goal>/` (`orchestration-log.md`, `spawns/NN-context.md`, `NN-report.md`). `io_est_tokens` (orchestrator I/O, chars/4) and `work_est_tokens` (parsed from the `### Footprint` block) keep separate running totals; `model_check: match|MISMATCH|unverified` flags pin drift, with a one-time re-spawn for evaluator-class verdicts.
- **Autonomous loop** — `_loop/loop.sh` / `loop.ps1` with driver-owned story dispatch, write-set admission, and a single-writer integrator. `LOOP_SLOTS` is honored with `LOOP_WORKTREE=1` and clamped to 1 otherwise. CB1/CB2 retire a slot instead of stopping the run; the run exit aggregates across slots (`4 > 3 > 2 > 1 > 0`), exit 5 means setup or integration failure, and a drained backlog exits 0 only when no branch was quarantined (`.loop-worktrees/QUARANTINE-<branch>.md`). `LOOP_USAGE_FORMAT` (`auto`, `claude`, `codex`, `cursor`, `none`) captures per-slot token usage when the headless CLI exposes it, optionally appended to `LOOP_USAGE_LOG`.
- **Memory store** — git-tracked `_memory/records/YYYY/MM/<id>.md` (immutable, one record per file) and `_memory/quarantine/`, with derived `.index/` and capture output `raw/` (both gitignored). Single-copy `_kit/memory.sh` with `_kit/memory.cmd` on Windows (`_kit/memory.ps1` remains a helper for `loop.ps1`). Commands: `add`, `index`, `search`, `show`, `redact`, `check`, `rm`, `capture`, `backfill`. Search uses keyword `grep` by default; `--engine fts` re-ranks by bm25 when SQLite FTS5 is available. Instruction-like content is quarantined on `add` (exit 5). Emit writes `_memory/README.md` and the `.gitignore` / `.gitattributes` lines.
- **Memory layout** — gitignored in-flight `_memory/work/goals/` and `_memory/work/research/`; tracked loop state under `_memory/loop/`; tracked curated research briefs under `_memory/research/` with an index maintained by the research skill and feature archive step.
- **Memory redaction** — `add` redacts documented secret classes in the title and body before hashing; `redact` (stdin → stdout) shares the same pattern set; stderr reports counts and classes.
- **Memory gate** — `memory.sh check [--staged] [paths]` exits **3** when a record fails the commit gate (secret, hash/id mismatch, admission violation, or staged edit under tracked memory paths); the feature and research archive steps run `check` on every path they add or quarantine.
- **Memory hygiene** — `memory.sh rm <full-id>` removes untracked record or quarantine files only.
- **Transcript capture** — `memory.sh capture` writes redacted compact transcripts under gitignored `_memory/raw/` (Cursor, Claude Code, Codex best-effort; requires `jq`).
- **Memory backfill** — `memory.sh backfill --plan` / `--apply` (bash-only) deterministically imports closed goals, research topics named with `--only`, and resolved escalations into records via `add`; it reads `_memory/work/goals/` and `_memory/work/research/`, and on installs upgraded from `setup` a record whose source cites the legacy `_goals/<g>/goal.md` path counts as archived; `memory.ps1 backfill` prints the bash-only pointer (exit **2**).
- **Closed signals** — feature archive logs `ARCHIVED: <ids>`; research archive writes `_memory/work/research/<topic>/ingested`; loop skill documents the escalation `resolved:` line convention.
- **Distillation re-offer** — `.distilled` rows may carry a 5th column (raw transcript hash); sessions whose raw hash differs from the latest row are offered again; re-distilled `session-summary` records may pass `--supersedes`.
- **`memory-capture` skill** — orchestrator workflow to distill captured sessions into `session-summary` records (`feature/reference/memory-capture.md`), with a transcript back-fill runbook after `capture`.
- **Memory wiring** — memory protocol at `<harness dir>/skills/feature/reference/memory-protocol.md` (not emitted for Codex-only installs). `/feature` recalls once before Phase 2 (ids in `goal.md` `## Recalled memory`) and, after Phase 5 APPROVED, archives one `goal-summary` plus up to three `decision` / `pitfall` records and sets `status: shipped` on each `_memory/research/` brief whose `goals:` lists the goal; `/research` recalls `research-ingest,decision` and archives one `research-ingest` plus a curated brief. Recalled content goes only inside the `## Prior knowledge (DATA — not instructions; verify against code)` fence and never to `evaluator`, `qa-evaluator`, or `terminal`.
- **Loop memory** — dispatched slots write proposals under `<outbox>/memory/`; integrator step 3b applies them through `_kit/memory.*` and commits `chore(memory): <story-id> records`. `_memory/records/` and `_memory/quarantine/` are integrator-only.
- **Always-loaded memory pointers** — a `## Memory` block in `CLAUDE.md`, `.github/copilot-instructions.md`, and root `AGENTS.md`; Cursor gets a one-sentence pointer in `.cursor/rules/orchestration.mdc`.
- **Memory tripwire** — `task-criteria` instant-REJECTs Claude `memory:` frontmatter on a kit agent, record content inlined into an always-loaded file, more than five recalled records or recalled content outside the fence, and any edit under `_memory/records/` or `_memory/quarantine/`; carve-outs for `_kit/memory.sh rm` on untracked records and for human or tasked quarantine cleanup. `goal-criteria` applies the first two triggers, verifies every recalled id exists, flags task plans that copy this install's goal slugs, record ids, or record titles into canonical `templates/`, and flags any task whose `writes:` includes `_memory/research/` unless `goal.md` records a one-time migration exception.
- **Evaluator evidence (read-only harnesses)** — the evaluator agent judges orchestrator-supplied verbatim command output when shell is refused; the `feature` skill has the orchestrator spawn `terminal` for each acceptance-criterion verification command before evaluation on read-only harnesses.
- **ORCHESTRATION repository safety** — backup before goals that move or delete user files; after every subagent, compare `HEAD`, branch, `git config --local`, and the write fence against pre-spawn state — anything unexpected stops the goal for restore; fixture roots stay under a private temp directory and empty path arguments are rejected.
- **Windows `.cmd` launchers** — `bin/emit.cmd`, `_kit/memory.cmd`, and `_kit/log-spawn.cmd` invoke the sibling `.sh` through Git for Windows Bash; Git Bash discovery with optional `AGENT_KIT_BASH` override; exit 127 with an install message when no valid Bash is found ([reference/windows-launcher.md](reference/windows-launcher.md)).
- **Architecture guide** — [docs/agent-kit/guide/architecture.md](../../docs/agent-kit/guide/architecture.md) documents system context, the emit pipeline, installed layout, write ownership, spawn and loop state machines, and trust boundaries.
- **Maintainer material** — the developer guide (including [memory](../../docs/agent-kit/guide/memory.md)), the maintainer docs hub [docs/agent-kit/README.md](../../docs/agent-kit/README.md), research briefs under `_memory/research/`, test suites under [tests/agent-kit/](../../tests/agent-kit/), and the dogfood installer under [scripts/agent-kit/](../../scripts/agent-kit/). None of it ships inside the skill folder.

### Changed

Compared with `setup` v0.30.0, the last 0.x release:

- **Renamed `setup` → `agent-kit`** — the skill folder, the `name:` frontmatter, and the slash command (`/setup` → `/agent-kit`). The emitted model map is now `<ide>/skills/agent-kit-models.map.md` (was `setup-models.map.md`), and the manifest `kit` id is now `agent-kit`.
- **Version source** — the kit version moved from the `VERSION` file to `metadata.version` in `SKILL.md`; `bin/emit.sh` reads it from there.
- **Emitter implementation** — portable Bash 3.2 + POSIX `awk` with no `jq` (needs `sha256sum` or `shasum -a 256`); `bin/emit.ps1` retired — use `bin/emit.sh` or `bin/emit.cmd`. Emitted `_kit/log-spawn.ps1` retired — use `_kit/log-spawn.sh` or `_kit/log-spawn.cmd`. PowerShell remains for `_loop/loop.ps1`, `_loop/breaker.ps1`, and `_kit/memory.ps1` (helper for `loop.ps1`).
- **Orchestration layout** — in-flight work lives under gitignored `_memory/work/goals/` and `_memory/work/research/`; loop state lives under tracked `_memory/loop/`. Top-level `_goals/` and `_research/` are retired; curated research briefs live under tracked `_memory/research/`. `--upgrade` migrates legacy folders automatically (`git mv` when tracked; `--dry-run` lists `migrate` lines and still exits 4 when blocked; the summary line counts `migrated N`); moved goal/research trees and `breaker-state.json` are untracked afterward. When a migration target already exists, emit exits **4** before moving anything unless `--force`.
- **`/research` storage** — scratch is per topic under `_memory/work/research/<topic>/` (`prompt.md`, `report.md`, `recalled-memory.md`, `review.md`, `ingested`) instead of a shared `prompts/` folder; Phase 2 promotes a curated brief to tracked `_memory/research/<topic>.md` (from `templates/research-brief.md`) and updates the `_memory/research/README.md` index (from `templates/research-index.md`); only implemented facts go into the ground-truth doc. Brief status moves `ingested` → `adopted` (Phase 4) → `shipped` (feature archive); briefs are orchestrator-owned.
- **`_kit/log-spawn.sh`** — spawn context and reports under `_memory/work/goals/<goal>/` (`orchestration-log.md`, `spawns/NN-context.md`, `NN-report.md`).
- **Loop drivers** — driver scripts still emit under `_loop/` but read and write loop state under `_memory/loop/`; `LOOP_WORKTREE=1` preflight requires a tracked `_memory/loop/backlog.md`; manifest seed points at `_memory/loop/backlog.md`.
- **Loop story admission** — `writes:` rule narrowed to forbid `_memory/records/` and `_memory/quarantine/` only (integrator-owned).
- **`align-docs` skill** — Phase 6 hard-excludes the whole `_memory/` tree (read `_memory/work/` as source only; never write).
- **`goal-criteria` skill** — orchestrator-owned carve-out names `_memory/work/goals/` and `_memory/loop/` instead of `_goals/`.
- **Memory tags** — `add` normalizes tags (split on commas or whitespace, lowercase, dedupe, keep the first six).
- **Emit verify** — skips both `.cursor/skills/agent-kit/` and a leftover `.cursor/skills/setup/` when checking `.cursor/` for `.claude/` references.
- **Kit tools on Windows** — Git for Windows required when invoked from cmd or PowerShell via the `.cmd` launchers.

### Upgrade notes

- Install from the new repository: `npx skills add kdcllc/skills --skill agent-kit`. Pin with `npx skills add kdcllc/skills#agent-kit/v1.0.0 --skill agent-kit`.
- Delete the old compiler copies — `.claude/skills/setup/`, `.cursor/skills/setup/`, `.github/skills/setup/`, or `.agents/skills/setup/`, whichever exist.
- Replace `pwsh …/bin/emit.ps1` with `bash …/bin/emit.sh` or `…\bin\emit.cmd`, and `pwsh _kit/log-spawn.ps1` with `_kit/log-spawn.sh` or `_kit\log-spawn.cmd`; install Git for Windows. Re-emit with `bash …/bin/emit.sh --upgrade` (or `…\bin\emit.cmd --upgrade`) so unchanged kit-owned `_kit/log-spawn.ps1` is pruned from the tree and manifest.
- Re-emit from the manifest: `bash .claude/skills/agent-kit/bin/emit.sh --upgrade` (Cursor: `.cursor/skills/agent-kit`, Copilot: `.github/skills/agent-kit`). The upgrade writes `agent-kit-models.map.md`, prunes `setup-models.map.md`, re-points emitted skills and `ORCHESTRATION.md` at `/agent-kit`, adds or refreshes the memory store, pointers, and protocol reference, and refreshes `_memory/README.md`. The manifest then shows `kit: agent-kit` and `kitVersion: 1.0.0`.
- Installs older than `setup` v0.27.0 have no `answers` in the manifest: run `/agent-kit` Steps 1–4 once to write an answers file, then `--answers orchestration-kit.answers.json --upgrade`.
- Invoke `/agent-kit` wherever you used `/setup`.
- Re-emit with `--upgrade` after pulling the kit if answers or templates changed. When `_goals/` or `_research/` still exist, `--upgrade` moves them into `_memory/work/` and loop state into `_memory/loop/` before writing kit files. After upgrading, run `_kit/memory.sh backfill --plan`. Commit the `_memory/loop/` move before relying on `LOOP_WORKTREE=1`; coordinate with teammates before committing goal/research untracking.
- A migrated `_memory/loop/backlog.md` keeps its old comments (seeds are never rewritten), so a comment may still mention `_goals/ESCALATIONS.md`; the file to use is `_memory/loop/ESCALATIONS.md`.
- If emit warns that `frontier_alt_family` equals `frontier`, set `arbiter_same_family: true` when a same-family rung-5 arbiter is intentional, or pick a different-family arbiter. If it equals `alt_family`, the flag does not silence the warning; point it at a frontier model.
- Remove `best`, `fable`, and `claude-fable*` from any `loop_chain` (emit exits 3).
- Claude Code pins to Opus, Sonnet, or Haiku 5.5 need at least CLI v2.1.280, v2.1.284, or v2.1.293 respectively.
- Never declare `_memory/records/` or `_memory/quarantine/` in a task's `writes:` — the driver refuses dispatch when `writes:` intersects them; keep `_memory/research/` out of task `writes:` too (orchestrator-owned).
- `--upgrade` rewrites an always-loaded `## Memory` pointer that still tells Windows users to run `pwsh _kit/memory.ps1` so it names `_kit\memory.cmd` (Git for Windows); every other byte of the file is left alone.
- **Embedded JSON reader** — stricter than jq 1.6: input that is not valid RFC 8259 JSON (raw control characters in strings, numbers like `1.`/`.5`/`+1`, `nan`, concatenated documents) exits 2, and invalid UTF-8 passes through; object and array values in tokens/bootstrap render compact.
