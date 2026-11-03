Translation rules live in `bin/emit.sh` (Windows: `bin/emit.cmd`); this file is caveats only.

# Emitter: Claude Code

Target: `.claude/` — canonical format. The `CLAUDE.md` pointer and
`.claude/settings.json` merge content is embedded in `bin/emit.sh`.
Appends a separate `## Memory` block (marker `<!-- orchestration-kit:memory-pointer -->`) after the orchestration pointer when absent.

## Harness specifics

**Ready groups:** for write-disjoint Phase 4 tasks the orchestrator launches parallel
Agent spawns (documented; default limit 20 concurrent — `Concurrent subagent limit
reached` means fall back to sequential); kit runs ready groups. Set `parallel: false`
on a goal to force groups of one.

Orchestrator spawn allowlists use this literal tools line:

tools: Agent(implementer, test-writer, evaluator, qa-evaluator, terminal, diagnostician, evidence-collector)

`terminal` is on the allowlist so callers can spawn it; `diagnostician` joins
for rung 4; `evidence-collector` gathers QA evidence before `qa-evaluator` when
the QA gate runs. P0 skills keep `disable-model-invocation: true` (this emitter never
strips frontmatter keys).

Model values: Claude aliases (`opus`, `sonnet`, `haiku`, `fable`) or full IDs
are both valid; `inherit` is the frontmatter default if a tier is deliberately
unpinned. `fable` is never valid in a loop chain — emit exits 3. Claude Code
runs **Anthropic models only** — a cross-family arbiter is unreachable
natively; use the same-family arbiter flag when the arbiter ID equals
frontier. Prefer full IDs; aliases resolve per provider (see the model-config
docs). Record the minimum Claude Code version for each pinned model (check
`claude --version` against the docs' per-model floor).

Pin nesting explicitly — the default flipped twice in July 2026. Merge
`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=3` into `.claude/settings.json` (merge,
don't overwrite).

Loop-enabled installs emit `_loop/loop.ps1` and `_loop/breaker.ps1` (and the
bash twins). `_memory/loop/backlog.md` (create if missing; never overwrite).
Always emits `_kit/log-spawn.sh` and `_kit/log-spawn.cmd` (single-copy; Git for Windows on Windows).
Always emits `_kit/memory.sh`, `_kit/memory.cmd`, `_kit/memory.ps1` (loop helper), and `_memory/README.md` (single-copy), appends `_memory/work/`, `_memory/.index/`, and `_memory/raw/` to `.gitignore`, and appends `_memory/** text eol=lf` to `.gitattributes`; loop emits also union-merge `_memory/loop/LEARNINGS.md` and `_memory/loop/ESCALATIONS.md` and gitignore `_memory/loop/breaker-state.json`; `_memory/records/` and `_memory/quarantine/` stay tracked.
Post-hoc transcript capture scans `~/.claude/projects/<slug>/*.jsonl` under `$HOME` (see
`_memory/README.md`); distillation uses the emitted `memory-capture` skill.
