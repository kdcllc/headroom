#!/usr/bin/env bash
# log-spawn — append-only orchestration-log writer for the AI Orchestration Kit.
# Emitted single-copy to `_kit/log-spawn.sh` (Windows outside Git Bash: `_kit\log-spawn.cmd`
# — Git for Windows required). The orchestrator runs it INLINE after writing a context
# package / report file; it prints exactly one line on success.
#
# CLI CONTRACT (frozen — the feature skill and ORCHESTRATION.md describe this):
#
#   log-spawn.sh spawn   --goal <name> --agent <agent> --phase <text>
#                        --model-requested <id> --context <path>
#                        [--writes <text>] [--why <text>] [--expect <text>]
#     Appends (preceded by one blank line):
#       ### <ts> — SPAWN <agent> (<phase>) [#NN]
#       - agent: <agent> · model requested: <id>
#       - why: <why | —>
#       - writes claim: <writes | none>
#       - expected output: <expect | —>
#       - context: <path as given> · context_chars: <N>
#     NN = two digits parsed from the context file basename `NN-context.md`;
#     N  = byte length of the context file.
#
#   log-spawn.sh outcome --goal <name> --spawn <NN> --report <path> --verdict <text>
#                        --model-reported <text> [--note <text>] [--work-chars <C>]
#     Appends:
#       - OUTCOME [#NN]: <verdict> · model reported: <text> · model_check: <match|MISMATCH|unverified> · report: <path> · report_chars: <R> · io_est_tokens: <T> · work_read_chars: <C|n/a> · work_est_tokens: <W|n/a> · running io: <X> · running work: <Y>
#         <note>                (only with --note; indented two spaces)
#     model_check compares model families (case-insensitive, first match wins) for the
#     SPAWN block's `model requested:` id and --model-reported; on MISMATCH one stderr
#     line `log-spawn: MODEL-FAMILY-MISMATCH requested=<id> reported=<text>` (exit 0).
#     R = byte length of the report file; T = floor((context_chars of SPAWN #NN + R) / 4);
#     C/W parsed from report line `files_read: <N> (~<C> chars)` (digit-only C) or
#     overridden by --work-chars (digits only, else exit 2); W = floor(C/4) or n/a;
#     X = last `running io: <n>` (fallback: last `running total: <n>` for pre-v0.26 logs;
#     0 if none) + T; Y = last `running work: <n>` (0 if none) + W (W treated as 0 when n/a).
#
#   log-spawn.sh note    --goal <name> --text <text>
#     Appends a blank line + `### <ts> — <text>`.
#
#   Common: [--root <path>] (repo root; default $PWD; an explicit empty --root exits 2). Log path:
#   <root>/_memory/work/goals/<goal>/orchestration-log.md — created when missing with the header
#   `# Orchestration Log — <goal>` / blank / `Append-only spawn ledger. Running io_est_tokens
#   (orchestrator I/O proxy, chars/4) and work_est_tokens (subagent self-reported footprint /4):
#   see latest entry.` / blank / `---`.
#
#   Exit codes: 0 ok · 2 usage (unknown subcommand/flag, missing required flag, empty
#   --root, context basename not `NN-context.md`, --help/no args) · 3 ledger integrity (spawn with an NN
#   already present; outcome whose SPAWN #NN is missing or already has an OUTCOME) ·
#   4 missing goal directory or context/report file.
#   Check order is fixed: flags/basename (2) → paths (4) → integrity (3).
#   Errors: one line on stderr prefixed `log-spawn:` (plus optional MODEL-FAMILY-MISMATCH
#   warning on outcome MISMATCH). Success: exactly one stdout line (the appended heading
#   or outcome line).
#
#   Portability freeze (both twins): timestamp = local time, minutes precision, colon in
#   the offset (`2026-09-03T16:59-04:00`); byte counts are FILE BYTES; io_est_tokens is
#   floor((c + r) / 4); every append is UTF-8 without BOM with LF line endings; running
#   totals are the LAST `running io: <n>` / `running work: <n>` matches (io falls back to
#   `running total: <n>` when no `running io` exists).
#
# Zero runtime deps beyond bash + coreutils (date, wc, grep, sed, tail). Append-only:
# this script never rewrites an existing line. No setup placeholders — harness-agnostic.
set -u

usage() {
  cat <<'EOF'
usage: log-spawn.sh <spawn|outcome|note> [--root <path>] <flags>
  (--root must be non-empty when given; default when omitted is $PWD)
  spawn   --goal G --agent A --phase P --model-requested M --context _memory/work/goals/G/spawns/NN-context.md [--writes T] [--why T] [--expect T]
  outcome --goal G --spawn NN --report _memory/work/goals/G/spawns/NN-report.md --verdict V --model-reported M [--note T] [--work-chars C]
          (OUTCOME adds model_check: match|MISMATCH|unverified; MISMATCH → stderr warning, exit 0)
  note    --goal G --text T
exit: 0 ok · 2 usage · 3 ledger integrity · 4 missing goal dir / file
EOF
}

die() { # <code> <message>
  printf 'log-spawn: %s\n' "$2" >&2
  exit "$1"
}

timestamp() {
  local ts
  ts="$(date +%Y-%m-%dT%H:%M%z)"     # 2026-09-03T16:59-0400 (portable; no GNU %:z)
  printf '%s:%s' "${ts:0:19}" "${ts:19:2}"
}

file_bytes() { # <path> → bytes (trimmed)
  local n
  n="$(wc -c < "$1")"
  printf '%s' "${n//[[:space:]]/}"
}

append() { # <log> <text-with-trailing-newline>
  printf '%s' "$2" >> "$1"
}

ensure_log() { # <log> <goal>
  if [ ! -f "$1" ]; then
    printf '# Orchestration Log — %s\n\nAppend-only spawn ledger. Running io_est_tokens (orchestrator I/O proxy, chars/4) and work_est_tokens (subagent self-reported footprint /4): see latest entry.\n\n---\n' "$2" > "$1"
  fi
}

prev_running_io() { # <log> → last running io (fallback running total, else 0)
  local log="$1" v
  v="$(grep -o 'running io: [0-9]*' "$log" | tail -n1 | sed 's/running io: //')"
  if [ -n "$v" ]; then
    printf '%s' "$v"
    return
  fi
  v="$(grep -o 'running total: [0-9]*' "$log" | tail -n1 | sed 's/running total: //')"
  printf '%s' "${v:-0}"
}

prev_running_work() { # <log> → last running work (else 0)
  local log="$1" v
  v="$(grep -o 'running work: [0-9]*' "$log" | tail -n1 | sed 's/running work: //')"
  printf '%s' "${v:-0}"
}

parse_work_chars() { # <report-path> → 0 ok (sets work_c) · 1 n/a
  local path="$1" line
  work_c=""
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ ^files_read:\ [0-9]+\ \(~([0-9]+)\ chars\)$ ]]; then
      work_c="${BASH_REMATCH[1]}"
      return 0
    fi
  done < "$path"
  return 1
}

model_family() { # <model-id> → family on stdout; 1 if none
  local lc
  [ -n "$1" ] || return 1
  lc="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  if printf '%s' "$lc" | grep -qE 'claude|opus|sonnet|haiku|fable'; then
    printf 'anthropic'; return 0
  fi
  if printf '%s' "$lc" | grep -qE 'gpt|codex|(^|[^a-z0-9])o[0-9]'; then
    printf 'openai'; return 0
  fi
  if printf '%s' "$lc" | grep -qE 'grok'; then
    printf 'xai'; return 0
  fi
  if printf '%s' "$lc" | grep -qE 'gemini'; then
    printf 'google'; return 0
  fi
  if printf '%s' "$lc" | grep -qE 'composer'; then
    printf 'cursor'; return 0
  fi
  if printf '%s' "$lc" | grep -qE 'muse'; then
    printf 'meta'; return 0
  fi
  return 1
}

derive_model_check() { # <requested-id> <reported-text>
  local fam_req fam_rep
  fam_req="$(model_family "$1")" || { printf 'unverified'; return; }
  fam_rep="$(model_family "$2")" || { printf 'unverified'; return; }
  if [ "$fam_req" = "$fam_rep" ]; then
    printf 'match'
  else
    printf 'MISMATCH'
  fi
}

spawn_model_requested() { # <log> <nn> → id on stdout
  local log="$1" nn="$2" block line
  block="$(grep -A5 "^### .* — SPAWN .* \[#$nn\]\$" "$log")"
  line="$(printf '%s\n' "$block" | grep -m1 'model requested:')" || return 1
  printf '%s' "$line" | sed -n 's/.*model requested: \([^·]*\).*/\1/p' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

[ $# -eq 0 ] && { usage; exit 2; }
sub="$1"; shift
case "$sub" in
  -h|--help|help) usage; exit 2 ;;
  spawn|outcome|note) ;;
  *) usage; die 2 "unknown subcommand '$sub'" ;;
esac

root="$PWD"
root_explicit=0
goal="" agent="" phase="" model_requested="" context="" writes="" why="" expect=""
spawn_nn="" report="" verdict="" model_reported="" note="" text="" work_chars=""

need_val() { [ $# -ge 2 ] || die 2 "flag '$1' needs a value"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --root)            need_val "$@"; root_explicit=1; root="$2"; shift 2 ;;
    --goal)            need_val "$@"; goal="$2"; shift 2 ;;
    --agent)           need_val "$@"; agent="$2"; shift 2 ;;
    --phase)           need_val "$@"; phase="$2"; shift 2 ;;
    --model-requested) need_val "$@"; model_requested="$2"; shift 2 ;;
    --context)         need_val "$@"; context="$2"; shift 2 ;;
    --writes)          need_val "$@"; writes="$2"; shift 2 ;;
    --why)             need_val "$@"; why="$2"; shift 2 ;;
    --expect)          need_val "$@"; expect="$2"; shift 2 ;;
    --spawn)           need_val "$@"; spawn_nn="$2"; shift 2 ;;
    --report)          need_val "$@"; report="$2"; shift 2 ;;
    --verdict)         need_val "$@"; verdict="$2"; shift 2 ;;
    --model-reported)  need_val "$@"; model_reported="$2"; shift 2 ;;
    --note)            need_val "$@"; note="$2"; shift 2 ;;
    --text)            need_val "$@"; text="$2"; shift 2 ;;
    --work-chars)      need_val "$@"; work_chars="$2"; shift 2 ;;
    *) die 2 "unknown flag '$1' for '$sub'" ;;
  esac
done

if [ "$root_explicit" -eq 1 ] && [ -z "$root" ]; then
  usage >&2
  die 2 "--root needs a directory"
fi

require() { # <flag-name> <value>
  [ -n "$2" ] || die 2 "'$sub' requires $1"
}
require --goal "$goal"

goal_dir="$root/_memory/work/goals/$goal"
log="$goal_dir/orchestration-log.md"

case "$sub" in
  spawn)
    require --agent "$agent"; require --phase "$phase"
    require --model-requested "$model_requested"; require --context "$context"
    base="${context##*/}"
    case "$base" in
      [0-9][0-9]-context.md) nn="${base:0:2}" ;;
      *) die 2 "context basename must match NN-context.md (got '$base')" ;;
    esac
    ctx_path="$context"; [ "${ctx_path#/}" = "$ctx_path" ] && ctx_path="$root/$ctx_path"
    [ -d "$goal_dir" ] || die 4 "goal directory not found: $goal_dir"
    [ -f "$ctx_path" ] || die 4 "context file not found: $context"
    if [ -f "$log" ] && grep -q "^### .* — SPAWN .* \[#$nn\]\$" "$log"; then
      die 3 "SPAWN [#$nn] already present in $log"
    fi
    chars="$(file_bytes "$ctx_path")"
    ensure_log "$log" "$goal"
    heading="### $(timestamp) — SPAWN $agent ($phase) [#$nn]"
    append "$log" "
$heading
- agent: $agent · model requested: $model_requested
- why: ${why:-—}
- writes claim: ${writes:-none}
- expected output: ${expect:-—}
- context: $context · context_chars: $chars
"
    printf '%s\n' "$heading"
    ;;
  outcome)
    require --spawn "$spawn_nn"; require --report "$report"
    require --verdict "$verdict"; require --model-reported "$model_reported"
    case "$spawn_nn" in
      [0-9][0-9]) ;;
      *) die 2 "--spawn must be two digits (got '$spawn_nn')" ;;
    esac
    if [ -n "$work_chars" ]; then
      case "$work_chars" in
        *[!0-9]*) die 2 "invalid --work-chars value '$work_chars'" ;;
      esac
    fi
    nn="$spawn_nn"
    rep_path="$report"; [ "${rep_path#/}" = "$rep_path" ] && rep_path="$root/$rep_path"
    [ -d "$goal_dir" ] || die 4 "goal directory not found: $goal_dir"
    [ -f "$rep_path" ] || die 4 "report file not found: $report"
    [ -f "$log" ] || die 3 "no orchestration log at $log (no SPAWN [#$nn])"
    grep -q "^### .* — SPAWN .* \[#$nn\]\$" "$log" || die 3 "SPAWN [#$nn] not found in $log"
    if grep -q "^- OUTCOME \[#$nn\]:" "$log"; then
      die 3 "OUTCOME [#$nn] already present in $log"
    fi
    ctx_chars="$(grep -A5 "^### .* — SPAWN .* \[#$nn\]\$" "$log" | grep -m1 -o 'context_chars: [0-9]*' | sed 's/context_chars: //')"
    [ -n "$ctx_chars" ] || die 3 "SPAWN [#$nn] has no context_chars line"
    model_req="$(spawn_model_requested "$log" "$nn" || true)"
    if [ -n "$model_req" ]; then
      model_check="$(derive_model_check "$model_req" "$model_reported")"
    else
      model_check="unverified"
    fi
    rep_chars="$(file_bytes "$rep_path")"
    io_est=$(( (ctx_chars + rep_chars) / 4 ))
    prev_io="$(prev_running_io "$log")"
    prev_work="$(prev_running_work "$log")"
    running_io=$(( prev_io + io_est ))
    if [ -n "$work_chars" ]; then
      work_read=$((10#$work_chars))
      work_est=$(( work_read / 4 ))
      work_read_disp="$work_read"
      work_est_disp="$work_est"
      running_work=$(( prev_work + work_est ))
    elif parse_work_chars "$rep_path"; then
      work_read=$((10#$work_c))
      work_est=$(( work_read / 4 ))
      work_read_disp="$work_read"
      work_est_disp="$work_est"
      running_work=$(( prev_work + work_est ))
    else
      work_read_disp="n/a"
      work_est_disp="n/a"
      running_work="$prev_work"
    fi
    line="- OUTCOME [#$nn]: $verdict · model reported: $model_reported · model_check: $model_check · report: $report · report_chars: $rep_chars · io_est_tokens: $io_est · work_read_chars: $work_read_disp · work_est_tokens: $work_est_disp · running io: $running_io · running work: $running_work"
    if [ -n "$note" ]; then
      append "$log" "$line
  $note
"
    else
      append "$log" "$line
"
    fi
    if [ "$model_check" = MISMATCH ]; then
      printf 'log-spawn: MODEL-FAMILY-MISMATCH requested=%s reported=%s\n' "$model_req" "$model_reported" >&2
    fi
    printf '%s\n' "$line"
    ;;
  note)
    require --text "$text"
    [ -d "$goal_dir" ] || die 4 "goal directory not found: $goal_dir"
    ensure_log "$log" "$goal"
    heading="### $(timestamp) — $text"
    append "$log" "
$heading
"
    printf '%s\n' "$heading"
    ;;
esac
exit 0
