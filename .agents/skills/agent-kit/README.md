# AI Orchestration Kit (`agent-kit`)

> Kit version: **1.1.2** (`metadata.version` in [SKILL.md](SKILL.md)) · Version history: [CHANGELOG.md](CHANGELOG.md)

A portable orchestrator/worker/evaluator multi-agent system for AI coding harnesses —
**Claude Code, Cursor, GitHub Copilot (VS Code), and OpenAI Codex** — packaged as one
installable `agent-kit` skill that compiles a single canonical template source into each
harness's native format.

## Quick start

```bash
# 1. Install the agent-kit skill into your project (see §Install for options)
npx skills add kdcllc/skills --skill agent-kit

# 2. In a session inside the project, compile the kit for your harness(es)
/agent-kit

# 3. Start your first orchestrated feature
/feature
```

Optional: start an unattended run (sandboxed!) with `_loop/loop.sh 10` or
`pwsh _loop/loop.ps1 10` (PowerShell 7+).

## What you get

- A **seven-phase feature workflow** (`/feature`): alignment → goal creation → goal
  evaluation → task execution → final audit → optional docs alignment → optional
  approval-gated pull request. Acceptance criteria are defined at planning and
  validated at Phase 3; Phase 6 is off by default (`align_docs: false`); Phase 7 remains
  gated on `goal.md`'s `phases:` block. After cycle-3 exhaustion, interactive `/feature`
  escalates with the continuation ladder offered (`phases.ladder: escalate`, default);
  the autonomous loop sets `ladder: auto`. No phase advances without an evaluator
  verdict; fixes are always re-evaluated (3-cycle limits, explicit escalation).
- **Seven subagents with tiered model pinning**: `evaluator` and `qa-evaluator` on the
  frontier tier (effort high), `diagnostician` on the frontier tier (effort `xhigh`),
  `implementer`, `test-writer`, and `evidence-collector` on the light tier (effort medium), and `terminal` on
  the fast tier (effort low — when an install omits `fast`, terminal falls back to the
  light model) — every spawn passes its model explicitly and agents self-report in the
  first line of each report (`**Model (self-reported)**: ...`). `terminal` runs Bash or
  PowerShell and returns only the result the caller asked for, so the raw stream stays
  out of the frontier session. Model IDs are configuration (`models.map.md`), with
  per-tier fallback chains, a never-fall-up rule, and a cost-ceiling policy.
- **Hardened evaluation** (patterns adopted from studying
  [bradygaster/squad](https://github.com/bradygaster/squad)): existence checks with a
  ✅/⚠️/❌/🔍 confidence ladder and anti-fabrication rules, a required devil's-advocate
  section in goal evaluation, fix-cycle **model rotation**, execute-before-score,
  `PASS (with notes)` for wording-only minors, `eval_depth: light` default (with stated
  `full` triggers), a post-exhaustion **continuation ladder**, and an append-only
  **orchestration log** per goal with `io_est_tokens` (orchestrator I/O proxy, chars/4)
  and `work_est_tokens` (subagent self-reported Footprint /4) — appended by the emitted
  `_kit/log-spawn.sh` (Windows outside Git Bash: `_kit\log-spawn.cmd`; Git for Windows required), with every context package and verbatim report
  stored under `_memory/work/goals/<goal>/spawns/`. How each piece arrived is in
  [CHANGELOG.md](CHANGELOG.md); mechanics are in
  [evaluation-system.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/evaluation-system.md).
  The research behind the continuation ladder is
  [autonomous-escalation.md](https://github.com/kdcllc/skills/blob/master/_memory/research/autonomous-escalation.md).
- A **staged test ladder** (`test-ladder`): new tests → impacted tests mid-cycle; full
  suites at cycle end — in a goal's designated closer task when it has one, and in the
  orchestrator's Phase 5 Quality Checks.
- An optional **autonomous loop** (`auto-loop` + `_loop/loop.sh` / `_loop/loop.ps1`):
  one backlog story per fresh-context iteration, evaluation-gated commits, circuit
  breakers enforced in the loop drivers (not prose), optional parallel slots in
  driver-managed worktrees, a six-code exit contract, real per-iteration token usage
  capture when the headless CLI exposes it (`LOOP_USAGE_FORMAT`), and a single
  human-approved PR at run end. Knobs, exit codes, and the safety model are documented in
  [autonomous-loop.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/autonomous-loop.md).
- A **deterministic emitter** (`bin/emit.sh`; Windows outside Git Bash: `bin\emit.cmd`; Git for Windows required) in the installed `agent-kit` skill: after the LLM
  interview, one answers file and one script command compile canonical templates into
  every targeted harness — same inputs yield byte-identical output; upgrades re-emit
  from manifest-embedded `answers`.
- A **git-tracked memory store** (`_memory/` + `_kit/memory.sh` and `_kit\memory.cmd` on Windows; `_kit/memory.ps1` remains a helper for `loop.ps1` until loop twins retire): orchestrator recall before planning, archive at goal close, searchable immutable records, DATA fence for workers, loop integrator proposals. See [memory.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/memory.md).

## Documentation

Developer guide: [docs/agent-kit/guide/README.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/README.md).

| Guide | Description |
|-------|-------------|
| [architecture.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/architecture.md) | How the kit is built: components, emit pipeline, folder ownership, state machines |
| [getting-started.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/getting-started.md) | Install paths, `/agent-kit` compile flow, greenfield gate, multi-harness emission, manifest basics |
| [decision-guide.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/decision-guide.md) | Choosing direct edit, `/feature`, `/research` → `/feature`, or autonomous loop; flowchart, mode comparison, anti-patterns |
| [feature-workflow.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/feature-workflow.md) | Seven phases in depth, acceptance criteria at planning, optional Phases 6/7, fix-cycle rotation, escalation, orchestration log, condensed worked example |
| [research-workflow.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/research-workflow.md) | Why research precedes implementation, prompt/report artifacts, ingestion into a goal, when to skip |
| [autonomous-loop.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/autonomous-loop.md) | Drivers, backlog stories, iteration lifecycle, circuit breakers, slots/worktrees, exit codes, quarantine, safety model |
| [agents-and-models.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/agents-and-models.md) | Seven subagent roles and boundaries, model tiers, `models.map.md` anatomy, fallback chains, harness caveats |
| [evaluation-system.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/evaluation-system.md) | Verdict vocabulary, confidence ladder, anti-fabrication, devil's advocate, acceptance criteria validation, `eval_depth`, test ladder, orchestration log audit trail |
| [contributing.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/contributing.md) | Repo anatomy (canonical vs instance vs generated), self-install dogfood loop, templates/emitters, harness matrix, version + manifest + upgrades, test harness |
| [memory.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/memory.md) | `_memory/` store, recall and archive per workflow, search CLI, redaction, `check` gate, transcript capture, prior-knowledge fence, loop proposals and integrator step 3b, harness pointers |

## What's in this folder

| Path | What it is |
|------|------------|
| `SKILL.md` | The `/agent-kit` workflow (detect → greenfield gate → inspect → skill suggestions → interview → emit) and the placeholder table; `metadata.version` is the kit version |
| `bin/` | `emit.sh` + `emit.cmd` (Windows launcher) — deterministic emitter (flags and exit codes in [bin/README.md](bin/README.md)) |
| `templates/` | The canonical source: architecture doc, `models.map.md`, seven agents, the skills (each a `SKILL.template.md`, renamed to `SKILL.md` at emit), the loop drivers, and the `_kit/` tools |
| `emitters/` | Per-harness caveats (live model-check URLs, silent-fallback warnings) |
| `reference/` | `harness-matrix.md` (verified harness facts) and `bootstrap-ids.md` (answers-file id table) |
| `CHANGELOG.md` | Version history; 1.0.0 rolls up the 0.x releases from before the move to kdcllc/skills |

Maintainer material lives in the [kdcllc/skills](https://github.com/kdcllc/skills) repository, outside this folder, so it never ships with the skill: the developer guide under `docs/agent-kit/`, research briefs under `_memory/research/`, the test suites under `tests/agent-kit/`, and the dogfood installer under `scripts/agent-kit/`.

## Install into a project

```bash
# Option A — skills CLI (any agent)
npx skills add kdcllc/skills --skill agent-kit

# Pin to a release
npx skills add kdcllc/skills#agent-kit/v1.1.2 --skill agent-kit

# Option B — agent-skills-cli
npx agent-skills-cli install https://github.com/kdcllc/skills.git
```

Claude Code and Copilot CLI users can also install the whole pack with
`/plugin marketplace add kdcllc/skills` and `/plugin install kdcllc-skills@kdcllc`.

Or copy the skill in manually (any harness dir works — the skill detects and
asks):

```bash
cp -r skills/agent-kit  <your-project>/.claude/skills/     # Claude Code
cp -r skills/agent-kit  <your-project>/.cursor/skills/     # Cursor
```

**Greenfield / sparse directory:** On an empty or near-empty workspace, `/agent-kit` runs
Step 2a (the greenfield gate) and **asks** before scaffolding. It **shows** a
recommended project tree and **creates nothing until you confirm**. First-class layouts
are **TypeScript/Node** and **Python**; other stacks get a generic `src/` + `tests/`
tree. Non-sparse repos skip the scaffold offer only.

**Skill suggestions (Step 2b):** Runs for **every project** after Step 2 inspect —
greenfield accept/decline and non-sparse alike — following the
[find-skills](https://www.skills.sh/vercel-labs/skills/find-skills) workflow without
installing that skill. Inspection signals include a web UI, the test framework (e.g.
`pytest`), backend/web frameworks, infra/DevOps files, docs surfaces, and
databases/ORMs; only skills with **1000+** installs are offered, at most **8**
candidates total. You pick; skills install project-local with
`npx skills add <owner>/<repo> --skill <picked-skill> -y`. Already-installed skills
are never re-offered; picked skills are recorded in the emitted `ORCHESTRATION.md`
skills table and the feature skill's layer → skills map.

Then, in a session inside that project, run `/agent-kit`. It detects which harnesses to
target (multiple is normal), inspects the repo (stack, test commands, layers,
user-facing surfaces, existing project agents), suggests skills.sh skills from what it found (Step 2b),
interviews you for what it can't infer (project name, model
tiers, QA surfaces, research workflow, autonomous loop, delivery forge), writes
`orchestration-kit.answers.json`, and runs the emitter:

```bash
bash .claude/skills/agent-kit/bin/emit.sh --answers orchestration-kit.answers.json
# Windows outside Git Bash (Git for Windows required; forward slashes in path args):
# .claude\skills\agent-kit\bin\emit.cmd --answers orchestration-kit.answers.json
# (Cursor: .cursor/skills/agent-kit; Copilot: .github/skills/agent-kit)
```

If a manifest already
exists, run with `--dry-run` first. See [bin/README.md](bin/README.md) for flags and
exit codes.

| Generated | Purpose |
|-----------|---------|
| `agents/evaluator`, `agents/qa-evaluator` | Skeptical reviewers — frontier tier, existence checks + confidence ladder |
| `agents/diagnostician` | Root-cause analysis after fix-cycle exhaustion — frontier tier, no code writes |
| `agents/implementer`, `agents/test-writer` | Workers — light tier, ladder rungs 1–2 only |
| `agents/evidence-collector` | QA evidence for the optional gate — light tier, no verdicts, writes only under the goal's `qa/` folder |
| `skills/feature` | Seven-phase workflow + goal/task templates + orchestration log + memory protocol reference |
| `skills/research` | Research → Plan workflow (optional) |
| `skills/memory-capture` | Post-hoc transcript capture and distillation into `session-summary` records |
| `skills/{goal,task,qa}-criteria` | Evaluation checklists (goal evaluation includes devil's advocate) |
| `skills/test-ladder` | New → impacted tests mid-cycle; full suites only at cycle end |
| `skills/align-docs` | Phase 6: evaluator-gated sync of all docs to shipped code |
| `skills/ship-pr` | Phase 7: approval-gated forge delivery (GitHub / Azure DevOps / GitLab / hand-over) |
| `skills/auto-loop` + `_loop/` + `_memory/loop/backlog.md` | Autonomous loop with structural guards (optional) |
| `skills/agent-kit-models.map.md` | The model map — the only place model IDs live per install |
| `_kit/log-spawn.sh` + `_kit/log-spawn.cmd` | Single-copy orchestration-log writer + Windows launcher (`spawn` / `outcome` / `note`) |
| `_kit/memory.sh` + `_kit/memory.cmd` (+ `_kit/memory.ps1` for `loop.ps1`) | Single-copy memory store + Windows launcher (`add` / `index` / `search` / `show` / `redact` / `check` / `rm` / `capture` / `backfill`) |
| `_memory/` | Tracked records (`records/`, `quarantine/`, `loop/`); gitignored scratch `work/` plus derived `.index/` and `raw/` |
| `ORCHESTRATION.md` | The architecture doc, filled in for the project |
| `orchestration-kit.manifest.json` | Kit version + file hashes + embedded `answers`, enabling clean upgrades |

Everything is generated with project-specific content. Layer order, test commands, evaluator auto-fail triggers, and model IDs are derived from the codebase and your answers, never left generic.

`bin/` arrives with every installed skill copy (it sits beside `SKILL.md` in each `skills/agent-kit`); it is not an emit-set/manifest path.

Targeting Cursor emits a self-contained `.cursor/` tree containing agents, skills, the architecture doc, and the model map, with no dependency on `.claude/`.

Start your first feature with `/feature`.

Start an unattended run (sandboxed!) with `_loop/loop.sh 10` or `pwsh _loop/loop.ps1 10` (PowerShell 7+).

Loop driver behavior (dispatch, slots, worktrees, circuit breakers, exit codes) is
documented in [autonomous-loop.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/autonomous-loop.md).

## Model tiers

Three tiers — frontier, light, and fast — pin orchestrator/evaluators/diagnostician,
implementer/test-writer/evidence-collector, and terminal respectively (installs without a `fast` pin run
terminal on light). `models.map.md` is the single place model IDs live per install —
including fallback chains (never fall back *up* a tier, with a fast→light carve-out
because light is terminal's baseline when `fast` is omitted), the fix-cycle rotation
table, and the cost-ceiling policy. The research behind the split — including the
Copilot cost-ceiling and Cursor silent-fallback caveats — is in
[multi-harness-upgrade.md](https://github.com/kdcllc/skills/blob/master/_memory/research/multi-harness-upgrade.md).
Re-run `/agent-kit` when providers rotate model names.

## Upgrading an installed project

1. **Re-pull the kit** with whichever CLI you installed with:
   `npx skills add kdcllc/skills --skill agent-kit` again, or `npx agent-skills-cli update`.
2. **Re-emit from the manifest** — answers are embedded in
   `orchestration-kit.manifest.json`:

   ```bash
   bash .claude/skills/agent-kit/bin/emit.sh --upgrade
   # add --answers orchestration-kit.answers.json only when the interview changed
   # (Cursor: .cursor/skills/agent-kit; Copilot: .github/skills/agent-kit)
   ```

   Exit code 4 lists user-modified kit files, pre-existing kit-path files with no
   previous-manifest entry (first installs included), or legacy migration target conflicts; confirm with `--force`. Use `--dry-run` to
   preview planned actions. Seed files like `_memory/loop/backlog.md` are never
   overwritten.

Manifest semantics, seed files, and stale-file pruning are documented in
[contributing.md](https://github.com/kdcllc/skills/blob/master/docs/agent-kit/guide/contributing.md).

### Upgrading from the private setup kit

Coming from the private `setup` skill (the kit's name before 1.0.0)? Read the 1.0.0
**Upgrade notes** in [CHANGELOG.md](CHANGELOG.md), then:

- Re-add from [kdcllc/skills](https://github.com/kdcllc/skills) with
  `npx skills add kdcllc/skills --skill agent-kit` and delete old `setup` compiler
  copies (`.claude/skills/setup/`, `.cursor/skills/setup/`, `.github/skills/setup/`,
  or `.agents/skills/setup/`, whichever exist).
- Re-emit with `--upgrade` as above. Installs from the private `setup` kit before 0.27.0
  have no embedded `answers` in the manifest — run `/agent-kit` Steps 1–4 once to
  create an answers file, then `--answers … --upgrade`.
- Legacy layout: when `_goals/` or `_research/` remain, `--upgrade` moves them into
  `_memory/` before writing kit files (`git mv` when tracked); `--dry-run` lists
  `migrate` lines. Goal/research scratch is untracked afterward — see
  `_memory/README.md` § Upgrade migration and run `_kit/memory.sh backfill --plan`.
  Commit the `_memory/loop/` move before relying on `LOOP_WORKTREE=1`; coordinate with
  teammates before committing goal/research untracking.

## Editing the templates

Templates use `{{TOKEN}}` placeholders, `<!-- BOOTSTRAP[id]: … -->` comments (replaced
from `answers.bootstrap[id]`), and `<!-- IF flag -->` … `<!-- ENDIF flag -->` spans.
The placeholder reference lives in `SKILL.md`. All canonical content lives under
`templates/`; per-harness translation is implemented in `bin/emit.*`; harness caveats
live in `emitters/` and verified facts in `reference/harness-matrix.md`. Kit changes are
made in the [kdcllc/skills](https://github.com/kdcllc/skills) repository — see its
CONTRIBUTING.md for the dogfood loop and release steps.
