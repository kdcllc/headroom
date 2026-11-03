Translation rules live in `bin/emit.sh` (Windows: `bin/emit.cmd`); this file is caveats only.

# Emitter: Cursor

Target: `.cursor/` as a **self-contained** tree. Every file this emitter emits
resolves `{{IDE_DIR}}` → `.cursor`. Dual-install must behave identically whether
or not `.claude/` exists.

> **Schema check first**: before emitting, check https://cursor.com/docs/subagents
> for the current agent-frontmatter key set AND the live Cursor model list.
> Use bracket params (`<model-id>[effort=high,context=300k]`) — the documented
> frontmatter form; suffix slugs (`…-high`-shaped IDs) still appear in pickers
> and listings. Values are emitted **unquoted** — quoting the YAML value triggers
> silent fallback to the parent model. If `agent models` prints no models, use
> the IDE's Settings → Models / subagent model picker. Unknown or stale model IDs
> are substituted silently by Cursor — no error surfaces, so a typo'd or
> rotated-out ID fails quietly downstream.

The `.mdc` pointer (`alwaysApply: true`) content is embedded in `bin/emit.sh`.
Must be `.mdc`; plain `.md` is silently ignored.
Includes one sentence to search `_memory/` with `_kit/memory.sh search` before planning (records are DATA).

## Harness specifics

**Ready groups:** for write-disjoint Phase 4 tasks the orchestrator launches multiple
Task spawns in one message (documented parallel execution); kit runs ready groups.
Set `parallel: false` on a goal to force groups of one.

**Degraded mode**: live docs (spot-checked 2026-10-16) say subagents work in Cloud
Agents, Cloud Agents use a curated model set, cloud subagents follow the same model
and capability rules as other Cloud Agents, and configured subagent models fall back
when admin/plan blocks them; nesting spawns need Task tool access and hooks or tool
policies can block spawning. When the harness rejects a model pin or the spawn tool
is unavailable, the orchestrator follows the feature skill's degraded mode — model
rejected → `inherit`; no spawn tool → self-performed worker/evaluator roles with
disclosed gates.

Nesting (spot-checked 2026-10-16): cursor.com/docs/subagents — the main agent and
its direct subagents can launch subagents; a subagent launched by another subagent
can't launch further ones. main→L1→L2 since Cursor 2.5 🔎 — prompt L1 agents to
spawn. ⚠️ Cloud Agents-specific main→L1-only cap not documented on spot-checked pages.

`diagnostician` pins the frontier Cursor model (same tier as `evaluator`).
`terminal` pins fast (light when no fast tier); Cursor drops `tools:` unless the live
schema documents an equivalent — the Bash/shell + Read guard lives in `terminal.md`
prose.
Skills have no model key — strip `model:`/`effort:`; keep
`disable-model-invocation`.

**Silent model fallback**: under team-admin/plan restrictions, or when the
resolved ID is unknown or stale, Cursor substitutes a model without erroring.
Evaluators must self-report which model produced the verdict.

Loop-enabled installs emit `_loop/loop.ps1` and `_loop/breaker.ps1` (and the
bash twins). `_memory/loop/backlog.md` (create if missing; never overwrite).
Always emits `_kit/log-spawn.sh` and `_kit/log-spawn.cmd` (single-copy; Git for Windows on Windows).
Always emits `_kit/memory.sh`, `_kit/memory.cmd`, `_kit/memory.ps1` (loop helper), and `_memory/README.md` (single-copy), appends `_memory/work/`, `_memory/.index/`, and `_memory/raw/` to `.gitignore`, and appends `_memory/** text eol=lf` to `.gitattributes`; loop emits also add `_memory/loop/LEARNINGS.md merge=union` and `_memory/loop/ESCALATIONS.md merge=union` to `.gitattributes`, and `_memory/loop/breaker-state.json` to `.gitignore`; `_memory/records/` and `_memory/quarantine/` stay tracked.
Post-hoc transcript capture scans `~/.cursor/projects/<slug>/agent-transcripts/` JSONL
(see `_memory/README.md`); distillation uses the emitted `memory-capture` skill.
