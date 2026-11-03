#!/usr/bin/env pwsh
#Requires -Version 7.0
# Model circuit breaker for the {{PROJECT_NAME}} autonomous loop — CLOSED/OPEN/
# HALF-OPEN state machine that degrades to cheaper models on rate limits and
# self-heals. Dot-sourced by the loop driver (`loop.ps1`); never executed directly.
#
# Twin: breaker.sh (bash) — behaviorally identical —
# same states, thresholds, transitions, and schema; any divergence is a bug.
# Function-name mapping (PowerShell -> bash):
#   Breaker-Load          -> breaker_load
#   Breaker-ShouldSkip     -> breaker_should_skip
#   Breaker-Record         -> breaker_record
#   Breaker-CurrentModel   -> breaker_current_model
#
# Cooldown threshold: 600s (OPEN -> HALF-OPEN eligible after 600s elapsed).
# Recovery threshold: HALF-OPEN closes at exactly 2 consecutive successes.
#
# State schema (flat JSON, one key per line — never nested, never minified/reflowed;
# both twins hand-write this exact layout so the file stays a byte-for-byte parity
# contract, not merely a JSON-equivalence one):
#   {
#   "state": "CLOSED"|"OPEN"|"HALF-OPEN",
#   "chain": "<comma-separated model chain, first = preferred>",
#   "fallbackIndex": <int, 0-based index of currentModel within chain — at chain
#     end the index stays put (pointing at the last entry) while currentModel
#     empties (omit-the-pin), so the two fields diverge by design>,
#   "currentModel": "<model id, or \"\" = omit the model flag/pin>",
#   "cooldownSeconds": 600,
#   "openedAt": <epoch seconds when OPEN was (re)entered, or 0>,
#   "halfOpenSuccesses": <int, consecutive successes while HALF-OPEN>,
#   "totalFallbacks": <int, lifetime>,
#   "totalRecoveries": <int, lifetime>
#   }
# NOTE: there is no `consecutiveFailures` key — it was a dead key in the original
# design note and is intentionally dropped from this schema.
#
# `chain` is normally seeded by the driver from the chain configured at install
# time (the LOOP_MODEL_CHAIN placeholder; see models.map.md's "Loop fallback
# chain" row) — this file never reads that token itself; the chain always
# arrives as a plain argument.
#
# Zero runtime deps: state is written by hand-built strings — NEVER ConvertTo-Json
# (which would reorder/re-escape/nest and break the byte-for-byte parity with the
# bash twin) — and parsed back with plain string ops, never Invoke-Expression, so
# the state file is read strictly as inert data: a corrupted or adversarially-edited
# file can only fail validation, never execute anything. Persistence adds
# [System.IO.File]::Move (atomic rename on write) and Start-Sleep (torn-read retry
# backoff); Breaker-Load's optional -Now falls back to a wall-clock read only as a
# default-parameter fallback at the API boundary.
#
# Testability: transition logic (Breaker-ShouldSkip, Breaker-Record) takes
# timestamps as parameters — no wall-clock reads inside any transition logic.
# Breaker-Load's fail-safe seed is the one exception at the API boundary: its
# optional `-Now` parameter (0 sentinel) defaults to a wall-clock read only when
# the caller does not inject one, so every existing call site stays valid and the
# harness can still inject a timestamp for determinism. Wall-clock anomaly guard:
# the remaining-cooldown value is CLAMPED to [0, cooldownSeconds] so a system
# clock that jumps backward or forward can never produce a negative or absurdly
# long skip.
#
# Dot-sourcing this file has zero side effects: it only defines functions.

# --- internal helpers (private-by-convention; not part of the pinned API) --------

# Read the raw value for a flat-JSON key from a state file, or $null if absent.
function Get-BreakerField {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Key
    )
    $needle = '"' + $Key + '":'
    $line = (Get-Content -LiteralPath $Path) | Where-Object { $_.Contains($needle) } | Select-Object -First 1
    if ($null -eq $line) { return $null }
    $value = $line.Substring($line.IndexOf(':') + 1).Trim()
    if ($value.EndsWith(',')) { $value = $value.Substring(0, $value.Length - 1) }
    if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    return $value
}

# Return $true iff every required key is present and every typed field parses
# (state is one of the three enum values; numeric fields are numeric). This is
# everything Test-BreakerStateValid checked before the terminator condition below
# was added; split out so Breaker-Load can tell a torn read (fields fine,
# terminator missing) apart from a genuinely invalid one (some field itself
# doesn't parse) — the two get different retry behavior.
function Test-BreakerFieldsValid {
    param([Parameter(Mandatory)] [string]$Path)
    $requiredKeys = @('state', 'chain', 'fallbackIndex', 'currentModel', 'cooldownSeconds',
                       'openedAt', 'halfOpenSuccesses', 'totalFallbacks', 'totalRecoveries')
    $content = Get-Content -LiteralPath $Path -Raw
    foreach ($key in $requiredKeys) {
        if (-not $content.Contains('"' + $key + '":')) { return $false }
    }
    $state = Get-BreakerField -Path $Path -Key 'state'
    if ($state -notin @('CLOSED', 'OPEN', 'HALF-OPEN')) { return $false }
    foreach ($key in @('fallbackIndex', 'cooldownSeconds', 'halfOpenSuccesses', 'totalFallbacks', 'totalRecoveries')) {
        $v = Get-BreakerField -Path $Path -Key $key
        if ($v -notmatch '^[0-9]+$') { return $false }
    }
    $opened = Get-BreakerField -Path $Path -Key 'openedAt'
    if ($opened -notmatch '^-?[0-9]+$') { return $false }
    return $true
}

# Return $true iff the file's final non-empty line is exactly `}` (the schema's
# terminator, breaker.ps1:124), comparing AFTER stripping a trailing CR so a
# CRLF-normalized but otherwise valid file still passes (harness 11c is the
# regression this guards). tail-equivalent only — no new runtime dep. A reader
# that fails only this check knows it caught a write mid-flight (torn), not a
# corrupt file.
function Test-BreakerTerminatorOk {
    param([Parameter(Mandatory)] [string]$Path)
    $lines = Get-Content -LiteralPath $Path
    $last = ''
    foreach ($line in $lines) {
        $trimmed = $line.TrimEnd("`r")
        if ($trimmed -ne '') { $last = $trimmed }
    }
    return $last -eq '}'
}

# Return $true iff Test-BreakerFieldsValid passes AND the terminator line is
# intact. This is the "parseable" gate Breaker-Load uses to decide
# return-untouched vs retry-or-fail-safe.
function Test-BreakerStateValid {
    param([Parameter(Mandatory)] [string]$Path)
    if (-not (Test-BreakerFieldsValid -Path $Path)) { return $false }
    if (-not (Test-BreakerTerminatorOk -Path $Path)) { return $false }
    return $true
}

# The ONE place that serializes the schema — every transition below funnels
# through this so the on-disk layout never drifts. LF-only, no BOM, to stay a
# byte-for-byte match with the bash twin's `printf`-written file. Atomicity
# rationale: writes go to a sibling temp file first, then
# [System.IO.File]::Move($tmp, $Path, $true) (overwrite variant, PowerShell 7+ /
# .NET Core) — atomic on NTFS via ReplaceFile semantics, so a concurrent reader
# can never observe a zero-length or partially-written file (the torn-read race
# this story closes). The temp name is colon-free (templates/loop/SKILL.template.md:27).
function Write-BreakerState {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$State,
        [Parameter(Mandatory)] [AllowEmptyString()] [string]$Chain,
        [Parameter(Mandatory)] [int]$FallbackIndex,
        [Parameter(Mandatory)] [AllowEmptyString()] [string]$CurrentModel,
        [Parameter(Mandatory)] [int]$CooldownSeconds,
        [Parameter(Mandatory)] [long]$OpenedAt,
        [Parameter(Mandatory)] [int]$HalfOpenSuccesses,
        [Parameter(Mandatory)] [int]$TotalFallbacks,
        [Parameter(Mandatory)] [int]$TotalRecoveries
    )
    $lines = @(
        '{'
        ('"state": "{0}",' -f $State)
        ('"chain": "{0}",' -f $Chain)
        ('"fallbackIndex": {0},' -f $FallbackIndex)
        ('"currentModel": "{0}",' -f $CurrentModel)
        ('"cooldownSeconds": {0},' -f $CooldownSeconds)
        ('"openedAt": {0},' -f $OpenedAt)
        ('"halfOpenSuccesses": {0},' -f $HalfOpenSuccesses)
        ('"totalFallbacks": {0},' -f $TotalFallbacks)
        ('"totalRecoveries": {0}' -f $TotalRecoveries)
        '}'
    )
    $text = ($lines -join "`n") + "`n"
    $tmp = "$Path.tmp.$PID"
    [System.IO.File]::WriteAllText($tmp, $text, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::Move($tmp, $Path, $true)
}

# Writes a fresh CLOSED state seeded from -Chain. currentModel = first chain
# entry, or "" when the chain is empty.
function New-BreakerSeed {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [AllowEmptyString()] [string]$Chain
    )
    $first = ''
    if ($Chain -ne '') { $first = ($Chain -split ',')[0] }
    Write-BreakerState -Path $Path -State 'CLOSED' -Chain $Chain -FallbackIndex 0 `
        -CurrentModel $first -CooldownSeconds 600 -OpenedAt 0 -HalfOpenSuccesses 0 `
        -TotalFallbacks 0 -TotalRecoveries 0
}

# Reads every field into a single hashtable — the PowerShell analog of bash's
# _BRK_* scratch-variable read, used by Breaker-ShouldSkip/Breaker-Record.
function Read-BreakerState {
    param([Parameter(Mandatory)] [string]$Path)
    return @{
        State             = Get-BreakerField -Path $Path -Key 'state'
        Chain             = Get-BreakerField -Path $Path -Key 'chain'
        FallbackIndex     = [int](Get-BreakerField -Path $Path -Key 'fallbackIndex')
        CurrentModel      = Get-BreakerField -Path $Path -Key 'currentModel'
        CooldownSeconds   = [int](Get-BreakerField -Path $Path -Key 'cooldownSeconds')
        OpenedAt          = [long](Get-BreakerField -Path $Path -Key 'openedAt')
        HalfOpenSuccesses = [int](Get-BreakerField -Path $Path -Key 'halfOpenSuccesses')
        TotalFallbacks    = [int](Get-BreakerField -Path $Path -Key 'totalFallbacks')
        TotalRecoveries   = [int](Get-BreakerField -Path $Path -Key 'totalRecoveries')
    }
}

# Mutates $s.FallbackIndex/$s.CurrentModel per the pinned rule: index++ (and
# currentModel = that entry) if a next entry exists, ELSE currentModel=""
# (chain-end reconciles with models.map's omit-the-pin rule). A further advance
# while already at chain-end recomputes the same false condition, so
# currentModel simply stays "" — no special "exhausted" sentinel needed.
function Step-BreakerChain {
    param([Parameter(Mandatory)] [hashtable]$State)
    $entries = @()
    if ($State.Chain -ne '') { $entries = $State.Chain -split ',' }
    $n = $entries.Length
    if (($State.FallbackIndex + 1) -lt $n) {
        $State.FallbackIndex = $State.FallbackIndex + 1
        $State.CurrentModel = $entries[$State.FallbackIndex]
    } else {
        $State.CurrentModel = ''
    }
}

# New-BreakerFailsafeOpen -Path <file> -Chain <chain-arg> -Now <now> -> seeds
# OPEN with openedAt=<now> and the full cooldown, carrying the COMPLETE field
# disposition (goal.md, cycle-1 MAJOR-4 fix): chain/fallbackIndex preserved if
# they individually parse, else <chain-arg>/0; currentModel preserved if it
# parses, else DERIVED as chain[fallbackIndex] (empty past chain end, per the
# omit-the-pin rule at breaker.ps1's Step-BreakerChain — never blindly
# chain[0], which would re-pin the just-rate-limited model and undo half the
# harm the inversion prevents); halfOpenSuccesses always resets to 0;
# totalFallbacks/totalRecoveries preserved if they parse, else 0. Called only
# from Breaker-Load's still-invalid branch below.
function New-BreakerFailsafeOpen {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [AllowEmptyString()] [string]$Chain,
        [Parameter(Mandatory)] [long]$Now
    )
    $rawChain = Get-BreakerField -Path $Path -Key 'chain'
    $chain = if ($null -ne $rawChain) { $rawChain } else { $Chain }

    $idx = 0
    $rawIdx = Get-BreakerField -Path $Path -Key 'fallbackIndex'
    if ($rawIdx -match '^[0-9]+$') { $idx = [int]$rawIdx }

    $rawModel = Get-BreakerField -Path $Path -Key 'currentModel'
    if ($null -ne $rawModel) {
        $model = $rawModel
    } else {
        $entries = @()
        if ($chain -ne '') { $entries = $chain -split ',' }
        $model = if ($idx -lt $entries.Length) { $entries[$idx] } else { '' }
    }

    $fb = 0
    $rawFb = Get-BreakerField -Path $Path -Key 'totalFallbacks'
    if ($rawFb -match '^[0-9]+$') { $fb = [int]$rawFb }

    $rec = 0
    $rawRec = Get-BreakerField -Path $Path -Key 'totalRecoveries'
    if ($rawRec -match '^[0-9]+$') { $rec = [int]$rawRec }

    Write-BreakerState -Path $Path -State 'OPEN' -Chain $chain -FallbackIndex $idx `
        -CurrentModel $model -CooldownSeconds 600 -OpenedAt $Now -HalfOpenSuccesses 0 `
        -TotalFallbacks $fb -TotalRecoveries $rec
}

# --- pinned API --------------------------------------------------------------

# Breaker-Load -Path <state-file> -Chain <chain> [-Now <now-epoch>]
# -Now is OPTIONAL ([long]$Now = 0, where 0 means "read now") and defaults to a
# wall-clock read at the API boundary when the caller does not inject one —
# every existing call site stays valid.
# Three branches (design §3.2 part 3):
#   - file absent -> seed fresh CLOSED from -Chain, silently (unchanged).
#   - present but failing ONLY the terminator check (torn — a write caught
#     mid-flight) -> re-read up to 3 times with a ~50ms backoff
#     (Start-Sleep -Milliseconds 50); a retry that becomes fully valid returns
#     silently, nothing rewritten, no warning.
#   - present and still invalid after that (or invalid for reasons beyond the
#     terminator, e.g. a dropped key -> no retry) -> FAIL SAFE, not fail
#     CLOSED-erasing: one stderr warning, then seed OPEN via
#     New-BreakerFailsafeOpen (openedAt=<now>, full cooldown, complete
#     per-field-preserved-if-parse disposition). This inverts the one branch
#     that could weaken protection: a lost/torn read now costs one cooldown
#     instead of silently erasing one.
function Breaker-Load {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [AllowEmptyString()] [string]$Chain,
        [long]$Now = 0
    )
    if ($Now -eq 0) { $Now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
    if (-not (Test-Path -LiteralPath $Path)) {
        New-BreakerSeed -Path $Path -Chain $Chain
        return
    }
    if (Test-BreakerStateValid -Path $Path) {
        return
    }
    if (Test-BreakerFieldsValid -Path $Path) {
        for ($attempt = 0; $attempt -lt 3; $attempt++) {
            Start-Sleep -Milliseconds 50
            if (Test-BreakerStateValid -Path $Path) { return }
        }
    }
    [Console]::Error.WriteLine("breaker: $Path is unreadable — failing SAFE to OPEN")
    New-BreakerFailsafeOpen -Path $Path -Chain $Chain -Now $Now
}

# Breaker-CurrentModel -Path <state-file> -> echoes currentModel (may be empty).
function Breaker-CurrentModel {
    param([Parameter(Mandatory)] [string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Output ''
        return
    }
    $model = Get-BreakerField -Path $Path -Key 'currentModel'
    Write-Output $model
}

# Breaker-ShouldSkip -Path <state-file> -Now <now-epoch>
# OPEN & cooldown not elapsed -> echo remaining seconds (clamped to
#   [0, cooldownSeconds]).
# OPEN & cooldown elapsed -> transition to HALF-OPEN (halfOpenSuccesses=0),
#   persist, echo 0.
# Any other state -> echo 0, no state change.
function Breaker-ShouldSkip {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [long]$Now
    )
    $s = Read-BreakerState -Path $Path

    if ($s.State -ne 'OPEN') {
        Write-Output 0
        return
    }

    $elapsed = $Now - $s.OpenedAt
    $remaining = $s.CooldownSeconds - $elapsed
    # Wall-clock anomaly guard: clamp to [0, cooldownSeconds].
    if ($remaining -lt 0) { $remaining = 0 }
    if ($remaining -gt $s.CooldownSeconds) { $remaining = $s.CooldownSeconds }

    if ($remaining -gt 0) {
        Write-Output $remaining
        return
    }

    $s.State = 'HALF-OPEN'
    $s.HalfOpenSuccesses = 0
    Write-BreakerState -Path $Path -State $s.State -Chain $s.Chain -FallbackIndex $s.FallbackIndex `
        -CurrentModel $s.CurrentModel -CooldownSeconds $s.CooldownSeconds -OpenedAt $s.OpenedAt `
        -HalfOpenSuccesses $s.HalfOpenSuccesses -TotalFallbacks $s.TotalFallbacks -TotalRecoveries $s.TotalRecoveries
    Write-Output 0
}

# Breaker-Record -Path <state-file> -RateLimited <0|1> -Now <now-epoch>
# Transitions exactly per goal.md's exhaustive table:
#   CLOSED   + 0 -> no-op.
#   CLOSED   + 1 -> OPEN; advance chain; openedAt=now; totalFallbacks++.
#   HALF-OPEN+ 0 -> halfOpenSuccesses++; at exactly 2 -> CLOSED (reset
#                   halfOpenSuccesses/openedAt; totalRecoveries++).
#   HALF-OPEN+ 1 -> OPEN; advance chain; openedAt=now (reset).
#   OPEN     +any -> defensive path (normally unreachable under mechanism B):
#                   log a warning, then treat exactly as the HALF-OPEN input above.
function Breaker-Record {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [int]$RateLimited,
        [Parameter(Mandatory)] [long]$Now
    )
    $s = Read-BreakerState -Path $Path

    if ($s.State -eq 'OPEN') {
        [Console]::Error.WriteLine('breaker: Breaker-Record called while OPEN (defensive path — mechanism B should make this unreachable); treating as HALF-OPEN input')
        $s.State = 'HALF-OPEN'
    }

    switch ($s.State) {
        'CLOSED' {
            if ($RateLimited -eq 1) {
                Step-BreakerChain -State $s
                $s.State = 'OPEN'
                $s.OpenedAt = $Now
                $s.TotalFallbacks = $s.TotalFallbacks + 1
                Write-BreakerState -Path $Path -State $s.State -Chain $s.Chain -FallbackIndex $s.FallbackIndex `
                    -CurrentModel $s.CurrentModel -CooldownSeconds $s.CooldownSeconds -OpenedAt $s.OpenedAt `
                    -HalfOpenSuccesses $s.HalfOpenSuccesses -TotalFallbacks $s.TotalFallbacks -TotalRecoveries $s.TotalRecoveries
            }
            # CLOSED + success -> no-op: nothing written.
        }
        'HALF-OPEN' {
            if ($RateLimited -eq 1) {
                Step-BreakerChain -State $s
                $s.State = 'OPEN'
                $s.OpenedAt = $Now
                Write-BreakerState -Path $Path -State $s.State -Chain $s.Chain -FallbackIndex $s.FallbackIndex `
                    -CurrentModel $s.CurrentModel -CooldownSeconds $s.CooldownSeconds -OpenedAt $s.OpenedAt `
                    -HalfOpenSuccesses $s.HalfOpenSuccesses -TotalFallbacks $s.TotalFallbacks -TotalRecoveries $s.TotalRecoveries
            } else {
                $s.HalfOpenSuccesses = $s.HalfOpenSuccesses + 1
                if ($s.HalfOpenSuccesses -eq 2) {
                    $s.State = 'CLOSED'
                    $s.HalfOpenSuccesses = 0
                    $s.OpenedAt = 0
                    $s.TotalRecoveries = $s.TotalRecoveries + 1
                }
                Write-BreakerState -Path $Path -State $s.State -Chain $s.Chain -FallbackIndex $s.FallbackIndex `
                    -CurrentModel $s.CurrentModel -CooldownSeconds $s.CooldownSeconds -OpenedAt $s.OpenedAt `
                    -HalfOpenSuccesses $s.HalfOpenSuccesses -TotalFallbacks $s.TotalFallbacks -TotalRecoveries $s.TotalRecoveries
            }
        }
    }
}
