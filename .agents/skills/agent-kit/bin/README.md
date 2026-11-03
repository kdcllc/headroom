# emit.sh

Deterministic emitter for the AI Orchestration Kit (`/agent-kit` Steps 4–6). Resolves
IF / BOOTSTRAP / tokens, translates per harness, writes seeds, pointers, and the
manifest, then verifies.

Runs on **Bash 3.2+** with POSIX `awk` (no `jq`). On Windows outside Git Bash, use
`emit.cmd` beside this script — same flags, output, and exit codes ([windows-launcher](../reference/windows-launcher.md)).

## Flags

`--answers F` `--upgrade` `--dry-run` `--force` `--check-answers` `--check`
(legacy `_goals/` / `_research/` → `_memory/` migration runs whenever those dirs exist — fresh install or upgrade)
`--root DIR` (default: cwd; an empty value exits **2**) `--kit DIR` (default: this script's `..`)

`--check` runs `<kit>/templates/tools/kit-guard.sh check --root <root>` (default cwd).
It needs no `--answers` (any `--answers` is ignored). Mutually exclusive with
`--upgrade`, `--dry-run`, `--force`, and `--check-answers`. Exit **0** when every
manifest-listed kit file matches its recorded hash · **2** usage / no manifest (a
missing `--root` is not created) · **4** when any kit-owned file is missing or its
bytes differ (stdout lists each path and ends with the restore hint from `kit-guard.sh check`).

## Exit codes

`0` ok · `2` usage / answers unreadable · `3` answers invalid or
unanswered `--check-answers` ids · `4` emit blocked: user-modified kit files (disk
bytes differ from the last manifest hash), pre-existing files at kit paths that no
previous emit recorded (stderr distinguishes the two; `--dry-run` prints `blocked
<path>` for both), or a legacy migration target that already exists (`--force`
overrides file blocks and skips conflicting moves with a warning) · `5` verify failed ·
`6` template syntax. Pre-existing `.codex/config.toml` appends (user bytes plus kit
agent tables) are exempt from the no-manifest-entry block. `--help` → stderr, exit 2.

## Answers

JSON `schema: 1` per `SKILL.md` Step 4. `--check-answers` prints
`<id>\t<template-path>` for missing class-a bootstrap keys. Optional
`flags.loop_worktree` (boolean): absent ⇒ false; a present non-boolean ⇒ exit **3**
(`flags.loop_worktree must be a boolean`). Optional `flags.opt_in` (boolean): absent
⇒ false; a present non-boolean ⇒ exit **3** (`flags.opt_in must be a boolean`); drives
IF flag `opt_in` and the four derived `OPT_IN_*` tokens. When Codex is targeted with
`opt_in` true, emit warns:
`warning: flags.opt_in is partial on codex: no kit skills tree to gate, and an existing .codex/config.toml agent table is never rewritten`.
Optional `flags.kit_guard` (boolean): absent ⇒ false; a present non-boolean ⇒ exit **3**
(`flags.kit_guard must be a boolean`); drives IF flag `kit_guard` and emits
`_kit/kit-guard.sh`, `_kit/kit-guard.cmd`, `.claude/settings.json` (Claude Code
`PreToolUse` hook) when absent, and `.cursor/hooks.json` (`preToolUse`) when absent.
When those config files already exist without the hook, emit leaves them untouched and
warns (merge the snippet from stderr):
`warning: .claude/settings.json exists without the kit-guard hook — left untouched; merge into it: {"hooks":{"PreToolUse":[{"matcher":"Edit|Write|MultiEdit|NotebookEdit","hooks":[{"type":"command","command":"bash \"$CLAUDE_PROJECT_DIR/_kit/kit-guard.sh\" hook claude"}]}]}}`
`warning: .cursor/hooks.json exists without the kit-guard hook — left untouched; add to its "hooks" object: "preToolUse":[{"command":"bash _kit/kit-guard.sh hook cursor","matcher":"Write|Delete"}]`
With `kit_guard` off but a stale hook reference left in user config, emit warns:
`warning: .claude/settings.json still references _kit/kit-guard.sh but flags.kit_guard is off — remove that hook entry`
`warning: .cursor/hooks.json still references _kit/kit-guard.sh but flags.kit_guard is off — remove that hook entry`
Copilot and Codex partial warnings when `kit_guard` is on:
`warning: flags.kit_guard is partial on copilot: no edit-blocking hook; run emit.sh --check in CI (_kit/ is gitignored)`
`warning: flags.kit_guard is partial on codex: no edit-blocking hook; run emit.sh --check in CI (_kit/ is gitignored)`
Optional `flags.hook_telemetry` (boolean): absent ⇒ false; a present non-boolean ⇒ exit **3**
(`flags.hook_telemetry must be a boolean`); persists as `options.hook_telemetry` when present
and emits `_kit/hook-log.sh` and `_kit/hook-log.cmd`. Claude Code gets `Stop`, `SubagentStop` and
`StopFailure` hooks (in that order) in `.claude/settings.json`, and Cursor gets `stop` and
`subagentStop` hooks (each with `"loop_limit": 1`) in `.cursor/hooks.json`, written only when
those files are absent. With `kit_guard` on too, the same created file holds both, with
`PreToolUse` / `preToolUse` first. Both commands are guarded, so a fresh clone without `_kit/`
shows no hook error on every stop: the Claude Code command is
`test -f "$CLAUDE_PROJECT_DIR/_kit/hook-log.sh" && bash … hook claude || true`, and the Cursor
command is exactly `test -f _kit/hook-log.sh && bash _kit/hook-log.sh hook cursor || echo '{}'`
(it still prints the `{}` the Cursor hook protocol expects when the script is missing; Cursor's
shell on Windows is unverified). When those config files already exist without the hooks, emit
leaves them untouched and warns (merge the snippet from stderr):
`warning: .claude/settings.json exists without the hook-telemetry hooks — left untouched; merge into it: {"hooks":{"Stop":[{"hooks":[{"type":"command","command":"test -f \"$CLAUDE_PROJECT_DIR/_kit/hook-log.sh\" && bash \"$CLAUDE_PROJECT_DIR/_kit/hook-log.sh\" hook claude || true"}]}],"SubagentStop":[{"hooks":[{"type":"command","command":"test -f \"$CLAUDE_PROJECT_DIR/_kit/hook-log.sh\" && bash \"$CLAUDE_PROJECT_DIR/_kit/hook-log.sh\" hook claude || true"}]}],"StopFailure":[{"hooks":[{"type":"command","command":"test -f \"$CLAUDE_PROJECT_DIR/_kit/hook-log.sh\" && bash \"$CLAUDE_PROJECT_DIR/_kit/hook-log.sh\" hook claude || true"}]}]}}`
`warning: .cursor/hooks.json exists without the hook-telemetry hooks — left untouched; add to its "hooks" object: "stop":[{"command":"test -f _kit/hook-log.sh && bash _kit/hook-log.sh hook cursor || echo '{}'","loop_limit":1}],"subagentStop":[{"command":"test -f _kit/hook-log.sh && bash _kit/hook-log.sh hook cursor || echo '{}'","loop_limit":1}]`
When `.claude/settings.json` already has the telemetry hooks (it references `_kit/hook-log.sh`)
but no `StopFailure` hook, as an install from before that hook existed does, emit leaves it
untouched and warns once with the entry to add:
`warning: .claude/settings.json has the hook-telemetry hooks but no StopFailure hook — left untouched; add to its "hooks" object: "StopFailure":[{"hooks":[{"type":"command","command":"test -f \"$CLAUDE_PROJECT_DIR/_kit/hook-log.sh\" && bash \"$CLAUDE_PROJECT_DIR/_kit/hook-log.sh\" hook claude || true"}]}]`
With `hook_telemetry` off but a stale hook reference left in user config, emit warns:
`warning: .claude/settings.json still references _kit/hook-log.sh but flags.hook_telemetry is off — remove those hook entries`
`warning: .cursor/hooks.json still references _kit/hook-log.sh but flags.hook_telemetry is off — remove those hook entries`
Copilot and Codex partial warnings when `hook_telemetry` is on:
`warning: flags.hook_telemetry is partial on copilot: no telemetry hook`
`warning: flags.hook_telemetry is partial on codex: no telemetry hook`
These warnings go through the same sorted flush as the kit-guard ones, and the spawn-depth
message for an existing `.claude/settings.json` still prints at most once per run.

Emit warnings (stderr, counted in `warnings W`, exit unchanged) include same-family / reused
arbiter model lines from the model map, and
`warning: models.<h>.alt_family equals light; fix cycle 2 would not rotate models`
when `alt_family` equals that harness's `light` tier. Every counted warning prints one stderr
line. Informational `emit:` lines, such as the legacy-migration notes (`emit: moved legacy …`,
`emit: some legacy entries were left in place …`), are not warnings and are not counted. Two
upgrade cases print a line of their own:
`warning: kept <path>: kit-owned file from an earlier emit, modified locally, no longer emitted — delete it or keep it as your own`
when a retired kit-owned file was modified locally and emit keeps it, and
`warning: <path> is recorded in the previous manifest but missing — nothing to prune`
when a non-kit file the previous manifest records is gone. Unanswered bootstrap ids are not
counted as warnings: `--check-answers` lists them (exit **3**).

## Manifest

Top-level key order: `kit`, `kitVersion`, `installedAt`, `harnesses`, `primary`,
`options`, `seedFiles`, `files`, `answers`. `options` is flat: `forge` (string),
optional `forgeHost`, booleans `greenfield`, `lint`, `typecheck`,
`models_pinned`, `research`, `loop`, and optional `loop_worktree`, `opt_in`,
`kit_guard`, and `hook_telemetry` (each copied from answers only when the matching
`flags.*` key is present). `files` maps emit-set paths → sha256
(compiler copies and seeds excluded; foreign entries carried). `seedFiles`
lists seeds written only if absent. Nested object keys are ordinal-sorted.
Rewriting the manifest never counts toward `written`.

## Determinism

Same inputs ⇒ byte-identical tree and manifest. `EMIT_DATE=YYYY-MM-DD` pins
`installedAt` on a fresh install. Directory walks use `LC_ALL=C`. Manifest
top-level key order is pinned (see Manifest); nested objects are ordinal-sorted.

## emit.cmd

Windows launcher copied from `templates/tools/bash-launcher.cmd`. Invokes this
script through Git for Windows Bash: `bin\emit.cmd --answers F --root DIR` (use
forward slashes in path arguments). The emitter also writes the same launcher
bytes to `_kit/memory.cmd`, `_kit/log-spawn.cmd`, `_kit/trace-lint.cmd`, `_kit/kit-guard.cmd` (when
`flags.kit_guard` is true), `_kit/hook-log.cmd` (when `flags.hook_telemetry` is true), and — for
loop-enabled installs — `_loop/loop.cmd`.

## `_kit/kit-guard.sh`

Emitted single-copy to `_kit/kit-guard.sh` (Windows: `_kit/kit-guard.cmd`) when
`flags.kit_guard` is true.

- **`check [--root DIR]`** — compare every kit-owned manifest `files` path to its
  sha256 (user-owned exclusions: `.claude/settings.json`, `.codex/config.toml`,
  `.cursor/hooks.json`). Exit **0** clean · **2** usage / no manifest / no hasher ·
  **4** missing or modified (prints `kit-guard: restore tracked files from git; delete a modified _kit/ file and re-run emit.sh --upgrade; never edit kit-owned files`).
  `_kit/` is gitignored: on a fresh clone or CI checkout the guard script and hooks are
  inactive until emit runs, and `check` skips `_kit/*` manifest entries (printing a note).
- **`hook <claude|cursor> [--root DIR]`** — read hook JSON from stdin; deny agent
  edits to kit-owned paths. Claude Code `PreToolUse` uses exit **2** with a stderr
  message; Cursor `preToolUse` returns JSON `permission: deny` on exit **2** (empty or
  non-JSON input fails open: prints `{"permission":"allow"}`, exit **0**). Matcher: Claude
  `Edit|Write|MultiEdit|NotebookEdit`;
  Cursor `Write|Delete`. Path fields checked include `file_path`, `notebook_path`,
  `path`, and `target_file`. Set `AGENT_KIT_GUARD=0` to fail open in hook mode.
  `hook claude` detects a Cursor caller (`CURSOR_PROJECT_DIR`, or JSON containing
  `cursor_version` / Cursor `preToolUse` shape) and answers with Cursor-format JSON.

Hooks cover agent edit tools only — shell and human edits are caught by `check`. The
guard does not protect its own configuration (manifest, hook config files); CI
`check` is the backstop. On Windows, a hook whose `bash` cannot start — or resolves
to WSL's `System32\bash.exe`, whose Windows-style paths never match the root — fails
open.

**CI recipe:** install the kit (e.g.
`npx skills add kdcllc/skills#agent-kit/v2.3.0 --skill agent-kit`) and run
`bash <kit>/bin/emit.sh --check --root .`.

## `_kit/trace-lint.sh`

Emitted single-copy to `_kit/trace-lint.sh` on every install (Windows: `_kit/trace-lint.cmd`,
a byte copy of the one launcher template). Canonical source:
`templates/tools/trace-lint.sh`. Pre-flight check 2 runs it on a goal's `goal.md`; it reads
that one file and writes nothing. Bash 3.2 and `sed` only.

- **`trace-lint.sh <goal.md>`** — checks `## Searches` and `## Consumers` against the goal
  template's format: every search item starts at column 0 and is
  ``- **S<n>** `<command>` — <N> hit|hits`` followed by a `text` block of
  `<path>:<line>:<text>` hit lines (N of them), every hit path outside `_memory/` is listed as a
  Consumer, and each Consumer row's class (`changes`, `unaffected`, `owner-excluded`) carries
  evidence of the matching shape (`task NN` or `Phase 6` under `align_docs: true`; `test:` /
  `diff:` / `search: S<n>` with 0 hits; `Q&A row <n>` naming a Discovery Summary row). Search
  ids are numbers: `S01` and `S1` are the same id, so a repeat in either spelling is a finding.
  Fenced blocks are skipped by the heading scan whether they use backticks or `~~~`; a fence
  closes only on the same character with at least as many marks.
- **The `none` body** — a goal that changes no shared surface writes `none — <reason>` as the
  first body line of `## Consumers`. That line must be the only non-blank line of the section,
  and `## Searches` must be absent; any other text under it is a finding.
- **`--help`** — usage on stdout, exit **0**. It is recognised only as the sole argument; `--help`
  next to any other argument is a usage error (exit **2**).
- **Exit codes** — **0** valid, printing `trace-lint: ok (<S> searches, <C> consumers)` or
  `trace-lint: ok (none — <reason>)` · **2** usage (wrong argument count, unknown flag, `--help`
  among other arguments) ·
  **3** findings, one `trace-lint: <file>:<line>: <message>` stdout line each, then a last
  line `trace-lint: <N> finding(s)` · **4** the file is missing or unreadable.
- **Emitted paths** — `_kit/trace-lint.sh` (executable) and `_kit/trace-lint.cmd`, on every
  install regardless of flags.

## `_kit/hook-log.sh`

Emitted single-copy to `_kit/hook-log.sh` (Windows: `_kit/hook-log.cmd`, a byte copy of the one
launcher template) when `flags.hook_telemetry` is true. Canonical source:
`templates/tools/hook-log.sh`. Telemetry only: it records how agent loops and subagents stop and
never steers them. Bash 3.2, `awk` and `LC_ALL=C`; no runtime JSON tool.

- **`hook <claude|cursor> [--root DIR]`** — read one stop-hook payload from stdin (Claude Code
  `Stop` / `SubagentStop` / `StopFailure`, Cursor `stop` / `subagentStop`) and append one metadata
  line to the log. Always exits **0** and fails open: `hook cursor` prints exactly `{}` on every
  path, `hook claude` prints nothing, and neither ever returns a follow-up message, block
  decision, continue flag or permission verdict, so the hook cannot start or extend an agent
  loop. Skipped without writing: `AGENT_KIT_HOOK_LOG=0`; empty or non-JSON-looking stdin;
  `hook claude` with a Cursor caller (`CURSOR_PROJECT_DIR` set, or a payload containing
  `cursor_version`), so a dual Claude Code + Cursor install logs through the Cursor hook only; an
  event name outside the five above; a payload whose key is still in `events.jsonl` or
  `events.1.jsonl`; any write failure. The Cursor hook command emit writes is guarded
  (`test -f _kit/hook-log.sh && … || echo '{}'`), so on a fresh clone without `_kit/` it still
  prints `{}` and writes nothing.
- **`summary [--root DIR]`** — read-only. Reads `events.1.jsonl` then `events.jsonl` (either may be
  missing) and prints the event count with the log path, then counts by event, by
  `harness/agent_type`, by status and by model (`  <count> <value>`, sorted by value, null shown
  as `-`), then an `errors and aborts` section listing
  `ts harness event agent_type status error` for every line whose status is `error` or
  `aborted` (or `  none`; `error` is `-` when it is null or the line predates the field). When no
  line has harness `claude`, a last `hint:` line says to check that the Claude Code project
  settings file has the hook-log Stop hooks.
- **`--help`** — usage on stdout, exit **0**.
- **Exit codes** — **0** ok (hook mode always, once its arguments parse) · **2** usage error in any
  mode, or an unreadable root in `summary` (`hook-log: cannot read root: <dir>`).
- **Root** — `--root DIR` when given, else the parent of the script's directory (`_kit/..`).
- **Log path** — `<root>/_memory/work/hooks/events.jsonl`, under the gitignored `_memory/work/`.
  Once the file reaches the size cap it is moved once to `events.1.jsonl` under a `mkdir` lock
  (`hooks/.rotate.lock`, treated as stale after 10 minutes), replacing an older
  `events.1.jsonl`. The tool writes nowhere else.
- **Line fields, in order** — `ts` (UTC), `harness` (`claude` | `cursor`), `event`, `session`,
  `generation`, `agent_id`, `agent_type`, `status`, `error`, `duration_ms`, `message_count`,
  `tool_call_count`, `loop_count`, `model`, `modified_files` (the element count of the Cursor
  array), `key` (first 16 hex of the SHA-256 of the raw payload, the idempotency key;
  `c<cksum CRC>` when neither `sha256sum` nor `shasum -a 256` exists). A field the payload lacks, or
  whose value has the wrong type, is `null`; the count and model fields come from Cursor payloads
  only. A Claude Code `StopFailure` line carries `status` `"error"` and `error` (the documented
  error type, for example `rate_limit`, taken only when it is lowercase letters and underscores);
  `error` is `null` on every other line. Metadata only: the task prompt, `description`, summary,
  `last_assistant_message`, `error_details`, transcript and workspace paths, `cwd`,
  `permission_mode`, `background_tasks`, `session_crons` and user email are never read into the log.
- **Environment** — `AGENT_KIT_HOOK_LOG=0` turns logging off (anything else leaves it on);
  `AGENT_KIT_HOOK_LOG_MAX_BYTES` sets the rotation cap in bytes (default `5242880`; a non-numeric
  value uses the default).
- **Hook configs** — emit writes the hooks that call it only into a `.claude/settings.json` /
  `.cursor/hooks.json` it creates (see `flags.hook_telemetry` under Answers).
