Translation rules live in `bin/emit.sh` (Windows: `bin/emit.cmd`); this file is caveats only.

# Emitter: GitHub Copilot (VS Code)

Target: `.github/`. Check the live VS Code custom-agents page
(https://code.visualstudio.com/docs/agent-customization/custom-agents)
before pinning tool names.

## Harness specifics

**Ready groups:** for write-disjoint Phase 4 tasks the orchestrator may try parallel
`runSubagent` spawns; concurrency is ⚠️ unverified — fall back to sequential on a
concurrency error. Set `parallel: false` on a goal to force groups of one.

**Cost ceiling**: a subagent cannot run a stronger model than the session; a
too-strong pin makes the subagent **not run at all**. Orchestrated sessions
run the frontier tier; evaluators never pin above it; workers pin down.
Copilot has no `effort` key.

Nesting stays off (kit default). `chat.subagents.allowInvocationsFromSubagents`
must not be enabled by `/agent-kit`. Do not write `.vscode/settings.json`.
`feature.agent.md` is the L1 orchestrator and spawns workers and evaluators
directly; that top-level spawn works with nesting off. Workers do not spawn
subagents of their own; when output needs isolating, spawn `terminal`.

Skills: copy `disable-model-invocation` as-is on
`.github/skills/*/SKILL.md`. Subagents are stateless — context packages must
be complete on first send.

The copilot-instructions pointer content is embedded in `bin/emit.sh`.
Appends a separate `## Memory` block (marker `<!-- orchestration-kit:memory-pointer -->`) after the orchestration pointer when absent.

Loop-enabled installs emit `_loop/loop.ps1` and `_loop/breaker.ps1` (and the
bash twins). `_memory/loop/backlog.md` (create if missing; never overwrite).
Always emits `_kit/log-spawn.sh` and `_kit/log-spawn.cmd` (single-copy; Git for Windows on Windows).
Always emits `_kit/memory.sh`, `_kit/memory.cmd`, `_kit/memory.ps1` (loop helper), and `_memory/README.md` (single-copy), appends `_memory/work/`, `_memory/.index/`, and `_memory/raw/` to `.gitignore`, and appends `_memory/** text eol=lf` to `.gitattributes`; loop emits also union-merge `_memory/loop/LEARNINGS.md` and `_memory/loop/ESCALATIONS.md` and gitignore `_memory/loop/breaker-state.json`; `_memory/records/` and `_memory/quarantine/` stay tracked.
No supported Copilot transcript export — session summaries use the `memory-capture`
skill's **orchestrator-written fallback** (see `feature/reference/memory-capture.md`).
