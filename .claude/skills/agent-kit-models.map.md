# Model Map (Claude Code, local CLI)

Model IDs are **configuration, not constants**. This file is the single place they are
defined; re-run `/agent-kit` (or edit here and re-emit) when providers rotate model names.

Verified 2026-10-23 against the live Claude Code model-configuration documentation at https://code.claude.com/docs/en/model-config and installed Claude Code 2.1.309. The documented Anthropic API aliases are opus → Opus 5.5 (minimum Claude Code v2.1.280), sonnet → Sonnet 5.5 (minimum v2.1.284), and haiku → Haiku 5.5 (minimum v2.1.293). These aliases are the configured pins; aliases resolve per provider and account availability.

## Tier assignments

| Tier | Roles | Rationale |
|------|-------|-----------|
| `frontier` | orchestrator (main session), `evaluator`, `qa-evaluator`, `diagnostician` | Delegation and evaluation have a capability floor — don't cheap out on the roles that decide and verify; continuation-ladder diagnosis needs frontier-tier reasoning |
| `light` | `implementer`, `test-writer`, `evidence-collector` | Checklist-driven execution retains most quality at a fraction of the cost when the plan and the verification are strong |
| `fast` | `terminal` | Single-command execution and result extraction need no deep reasoning — the cheapest, quickest tier fits |

## Resolved models

| Tier | Claude Code |
|------|-------------|
| `frontier` | opus |
| `light` | sonnet |
| `fast` | haiku |

An install that omits `fast` runs `terminal` on the light model (the `fast` row then
repeats the light ID).

Claude Code effort frontmatter: evaluators high, diagnostician xhigh, implementer/test-writer/evidence-collector medium, terminal low.

## Fallback chains

| Tier | Chain (first available wins) |
|------|------------------------------|
| `frontier` | `opus` → `claude-opus-5` → omit model pin |
| `light` | `sonnet` → `claude-sonnet-5` → omit model pin |
| `fast` | `haiku` → `sonnet` → omit model pin |

Rules (adapted from bradygaster/squad's model selector):

- **Never fall back UP a tier** — a light role must never silently land on a frontier
  model, and a frontier role never degrades below the standard rung of its chain.
  One carve-out: fast → light is allowed, because light is `terminal`'s baseline tier
  (installs without `fast` run it there).
- Fallbacks are silent to the user but **logged in the orchestration log**.
- Max 3 fallback attempts, then omit the model pin and take the harness default.
- Apply at most **one** complexity adjustment per spawn — no cascading bumps.
- **Cost ceiling policy**: an EXPLICIT human model choice above a plan/admin ceiling →
  warn loudly and honor it; an implicit (auto-selected) choice → downgrade to the
  ceiling; no compliant model at all → fail loud — never silently substitute.
- **Prompts are executable — narrowly**: only tasks that edit `templates/agents/*`
  or `templates/skills/*-criteria/*` (the files that shape every later spawn's
  behavior) use the frontier tier; skills, emitters, drivers, docs, and tests stay
  on the light tier.
- **Every spawn names its model.** The orchestrator passes the tier's resolved ID
  explicitly on every spawn and records `requested` vs the agent's self-reported
  model in the orchestration log; `inherit` is legitimate only for a tier the
  install deliberately left unpinned.

### Loop fallback chain

| Chain (first available wins) | Resolves |
|-------------------------------|----------|
| `sonnet` → `claude-sonnet-5` → omit model pin | `sonnet,claude-sonnet-5` |

## Fix-cycle rotation (after evaluator rejections)

A model blind to its own class of mistake rarely fixes it on retry. Rotate:

| Fix cycle | Implementer model |
|-----------|-------------------|
| 1 | `sonnet` (normal) |
| 2 | `opus` — same-family rotation (reduced diversity) |
| 3 | `opus` |

**Same-family rotation.** When no different-family model at comparable tier is reachable
on a harness, fix cycle 2 may pin a different same-family model (see the table above) and
label the row `same-family rotation (reduced diversity)`. A second harness such as Copilot
or Codex provides cross-family models when targeted. Repeated same-shaped failures across
fix cycle 2 and continuation-ladder rung 4 should escalate to a human sooner.

### After cycle 3 — continuation ladder pins

When fix cycles 1–3 exhaust, the continuation ladder (see ORCHESTRATION.md) applies:

| Ladder step | Model pin |
|-------------|-----------|
| Diagnosis-driven implementation attempt (rung 4) | `opus` |
| Evaluator arbitration mode (rung 5) | `opus` — same-family arbiter (reduced independence) |

**Same-family arbiter.** When no different-family frontier model is reachable on a
harness, `frontier_alt_family` may equal `frontier` with `arbiter_same_family: true`
in the answers file (emit otherwise warns); the rung-5 row is then labelled
"same-family arbiter (reduced independence)" and the arbiter's verdict header says
`same-family arbiter`. Reusing the fix-cycle-2 alternate (`alt_family`) for
arbitration stays forbidden — when `frontier_alt_family` equals `alt_family` (and
differs from `frontier`), emit warns even with the flag.

## Harness caveats that shape tiering

- Claude Code environment variables CLAUDE_CODE_SUBAGENT_MODEL and CLAUDE_CODE_EFFORT_LEVEL override frontmatter; organization availableModels restrictions can ignore pins.
- Claude Code is Anthropic-family only; the selected cycle-2 alternate and frontier arbiter are same-family (reduced diversity/independence).
- Model aliases resolve per provider; the documented minimum CLI versions are recorded above.
- Never use best or fable in the autonomous loop chain.
