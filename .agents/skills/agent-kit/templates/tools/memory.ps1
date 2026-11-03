#!/usr/bin/env pwsh
#Requires -Version 7.2
# memory — add|index|search|show|redact|check|rm|capture|backfill
# Twin: memory.sh (bash 3.2+) — behaviorally identical — any divergence is a bug.
# Emitted single-copy to `_kit/memory.ps1`.
#
# Supported invocation: `pwsh -File _kit/memory.ps1 …` or `pwsh _kit/memory.ps1 …` (not in-session `&`).
# All data and messages go to raw stdout/stderr; pipeline capture ($x = & memory.ps1 …) gets nothing by design.
#
#   memory.ps1 add --kind <k> --title <t> --body <path>
#             [--source <s>] [--tags <list>] [--supersedes <list>] [--harness <h>] [--root <dir>]
#   memory.ps1 index [--root <dir>]
#   memory.ps1 search <term>... [--kind <list>] [--limit <n>] [--include-superseded]
#             [--engine grep|fts] [--root <dir>]
#   memory.ps1 show <id> [--root <dir>]
#   memory.ps1 redact [--root <dir>]
#   memory.ps1 check [--staged] [--root <dir>] [<path>…]
#   memory.ps1 rm <id> [--root <dir>]
#   memory.ps1 capture [--harness cursor|claude|codex|all] [--from <dir>] … [--root <dir>]
#   backfill is bash-only — run bash _kit/memory.sh backfill (Windows: _kit\memory.cmd backfill)
#
# Exit codes: 0 ok · 2 usage/format · 3 gate failed · 4 missing root, file, id, or optional dependency · 5 quarantined.
# Errors: one line on stderr prefixed `memory: `. Store path: `<root>/_memory/`.
#
# Portability: PowerShell 7.2+; optional sqlite3 (FTS5 auto-detect). Byte domain: Latin-1 views, raw stdio.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Environment]::CurrentDirectory = (Get-Location -PSProvider FileSystem).ProviderPath

$Script:L1 = [Text.Encoding]::Latin1
$Script:U8 = [Text.Encoding]::UTF8
$Script:OutB = [Console]::OpenStandardOutput()
$Script:ErrB = [Console]::OpenStandardError()
$Script:Tab = [char]9
$Script:US = [char]0x1F
$Script:TmpPaths = [Collections.Generic.List[string]]::new()
$Script:SearchTerms = @()

$Script:ReId = '^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$'
$Script:ReTag = '^[a-z0-9][a-z0-9-]*$'
$Script:ReLimit = '^[1-9][0-9]*$'
$Script:ReMemNow = '^[0-9]{8}T[0-9]{6}Z$'
$Script:AdmissionRe = 'ignore (all )?(previous|prior|above) instructions|disregard (all )?(previous|prior|above)|you must now|new instructions:|<[|]?im_start[|]?>|</?system>'
$Script:Kinds = @('goal-summary','spawn-digest','session-summary','research-ingest','decision','learning','fact','pitfall')
$Script:Harnesses = @('claude','cursor','copilot','codex')
$Script:ReOpts = [Text.RegularExpressions.RegexOptions]::CultureInvariant
$Script:TagsTruncated = 0
$Script:RedactN = 0
$Script:RedactClasses = ''
$Script:RedactClassOrder = @('private-key','secret','aws-key','github-token','api-key','slack-token','jwt','azure-key')

function Register-Tmp([string]$Path) { [void]$Script:TmpPaths.Add($Path) }
function New-TmpFile { $p = [IO.Path]::GetTempFileName(); Register-Tmp $p; return $p }
function View([string]$s) { return $Script:L1.GetString($Script:U8.GetBytes($s)) }
function ViewBytes([byte[]]$b) { return $Script:L1.GetString($b) }
function Latin1Bytes([string]$v) { return $Script:L1.GetBytes($v) }
function Write-Latin1Line([IO.MemoryStream]$ms, [string]$text) {
  $bytes = $Script:L1.GetBytes($text)
  $n = @($bytes).Count
  if ($n -gt 0) { $ms.Write([byte[]]@($bytes), 0, $n) }
  $ms.WriteByte(0x0A)
}
function Split-Lf([string]$Text, [StringSplitOptions]$Opts = [StringSplitOptions]::None) {
  if ($null -eq $Text) { return ,@() }
  return ,@([string[]]$Text.Split([char]10, $Opts))
}

function Split-LfRedact([string]$Text) {
  if ($null -eq $Text) { return ,@('') }
  $lines = [string[]]$Text.Split([char]10)
  if ($lines.Count -gt 1 -and $lines[$lines.Count - 1] -eq '') {
    return ,@($lines[0..($lines.Count - 2)])
  }
  return ,@($lines)
}

function Test-InputTrailingLf([string]$path) {
  $b = [IO.File]::ReadAllBytes($path)
  if ($b.Length -eq 0) { return $false }
  return ($b[$b.Length - 1] -eq 0x0A)
}
function Write-Raw([IO.Stream]$st, [byte[]]$b) { $st.Write($b, 0, $b.Length) }
function Write-Stdout([byte[]]$b) { Write-Raw $Script:OutB $b }
function Write-Stderr([byte[]]$b) { Write-Raw $Script:ErrB $b }
function Write-StdoutUtf8([string]$t) { Write-Stdout ($Script:U8.GetBytes($t)) }
function Write-StderrUtf8([string]$t) { Write-Stderr ($Script:U8.GetBytes($t)) }
function Die([int]$Code, [string]$Msg) { Write-Stderr (Latin1Bytes "memory: $Msg`n"); exit $Code }

function Test-Dir([string]$p) {
  if ([IO.Directory]::Exists($p)) { return $true }
  return (Test-Path -LiteralPath $p -PathType Container)
}

function Test-File([string]$p) {
  if ([string]::IsNullOrEmpty($p)) { return $false }
  if ([IO.File]::Exists($p)) { return $true }
  try { return (Test-Path -LiteralPath $p -PathType Leaf) } catch { return $false }
}

function Strip-DoubleQuotes([string]$val) {
  if ($val.StartsWith('"', [StringComparison]::Ordinal)) { $val = $val.Substring(1) }
  if ($val.EndsWith('"', [StringComparison]::Ordinal)) { $val = $val.Substring(0, $val.Length - 1) }
  return $val
}

function Get-UsageText {
  return @(
    'usage: memory.sh <add|index|search|show|redact|check|rm|capture|backfill> [--root <dir>] ...'
    '  add    --kind <k> --title <t> --body <path> [--source <s>] [--tags <list>] [--supersedes <list>] [--harness <h>]'
    '  index  [--root <dir>]'
    '  search <term>... [--kind <list>] [--limit <n>] [--include-superseded] [--engine grep|fts]'
    '  show   <id> [--root <dir>]'
    '  redact [--root <dir>]'
    '  check  [--staged] [--root <dir>] [<path>…]'
    '  rm     <id> [--root <dir>]'
    '  capture [--harness cursor|claude|codex|all] [--from <dir>] [--idle-hours <n>] [--since <YYYY-MM-DD>] [--root <dir>]'
    '  backfill [--plan|--apply] [--goals] [--research] [--escalations] [--only <name>] [--root <dir>]'
    'exit: 0 ok · 2 usage/format · 3 gate failed · 4 missing root/file/id/dependency · 5 quarantined'
  ) -join "`n"
}

function Show-UsageStdout { Write-StdoutUtf8("$(Get-UsageText)`n") }
function Show-UsageStderr { Write-StderrUtf8("$(Get-UsageText)`n") }

function Test-Re([string]$ViewStr, [string]$Ere) {
  if ($ViewStr.Contains([char]10)) { return $false }
  return [regex]::IsMatch($ViewStr, $Ere, $Script:ReOpts)
}

function Test-Kind([string]$k) { return [Array]::IndexOf($Script:Kinds, $k) -ge 0 }
function Test-Harness([string]$h) { return [Array]::IndexOf($Script:Harnesses, $h) -ge 0 }

function Trim-AsciiSp([string]$s) {
  while ($s.Length -gt 0 -and [int][char]$s[0] -eq 32) { $s = $s.Substring(1) }
  while ($s.Length -gt 0 -and [int][char]$s[$s.Length - 1] -eq 32) { $s = $s.Substring(0, $s.Length - 1) }
  return $s
}

function Fold-Ascii([string]$s) {
  $ca = $s.ToCharArray()
  for ($i = 0; $i -lt $ca.Length; $i++) {
    $c = [int][char]$ca[$i]
    if ($c -ge 65 -and $c -le 90) { $ca[$i] = [char]($c + 32) }
  }
  return -join $ca
}

function Has-ControlBytes([string]$v) {
  foreach ($ch in $v.ToCharArray()) {
    $b = [int][char]$ch
    if ($b -lt 0x20 -or $b -eq 0x7F) { return $true }
  }
  return $false
}

function Escape-Source([string]$s) {
  return ($s -replace '"',"'" -replace '\\','/')
}

function Parse-List([string]$Raw, [string]$Mode) {
  $items = [Collections.Generic.List[string]]::new()
  $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  if ([string]::IsNullOrEmpty($Raw)) { return ,@() }
  $rest = $Raw
  while ($true) {
    $idx = $rest.IndexOf([char]',')
    if ($idx -lt 0) { $part = $rest; $rest = '' } else { $part = $rest.Substring(0, $idx); $rest = $rest.Substring($idx + 1) }
    $item = Trim-AsciiSp $part
    if ($item.Length -eq 0) { if ($rest.Length -eq 0) { break }; continue }
    switch ($Mode) {
      'tag' { if (-not (Test-Re $item $Script:ReTag)) { throw 'bad' } }
      'id' { if (-not (Test-Re $item $Script:ReId)) { throw 'bad' } }
      'kind' { if (-not (Test-Kind $item)) { throw 'bad' } }
    }
    if ($seen.Add($item)) { [void]$items.Add($item) }
    if ($rest.Length -eq 0) { break }
  }
  return ,@($items.ToArray())
}

function List-ToYamlInline($Items) {
  $arr = @($Items)
  if ($arr.Count -eq 0) { return '[]' }
  return '[' + ($arr -join ', ') + ']'
}

function List-ToComma([string]$UsJoined) {
  if ([string]::IsNullOrEmpty($UsJoined)) { return '' }
  $parts = [Collections.Generic.List[string]]::new()
  $rest = $UsJoined
  while ($true) {
    $idx = $rest.IndexOf($Script:US)
    if ($idx -lt 0) { $x = $rest; $rest = '' } else { $x = $rest.Substring(0, $idx); $rest = $rest.Substring($idx + 1) }
    if ($x.Length -gt 0) { [void]$parts.Add($x) }
    if ($rest.Length -eq 0) { break }
  }
  return ($parts -join ',')
}

function Invoke-GitStdout([string[]]$GitArgs) {
  $cmds = @(Get-Command git -CommandType Application -ErrorAction Ignore)
  if ($cmds.Count -lt 1) { return $null }
  $c = $cmds[0]
  $psi = [Diagnostics.ProcessStartInfo]::new($c.Path)
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
  foreach ($ga in $GitArgs) { [void]$psi.ArgumentList.Add($ga) }
  $p = [Diagnostics.Process]::Start($psi)
  $out = $p.StandardOutput.ReadToEnd()
  $null = $p.StandardError.ReadToEnd()
  $p.WaitForExit()
  if ($p.ExitCode -ne 0) { return $null }
  return $out.TrimEnd([char]10, [char]13)
}

function Get-DefaultRoot() {
  $o = Invoke-GitStdout @('rev-parse', '--show-toplevel')
  if ($o) { return $o }
  return $PWD.Path
}

function Resolve-Root([string]$r) {
  if (-not (Test-Dir $r)) { Die 4 "root directory not found: $(View $r)" }
  return $r
}

function Store-Dir([string]$root) { return Join-Path $root '_memory' }

function Rel-Path([string]$root, [string]$abs) {
  $rp = ($root -replace '\\', '/').TrimEnd('/')
  $norm = ($abs -replace '\\', '/')
  $prefix = $rp + '/'
  if ($norm.StartsWith($prefix, [StringComparison]::Ordinal)) { return $norm.Substring($prefix.Length) }
  return $norm
}

function Id-ToRecord([string]$store, [string]$id) {
  return Join-Path $store ("records/{0}/{1}/{2}.md" -f $id.Substring(0,4), $id.Substring(4,2), $id)
}

function Id-ToQuarantine([string]$store, [string]$id) {
  return Join-Path $store "quarantine/$id.md"
}

function Get-Sha256Hex([byte[]]$data) {
  $h = [Security.Cryptography.SHA256]::HashData($data)
  return ([BitConverter]::ToString($h) -replace '-','').ToLowerInvariant()
}

function Get-CommitShort([string]$root) {
  $o = Invoke-GitStdout @('-C', $root, 'rev-parse', '--short=12', 'HEAD')
  if (-not $o) { return 'none' }
  return $o
}

function Utc-NowPrefix() {
  return (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ', [cultureinfo]::InvariantCulture)
}

function Body-HasNul([string]$path) {
  try {
    $b = [IO.File]::ReadAllBytes($path)
  } catch {
    Die 4 "body file not found: $(View $path)"
  }
  return [Array]::IndexOf($b, [byte]0) -ge 0
}

function Normalize-BodyBytes([byte[]]$raw) {
  if ($raw.Length -eq 0) { return $null }
  $endLf = ($raw[$raw.Length - 1] -eq 0x0A)
  $lines = [Collections.Generic.List[string]]::new()
  $start = 0
  for ($i = 0; $i -le $raw.Length; $i++) {
    if ($i -eq $raw.Length -or $raw[$i] -eq 0x0A) {
      $len = $i - $start
      if ($len -gt 0) {
        $lb = [byte[]]($raw[$start..($i - 1)])
      } else {
        $lb = [byte[]]@()
      }
      $line = ViewBytes $lb
      if ($lines.Count -eq 0 -and $line.Length -ge 3) {
        $b0 = [int][char]$line[0]; $b1 = [int][char]$line[1]; $b2 = [int][char]$line[2]
        if ($b0 -eq 0xEF -and $b1 -eq 0xBB -and $b2 -eq 0xBF) { $line = $line.Substring(3) }
      }
      $isLast = ($i -eq $raw.Length)
      if (-not $isLast -or $endLf) {
        if ($line.Length -gt 0 -and [int][char]$line[$line.Length - 1] -eq 0x0D) {
          $line = $line.Substring(0, $line.Length - 1)
        }
      }
      [void]$lines.Add($line)
      $start = $i + 1
    }
  }
  while ($lines.Count -gt 0) {
    $ln = $lines[$lines.Count - 1]
    if ($ln -match '^[ \t]*$') { $lines.RemoveAt($lines.Count - 1) } else { break }
  }
  if ($lines.Count -lt 1) { return $null }
  $ms = [IO.MemoryStream]::new()
  for ($j = 0; $j -lt $lines.Count; $j++) {
    $bb = [byte[]]$Script:L1.GetBytes([string]$lines[$j])
    if ($bb.Length -gt 0) { $ms.Write($bb, 0, $bb.Length) }
    $ms.WriteByte(0x0A)
  }
  return $ms.ToArray()
}

function Prepare-BodyFile([string]$inPath) {
  if (-not (Test-File $inPath)) { Die 4 "body file not found: $(View $inPath)" }
  if (Body-HasNul $inPath) { Die 2 'body contains NUL byte' }
  try {
    $raw = [IO.File]::ReadAllBytes($inPath)
  } catch {
    Die 4 "body file not found: $(View $inPath)"
  }
  $norm = Normalize-BodyBytes $raw
  if ($null -eq $norm -or $norm.Length -lt 1) { Die 2 'invalid body' }
  if ($norm.Length -gt 4096) { Die 2 'invalid body' }
  $tmp = New-TmpFile
  [IO.File]::WriteAllBytes($tmp, $norm)
  return $tmp
}

function Test-Admission([string]$titleView, [string]$bodyFile) {
  if ([regex]::IsMatch((Fold-Ascii $titleView), $Script:AdmissionRe, $Script:ReOpts)) { return $true }
  $bodyBytes = [IO.File]::ReadAllBytes($bodyFile)
  $bodyView = ViewBytes $bodyBytes
  foreach ($line in (Split-Lf $bodyView)) {
    $ln = $line
    if ($ln.Length -gt 0 -and [int][char]$ln[$ln.Length - 1] -eq 0x0D) { $ln = $ln.Substring(0, $ln.Length - 1) }
    if ([regex]::IsMatch((Fold-Ascii $ln), $Script:AdmissionRe, $Script:ReOpts)) { return $true }
  }
  return $false
}

function Test-FileHasTrailingLf([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) { return $false }
  $b = [IO.File]::ReadAllBytes($path)
  if ($b.Length -eq 0) { return $false }
  return ($b[$b.Length - 1] -eq 0x0A)
}

function Strip-TrailingLfFile([string]$path) {
  $b = [IO.File]::ReadAllBytes($path)
  if ($b.Length -eq 0) { return }
  if ($b[$b.Length - 1] -ne 0x0A) { return }
  $nb = [byte[]]::new($b.Length - 1)
  [Array]::Copy($b, $nb, $nb.Length)
  [IO.File]::WriteAllBytes($path, $nb)
}

function Count-RedactMarkers([string]$path, [string]$cls) {
  $needle = "[REDACTED:$cls]"
  $n = 0
  $view = ViewBytes ([IO.File]::ReadAllBytes($path))
  $idx = 0
  while ($true) {
    $i = $view.IndexOf($needle, $idx, [StringComparison]::Ordinal)
    if ($i -lt 0) { break }
    $n++
    $idx = $i + $needle.Length
  }
  return $n
}

function Merge-RedactClasses([string]$a, [string]$b) {
  $out = [Collections.Generic.List[string]]::new()
  foreach ($cls in $Script:RedactClassOrder) {
    $hit = $false
    foreach ($part in ($a -split ',')) { if ($part -ceq $cls) { $hit = $true; break } }
    if (-not $hit) {
      foreach ($part in ($b -split ',')) { if ($part -ceq $cls) { $hit = $true; break } }
    }
    if ($hit) { [void]$out.Add($cls) }
  }
  $Script:RedactClasses = ($out -join ',')
}

function Print-RedactNotice {
  if ($Script:RedactN -le 0) { return }
  Write-StderrUtf8("memory: redacted $($Script:RedactN) secret(s): $($Script:RedactClasses)`n")
}

function Print-AddNotices {
  Print-RedactNotice
  if ($Script:TagsTruncated -eq 1) {
    Write-StderrUtf8("memory: tags truncated to 6`n")
  }
}

function Normalize-TagsList([string]$Raw) {
  $Script:TagsTruncated = 0
  if ([string]::IsNullOrEmpty($Raw)) { return ,@() }
  $parts = [regex]::Split($Raw, '[, \t\n\r\v\f]+')
  $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  $all = [Collections.Generic.List[string]]::new()
  foreach ($p in $parts) {
    if ($p.Length -eq 0) { continue }
    $w = Fold-Ascii $p
    if ($w.Length -eq 0) { continue }
    if (-not $seen.Add($w)) { continue }
    if (-not (Test-Re $w $Script:ReTag)) { throw 'bad' }
    [void]$all.Add($w)
  }
  $kept = [Collections.Generic.List[string]]::new()
  for ($i = 0; $i -lt $all.Count; $i++) {
    if ($i -lt 6) { [void]$kept.Add($all[$i]) }
    else { $Script:TagsTruncated = 1 }
  }
  return ,@($kept.ToArray())
}

function Redact-PrivateKeyBody([string]$inPath, [string]$outPath) {
  $view = ViewBytes ([IO.File]::ReadAllBytes($inPath))
  $lines = Split-LfRedact $view
  $inBlock = $false
  $outLines = [Collections.Generic.List[string]]::new()
  foreach ($line in $lines) {
    $ln = [string]$line
    if ($inBlock) {
      if ([regex]::IsMatch($ln, '-----END [A-Z0-9 ]*PRIVATE KEY-----', $Script:ReOpts)) { $inBlock = $false }
      continue
    }
    if ([regex]::IsMatch($ln, '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----', $Script:ReOpts) -and
        [regex]::IsMatch($ln, '-----END [A-Z0-9 ]*PRIVATE KEY-----', $Script:ReOpts)) {
      [void]$outLines.Add('[REDACTED:private-key]')
      continue
    }
    if ([regex]::IsMatch($ln, '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----', $Script:ReOpts)) {
      [void]$outLines.Add('[REDACTED:private-key]')
      $inBlock = $true
      continue
    }
    [void]$outLines.Add($ln)
  }
  $ms = [IO.MemoryStream]::new()
  for ($j = 0; $j -lt $outLines.Count; $j++) {
    Write-Latin1Line $ms ([string]$outLines[$j])
  }
  [IO.File]::WriteAllBytes($outPath, $ms.ToArray())
}

function Test-SecretSpace([char]$c) {
  $b = [int][char]$c
  return ($b -eq 32 -or $b -eq 9 -or $b -eq 10 -or $b -eq 13 -or $b -eq 11 -or $b -eq 12)
}

function Test-SecretBadFirst([char]$c) {
  if (Test-SecretSpace $c) { return $true }
  $b = [string]$c
  if ($b -ceq '[' -or $b -ceq ']' -or $b -ceq '"' -or $b -ceq "'" -or $b -ceq '<' -or $b -ceq '$' -or $b -ceq '{' -or $b -ceq '`') { return $true }
  return $false
}

function Test-SecretBadRest([char]$c) {
  if (Test-SecretSpace $c) { return $true }
  $b = [string]$c
  if ($b -ceq '"' -or $b -ceq "'" -or $b -ceq '`' -or $b -ceq ',' -or $b -ceq ';') { return $true }
  return $false
}

function Test-SecretKeyAt([string]$line, [int]$pos, [string]$key) {
  for ($j = 0; $j -lt $key.Length; $j++) {
    $c1 = Fold-Ascii ([string]$line[$pos + $j - 1])
    $c2 = Fold-Ascii ([string]$key[$j])
    if ($c1 -cne $c2) { return $false }
  }
  return $true
}

function Match-SecretKey([string]$line, [int]$pos) {
  $keys = @('password','passwd','pwd','secret','client_secret','token','access_token','api_key','api-key','apikey')
  foreach ($k in $keys) {
    if ($pos + $k.Length - 1 -le $line.Length -and (Test-SecretKeyAt $line $pos $k)) { return $k }
  }
  return ''
}

function Get-SecretValueStart([string]$line, [int]$p) {
  $n = $line.Length
  if ($p -le $n -and ($line[$p - 1] -ceq '"' -or $line[$p - 1] -ceq "'")) { $p++ }
  while ($p -le $n -and (Test-SecretSpace $line[$p - 1])) { $p++ }
  if ($p -gt $n) { return 0 }
  $ch = $line[$p - 1]
  if ($ch -cne '=' -and $ch -cne ':') { return 0 }
  $p++
  while ($p -le $n -and (Test-SecretSpace $line[$p - 1])) { $p++ }
  if ($p -le $n -and ($line[$p - 1] -ceq '"' -or $line[$p - 1] -ceq "'")) { $p++ }
  if ($p -gt $n) { return 0 }
  return $p
}

function Redact-SecretLine([string]$line) {
  $keys = @('password','passwd','pwd','secret','client_secret','token','access_token','api_key','api-key','apikey')
  $null = $keys
  $out = [Text.StringBuilder]::new()
  $i = 1
  $n = $line.Length
  while ($i -le $n) {
    $c = $line[$i - 1]
    $b = ($i -eq 1)
    if (-not $b) {
      $prev = $line[$i - 2]
      $b = -not ([regex]::IsMatch([string]$prev, '[A-Za-z0-9_]', $Script:ReOpts))
    }
    if ($b) {
      $key = Match-SecretKey $line $i
      if ($key.Length -gt 0) {
        $k = $key.Length
        $sepFrom = $i + $k
        $valStart = Get-SecretValueStart $line $sepFrom
        if ($valStart -gt 0) {
          $ch = $line[$valStart - 1]
          if (-not (Test-SecretBadFirst $ch)) {
            $valEnd = $valStart
            while ($valEnd -lt $n) {
              $ch2 = $line[$valEnd]
              if (Test-SecretBadRest $ch2) { break }
              $valEnd++
            }
            if ($valEnd - $valStart + 1 -ge 8) {
              [void]$out.Append($line.Substring($i - 1, $k))
              [void]$out.Append($line.Substring($sepFrom - 1, $valStart - $sepFrom))
              [void]$out.Append('[REDACTED:secret]')
              $i = $valEnd + 1
              continue
            }
          }
        }
      }
    }
    [void]$out.Append($c)
    $i++
  }
  return $out.ToString()
}

function Redact-SecretAssignments([string]$inPath, [string]$outPath) {
  $view = ViewBytes ([IO.File]::ReadAllBytes($inPath))
  $lines = Split-LfRedact $view
  $ms = [IO.MemoryStream]::new()
  foreach ($line in $lines) {
    $ln = [string]$line
    $red = Redact-SecretLine $ln
    Write-Latin1Line $ms $red
  }
  [IO.File]::WriteAllBytes($outPath, $ms.ToArray())
}

function Redact-SedPassSimple([string]$inPath, [string]$outPath, [string]$pattern, [string]$replacement) {
  $view = ViewBytes ([IO.File]::ReadAllBytes($inPath))
  $lines = Split-LfRedact $view
  $ms = [IO.MemoryStream]::new()
  foreach ($line in $lines) {
    $ln = [string]$line
    $red = [regex]::Replace($ln, $pattern, $replacement, $Script:ReOpts)
    Write-Latin1Line $ms $red
  }
  [IO.File]::WriteAllBytes($outPath, $ms.ToArray())
}

function Memory-RedactFile([string]$inPath, [string]$outPath, [bool]$includePrivateKey) {
  $step = New-TmpFile
  $tmp = New-TmpFile
  if ($includePrivateKey) {
    Redact-PrivateKeyBody $inPath $step
  } else {
    [IO.File]::WriteAllBytes($step, [IO.File]::ReadAllBytes($inPath))
  }
  Redact-SecretAssignments $step $tmp
  [IO.File]::WriteAllBytes($step, [IO.File]::ReadAllBytes($tmp))
  Redact-SedPassSimple $step $tmp '((AKIA|ASIA)[0-9A-Z]{16})' '[REDACTED:aws-key]'
  [IO.File]::WriteAllBytes($step, [IO.File]::ReadAllBytes($tmp))
  Redact-SedPassSimple $step $tmp '(^|[^A-Za-z0-9_])((gh[pousr]_[A-Za-z0-9]{36,}))' '${1}[REDACTED:github-token]'
  [IO.File]::WriteAllBytes($step, [IO.File]::ReadAllBytes($tmp))
  Redact-SedPassSimple $step $tmp '(^|[^A-Za-z0-9_])((github_pat_[A-Za-z0-9_]{22,}))' '${1}[REDACTED:github-token]'
  [IO.File]::WriteAllBytes($step, [IO.File]::ReadAllBytes($tmp))
  Redact-SedPassSimple $step $tmp '(^|[^A-Za-z0-9_-])((sk-(ant-)?[A-Za-z0-9_-]{20,}))' '${1}[REDACTED:api-key]'
  [IO.File]::WriteAllBytes($step, [IO.File]::ReadAllBytes($tmp))
  Redact-SedPassSimple $step $tmp '(xox[abprs]-[A-Za-z0-9-]{10,})' '[REDACTED:slack-token]'
  [IO.File]::WriteAllBytes($step, [IO.File]::ReadAllBytes($tmp))
  Redact-SedPassSimple $step $tmp '(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})' '[REDACTED:jwt]'
  [IO.File]::WriteAllBytes($step, [IO.File]::ReadAllBytes($tmp))
  Redact-SedPassSimple $step $tmp '((AccountKey|SharedAccessKey)=)([^\[\];"'' \t\n\r\v\f][^;"'' \t\n\r\v\f]*)' '${1}[REDACTED:azure-key]'
  [IO.File]::WriteAllBytes($step, [IO.File]::ReadAllBytes($tmp))
  [IO.File]::Copy($step, $outPath, $true)
  if (-not (Test-InputTrailingLf $inPath)) {
    Strip-TrailingLfFile $outPath
  }
  $total = 0
  $classes = [Collections.Generic.List[string]]::new()
  foreach ($cls in $Script:RedactClassOrder) {
    if (-not $includePrivateKey -and $cls -ceq 'private-key') { continue }
    $before = Count-RedactMarkers $inPath $cls
    $after = Count-RedactMarkers $outPath $cls
    $delta = $after - $before
    if ($delta -gt 0) {
      $total += $delta
      [void]$classes.Add($cls)
    }
  }
  $Script:RedactN = $total
  $Script:RedactClasses = ($classes -join ',')
}

function Invoke-BashOnlySub([string]$sub) {
  Die 2 "'$sub' is bash-only; run bash _kit/memory.sh $sub (Windows: _kit\memory.cmd $sub)"
}

function Read-Frontmatter([string]$path, [ref]$Fm) {
  $Fm.Value = @{
    id=''; kind=''; title=''; date=''; source=''; commit=''; harness=''; tags=''; supersedes=''; sha256=''
  }
  if (-not (Test-IsRegularRecordFile $path)) { return $false }
  try {
    $view = ViewBytes ([IO.File]::ReadAllBytes($path))
  } catch { return $false }
  $lines = Split-Lf $view
  if ($lines.Count -lt 1) { return $false }
  $first = [string]$lines[0]
  if ($first.Length -gt 0 -and [int][char]$first[$first.Length - 1] -eq 0x0D) { $first = $first.Substring(0, $first.Length - 1) }
  if ($first -cne '---') { return $false }
  $in = $true; $closed = $false
  $h = @{ id=0; kind=0; title=0; date=0; source=0; commit=0; harness=0; tags=0; supersedes=0; sha256=0 }
  for ($i = 1; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line.Length -gt 0 -and [int][char]$line[$line.Length - 1] -eq 0x0D) { $line = $line.Substring(0, $line.Length - 1) }
    if ($line -ceq '---') { $closed = $true; break }
    $ci = $line.IndexOf([char]':' )
    $key = if ($ci -lt 0) { $line } else { $line.Substring(0, $ci) }
    $vi = $line.IndexOf(': ', [StringComparison]::Ordinal)
    $val = if ($vi -lt 0) { $line } else { $line.Substring($vi + 2) }
    switch -CaseSensitive ($key) {
      'id' { $Fm.Value.id = $val; $h.id = 1 }
      'kind' { $Fm.Value.kind = $val; $h.kind = 1 }
      'title' { $Fm.Value.title = (Strip-DoubleQuotes $val); $h.title = 1 }
      'date' { $Fm.Value.date = $val; $h.date = 1 }
      'source' { $Fm.Value.source = (Strip-DoubleQuotes $val); $h.source = 1 }
      'commit' { $Fm.Value.commit = $val; $h.commit = 1 }
      'harness' { $Fm.Value.harness = (Strip-DoubleQuotes $val); $h.harness = 1 }
      'tags' { $Fm.Value.tags = $val; $h.tags = 1 }
      'supersedes' { $Fm.Value.supersedes = $val; $h.supersedes = 1 }
      'sha256' { $Fm.Value.sha256 = $val; $h.sha256 = 1 }
      'quarantined' { }
      default { }
    }
  }
  if (-not $closed) { return $false }
  foreach ($k in @('id','kind','title','date','source','commit','harness','tags','supersedes','sha256')) {
    if ($h[$k] -ne 1) { return $false }
  }
  return $true
}

# Canonical real path of a directory: every symlinked component of the absolute path
# (ancestors included, not just the last one) is replaced by its target, `.`/`..` are
# applied physically, and the result has no trailing separator. This is the string
# equivalent of the (device, inode) identity GNU `find -L` compares for loop detection.
# Returns $null if the path does not resolve to an existing directory, or if more than
# 40 links are followed (Linux MAXSYMLINKS) so a link cycle can never hang.
function Get-CanonicalDir([string]$path) {
  if ([string]::IsNullOrEmpty($path)) { return $null }
  try {
    if (-not [IO.Path]::IsPathRooted($path)) {
      $path = [IO.Path]::Combine([IO.Directory]::GetCurrentDirectory(), $path)
    }
    $root = [IO.Path]::GetPathRoot($path)
    $seps = [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $pending = [Collections.Generic.List[string]]::new()
    $pending.AddRange([string[]]$path.Substring($root.Length).Split($seps, [StringSplitOptions]::RemoveEmptyEntries))
    $cur = $root
    $hops = 0
    $i = 0
    while ($i -lt $pending.Count) {
      $comp = $pending[$i]; $i++
      if ($comp -ceq '.') { continue }
      if ($comp -ceq '..') {
        if ($cur.Length -gt $root.Length) { $cur = [IO.Path]::GetDirectoryName($cur) }
        continue
      }
      $cand = [IO.Path]::Combine($cur, $comp)
      $lt = [IO.DirectoryInfo]::new($cand).LinkTarget
      if ($null -ne $lt) {
        $hops++
        if ($hops -gt 40) { return $null }
        $rest = $pending.GetRange($i, $pending.Count - $i)
        $pending.Clear()
        if ([IO.Path]::IsPathRooted($lt)) {
          $lr = [IO.Path]::GetPathRoot($lt)
          $cur = $lr
          $lt = $lt.Substring($lr.Length)
        }
        $pending.AddRange([string[]]$lt.Split($seps, [StringSplitOptions]::RemoveEmptyEntries))
        $pending.AddRange($rest)
        $i = 0
        continue
      }
      if (-not [IO.Directory]::Exists($cand)) { return $null }
      $cur = $cand
    }
    if (-not [IO.Directory]::Exists($cur)) { return $null }
    return $cur
  } catch { return $null }
}

function Test-DirLoop([string]$realDir, [string]$listingDirReal, [Collections.Generic.HashSet[string]]$stack) {
  if ($null -eq $realDir) { return $true }
  if ($realDir.Equals($listingDirReal, [StringComparison]::Ordinal)) { return $true }
  return $stack.Contains($realDir)
}

function Get-ChildEntryNames([string]$dir) {
  $names = [Collections.Generic.List[string]]::new()
  if (-not (Test-Path -LiteralPath $dir)) { return ,@() }
  try {
    foreach ($ent in [IO.Directory]::EnumerateFileSystemEntries($dir)) {
      [void]$names.Add([IO.Path]::GetFileName($ent))
    }
  } catch { }
  return ,([string[]]$names.ToArray())
}

function Test-IsRegularRecordFile([string]$path) {
  if ([string]::IsNullOrEmpty($path)) { return $false }
  if (-not (Test-Path -LiteralPath $path)) { return $false }
  try {
    $fi = [IO.FileInfo]::new($path)
    if ($fi.Attributes -band [IO.FileAttributes]::ReparsePoint) {
      $target = $fi.ResolveLinkTarget($true)
      if ($null -eq $target -or -not $target.Exists) { return $false }
      if ($target -is [IO.DirectoryInfo]) { return $false }
      return -not ($target.Attributes -band [IO.FileAttributes]::Directory)
    }
    if (-not $fi.Exists) { return $false }
    return -not ($fi.Attributes -band [IO.FileAttributes]::Directory)
  } catch { return $false }
}

function Get-RecordMtimeUtc([string]$path) {
  try {
    $fi = [IO.FileInfo]::new($path)
    if ($fi.Attributes -band [IO.FileAttributes]::ReparsePoint) {
      $target = $fi.ResolveLinkTarget($true)
      if ($null -eq $target -or -not $target.Exists) { return [datetime]::MinValue }
      if ($target -is [IO.DirectoryInfo]) { return [datetime]::MinValue }
      return $target.LastWriteTimeUtc
    }
    if (-not $fi.Exists) { return [datetime]::MinValue }
    return $fi.LastWriteTimeUtc
  } catch { return [datetime]::MinValue }
}

function Add-IdMdFiles([Collections.Generic.List[string]]$out, [string]$dir) {
  if (-not (Test-Path -LiteralPath $dir)) { return }
  try {
    foreach ($f in [IO.Directory]::EnumerateFiles($dir, '*.md')) {
      if (-not $f.EndsWith('.md', [StringComparison]::Ordinal)) { continue }
      if (-not (Test-IsRegularRecordFile $f)) { continue }
      if (Test-Re ([IO.Path]::GetFileNameWithoutExtension($f)) $Script:ReId) { [void]$out.Add($f) }
    }
  } catch { }
}

function Get-RecordFiles([string]$store) {
  $out = [Collections.Generic.List[string]]::new()
  $rec = Join-Path $store 'records'
  if (-not (Test-Path -LiteralPath $rec)) { return ,@() }
  $recReal = Get-CanonicalDir $rec
  if ($null -eq $recReal) { return ,@() }
  $stack = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  [void]$stack.Add($recReal)
  foreach ($yyName in (Get-ChildEntryNames $rec)) {
    if (-not (Test-Re $yyName '^[0-9]{4}$')) { continue }
    $yyPath = Join-Path $rec $yyName
    $yyReal = Get-CanonicalDir $yyPath
    if ($null -eq $yyReal) { continue }
    if (Test-DirLoop $yyReal $recReal $stack) { continue }
    [void]$stack.Add($yyReal)
    try {
      foreach ($mmName in (Get-ChildEntryNames $yyPath)) {
        if (-not (Test-Re $mmName '^[0-9]{2}$')) { continue }
        $mmPath = Join-Path $yyPath $mmName
        $mmReal = Get-CanonicalDir $mmPath
        if ($null -eq $mmReal) { continue }
        if (Test-DirLoop $mmReal $yyReal $stack) { continue }
        [void]$stack.Add($mmReal)
        try { Add-IdMdFiles $out $mmPath }
        finally { [void]$stack.Remove($mmReal) }
      }
    } finally { [void]$stack.Remove($yyReal) }
  }
  return ,([string[]]$out.ToArray())
}

function Get-DedupeFiles([string]$store) {
  $out = [Collections.Generic.List[string]]::new()
  foreach ($f in (Get-RecordFiles $store)) { [void]$out.Add($f) }
  Add-IdMdFiles $out (Join-Path $store 'quarantine')
  return ,([string[]]$out.ToArray())
}

function Parse-Brackets([string]$raw) {
  $inner = $raw
  if ($inner.StartsWith('[', [StringComparison]::Ordinal) -and $inner.EndsWith(']', [StringComparison]::Ordinal)) {
    $inner = $inner.Substring(1, $inner.Length - 2)
  }
  $items = [Collections.Generic.List[string]]::new()
  if ([string]::IsNullOrEmpty($inner)) { return '' }
  $rest = $inner
  while ($true) {
    $idx = $rest.IndexOf([char]',')
    if ($idx -lt 0) { $x = $rest; $rest = '' } else { $x = $rest.Substring(0, $idx); $rest = $rest.Substring($idx + 1) }
    $x = Trim-AsciiSp $x
    if ($x.Length -gt 0) { [void]$items.Add($x) }
    if ($rest.Length -eq 0) { break }
  }
  return ($items -join $Script:US)
}

function Write-RecordFile([string]$path, [hashtable]$Meta, [byte[]]$bodyBytes, [bool]$quarantine) {
  $dir = Split-Path -Parent $path
  [IO.Directory]::CreateDirectory($dir) | Out-Null
  $tagsYaml = List-ToYamlInline $Meta.tagsItems
  $supYaml = List-ToYamlInline $Meta.supItems
  $srcEsc = Escape-Source $Meta.source
  $ms = [IO.MemoryStream]::new()
  function Add-L([string]$ln) { $bb = Latin1Bytes ($ln + "`n"); $ms.Write($bb, 0, $bb.Length) }
  Add-L '---'
  Add-L ("id: {0}" -f $Meta.id)
  Add-L ("kind: {0}" -f $Meta.kind)
  Add-L ('title: "' + $Meta.title + '"')
  Add-L ("date: {0}" -f $Meta.date)
  Add-L ('source: "' + $srcEsc + '"')
  Add-L ("commit: {0}" -f $Meta.commit)
  Add-L ('harness: "' + $Meta.harness + '"')
  Add-L ("tags: {0}" -f $tagsYaml)
  Add-L ("supersedes: {0}" -f $supYaml)
  Add-L ("sha256: {0}" -f $Meta.sha)
  if ($quarantine) { Add-L 'quarantined: true' }
  Add-L '---'
  $ms.Write($bodyBytes, 0, $bodyBytes.Length)
  [IO.File]::WriteAllBytes($path, $ms.ToArray())
}

function Sql-Escape([string]$s) { return ($s -replace '''','''''' ) }

function Get-Sqlite3Exe() {
  $cmds = @(Get-Command sqlite3 -CommandType Application -ErrorAction Ignore)
  if ($cmds.Count -lt 1) { return $null }
  return $cmds[0].Path
}

function Test-Fts5 {
  $exe = Get-Sqlite3Exe
  if (-not $exe) { return $false }
  $sql = New-TmpFile
  $out = New-TmpFile
  $sqlBytes = Latin1Bytes 'CREATE VIRTUAL TABLE t USING fts5(x);'
  [IO.File]::WriteAllBytes($sql, $sqlBytes)
  return (Invoke-Sqlite $exe ':memory:' $sql $out '' $false) -eq 0
}

function Invoke-Sqlite([string]$sqliteExe, [string]$db, [string]$sqlFile, [string]$outFile, [string]$separator, [bool]$inheritStderr) {
  if (-not $sqliteExe) { return 1 }
  $init = New-TmpFile
  [IO.File]::WriteAllBytes($init, [byte[]]@())
  $psi = [Diagnostics.ProcessStartInfo]::new($sqliteExe)
  $psi.UseShellExecute = $false
  $psi.RedirectStandardInput = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = -not $inheritStderr
  [void]$psi.ArgumentList.Add('-batch')
  [void]$psi.ArgumentList.Add('-init')
  [void]$psi.ArgumentList.Add($init)
  [void]$psi.ArgumentList.Add('-noheader')
  if ($separator) {
    [void]$psi.ArgumentList.Add('-separator')
    [void]$psi.ArgumentList.Add($separator)
  }
  [void]$psi.ArgumentList.Add($db)
  $p = [Diagnostics.Process]::Start($psi)
  $oms = [IO.MemoryStream]::new()
  $ot = $p.StandardOutput.BaseStream.CopyToAsync($oms)
  $et = $null
  if (-not $inheritStderr) { $et = $p.StandardError.BaseStream.CopyToAsync([IO.Stream]::Null) }
  $sqlBytes = [IO.File]::ReadAllBytes($sqlFile)
  try {
    $p.StandardInput.BaseStream.Write($sqlBytes, 0, $sqlBytes.Length)
  } catch [IO.IOException] {
    # child exited early
  }
  try {
    $p.StandardInput.Close()
  } catch [IO.IOException] {
    # child exited early (broken pipe on flush)
  }
  $ot.Wait()
  if ($null -ne $et) { $et.Wait() }
  $p.WaitForExit()
  $code = $p.ExitCode
  [IO.File]::WriteAllBytes($outFile, $oms.ToArray())
  return $code
}

function Get-RecordBodyForFts([string]$path) {
  $view = ViewBytes ([IO.File]::ReadAllBytes($path))
  $lines = Split-Lf $view
  $c = 0; $bodyLines = [Collections.Generic.List[string]]::new()
  foreach ($line in $lines) {
    $ln = $line
    if ($ln.Length -gt 0 -and [int][char]$ln[$ln.Length - 1] -eq 0x0D) { $ln = $ln.Substring(0, $ln.Length - 1) }
    if ($c -lt 2 -and $ln -ceq '---') { $c++; continue }
    if ($c -ge 2) { [void]$bodyLines.Add($ln) }
  }
  if ($bodyLines.Count -gt 0 -and $bodyLines[$bodyLines.Count - 1].Length -eq 0) {
    $bodyLines.RemoveAt($bodyLines.Count - 1)
  }
  return ($bodyLines -join "`n")
}

function Build-FtsDb([string]$store, [string[]]$files) {
  $db = Join-Path $store '.index/fts.db'
  [IO.Directory]::CreateDirectory((Split-Path $db)) | Out-Null
  if (Test-Path -LiteralPath $db) { Remove-Item -LiteralPath $db -Force }
  $exe = Get-Sqlite3Exe
  if (-not $exe) { return $false }
  if (-not (Test-Fts5)) { return $false }
  $sqlFile = New-TmpFile
  $sw = [IO.StreamWriter]::new($sqlFile, $false, $Script:L1)
  try {
    $sw.Write("CREATE VIRTUAL TABLE records USING fts5(id UNINDEXED, title, tags, body);`n")
    foreach ($f in $files) {
      if ([string]::IsNullOrEmpty($f)) { continue }
      $fm = @{}
      $ref = [ref]$fm
      if (-not (Read-Frontmatter $f $ref)) { continue }
      $id = Sql-Escape $fm.id
      $title = Sql-Escape $fm.title
      $tagsRaw = $fm.tags
      if ($tagsRaw.StartsWith('[', [StringComparison]::Ordinal) -and $tagsRaw.EndsWith(']', [StringComparison]::Ordinal)) {
        $tagsRaw = $tagsRaw.Substring(1, $tagsRaw.Length - 2)
      }
      $tagsRaw = ($tagsRaw -replace ', ', ',')
      $tags = Sql-Escape $tagsRaw
      $body = Sql-Escape (Get-RecordBodyForFts $f)
      $sw.Write("INSERT INTO records(id, title, tags, body) VALUES('$id','$title','$tags','$body');`n")
    }
  } finally {
    $sw.Close()
  }
  $out = New-TmpFile
  $rc = Invoke-Sqlite $exe $db $sqlFile $out '' $true
  return ($rc -eq 0)
}

function Sort-Ordinal([string[]]$arr) {
  $a = @($arr)
  [Array]::Sort($a, [Comparison[string]]{ param($x,$y) [string]::CompareOrdinal($x,$y) })
  return $a
}

function Sort-RowsById([string[]]$arr) {
  $list = [Collections.Generic.List[string]]::new()
  foreach ($item in $arr) { if (-not [string]::IsNullOrEmpty($item)) { [void]$list.Add($item) } }
  $list.Sort([Comparison[string]]{
    param($x,$y)
    $c = [string]::CompareOrdinal($x.Split([char]9)[0], $y.Split([char]9)[0])
    if ($c -ne 0) { return $c }
    return [string]::CompareOrdinal($x, $y)
  })
  return @($list.ToArray())
}

function Run-Index([string]$root, [bool]$quiet) {
  $store = Store-Dir $root
  $files = Get-RecordFiles $store
  $sortRows = [Collections.Generic.List[string]]::new()
  $refMap = [Collections.Generic.List[string]]::new()
  $n = 0
  foreach ($f in $files) {
    if ([string]::IsNullOrEmpty($f)) { continue }
    $fm = @{}
    $ref = [ref]$fm
    if (-not (Read-Frontmatter $f $ref)) {
      Write-Stderr (Latin1Bytes "memory: skipped malformed $(Rel-Path $root $f)`n")
      continue
    }
    $tagsUs = Parse-Brackets $fm.tags
    $supUs = Parse-Brackets $fm.supersedes
    $tagsM = List-ToComma $tagsUs
    $supM = List-ToComma $supUs
    $row = @($fm.id, $fm.kind, $fm.date, $fm.title, $tagsM, (Rel-Path $root $f), $supM) -join $Script:Tab
    [void]$sortRows.Add($row)
    if ($supM.Length -gt 0) {
      $srest = $supM
      while ($true) {
        $idx = $srest.IndexOf([char]',')
        if ($idx -lt 0) { $one = $srest; $srest = '' } else { $one = $srest.Substring(0, $idx); $srest = $srest.Substring($idx + 1) }
        if ($one.Length -gt 0) { [void]$refMap.Add("$one$($Script:Tab)$($fm.id)") }
        if ($srest.Length -eq 0) { break }
      }
    }
    $n++
  }
  $idxDir = Join-Path $store '.index'
  [IO.Directory]::CreateDirectory($idxDir) | Out-Null
  $man = Join-Path $idxDir 'manifest.tsv'
  $sorted = Sort-RowsById $sortRows.ToArray()
  $ms = [IO.MemoryStream]::new()
  $hdr = "id$($Script:Tab)kind$($Script:Tab)date$($Script:Tab)title$($Script:Tab)tags$($Script:Tab)path$($Script:Tab)supersedes$($Script:Tab)superseded_by`n"
  $hb = Latin1Bytes $hdr; $ms.Write($hb, 0, $hb.Length)
  foreach ($line in $sorted) {
    $rid = $line.Split([char]9)[0]
    $sbs = [Collections.Generic.List[string]]::new()
    foreach ($rm in $refMap) {
      $p = $rm.Split([char]9)
      if ([string]::Equals($p[0], $rid, [StringComparison]::Ordinal)) { [void]$sbs.Add($p[1]) }
    }
    $sb = (Sort-Ordinal @($sbs.ToArray())) -join ','
    $ln = $line + $Script:Tab + $sb + "`n"
    $lb = Latin1Bytes $ln; $ms.Write($lb, 0, $lb.Length)
  }
  [IO.File]::WriteAllBytes($man, $ms.ToArray())
  $stampPath = Join-Path $idxDir 'stamp'
  $stampBytes = Latin1Bytes "$n`n"
  [IO.File]::WriteAllBytes($stampPath, $stampBytes)
  $ftsYes = $false
  if (Test-Fts5) {
    if (Build-FtsDb $store $files) { $ftsYes = $true }
    else {
      $db = Join-Path $idxDir 'fts.db'
      if (Test-Path -LiteralPath $db) { Remove-Item -LiteralPath $db -Force }
    }
  } else {
    $db = Join-Path $idxDir 'fts.db'
    if (Test-Path -LiteralPath $db) { Remove-Item -LiteralPath $db -Force }
  }
  if (-not $quiet) {
    $ftsTxt = if ($ftsYes) { 'yes' } else { 'no' }
    Write-StdoutUtf8("memory: indexed $n records · fts: $ftsTxt`n")
  }
}

function Count-ValidRecords([string]$store) { $recs = Get-RecordFiles $store; return $recs.Count }

function Test-IndexStale([string]$root) {
  $store = Store-Dir $root
  $man = Join-Path $store '.index/manifest.tsv'
  $stamp = Join-Path $store '.index/stamp'
  if (-not (Test-Path -LiteralPath $man) -or -not (Test-Path -LiteralPath $stamp)) { return $true }
  $cnt = Count-ValidRecords $store
  $stampN = (ViewBytes ([IO.File]::ReadAllBytes($stamp))).Trim()
  if ("$cnt" -ne $stampN) { return $true }
  $manTime = [IO.File]::GetLastWriteTimeUtc($man)
  foreach ($f in (Get-RecordFiles $store)) {
    if ((Get-RecordMtimeUtc $f) -gt $manTime) { return $true }
  }
  return $false
}

function Grep-Score([string]$title, [string]$tagsUs, [string]$recPath) {
  $score = 0
  $titleF = Fold-Ascii $title
  foreach ($term in $Script:SearchTerms) {
    $termF = Fold-Ascii $term
    $metaHit = $false
    if ($titleF.Contains($termF)) { $metaHit = $true }
    if (-not $metaHit -and $tagsUs.Length -gt 0) {
      $trest = $tagsUs
      while ($true) {
        $idx = $trest.IndexOf($Script:US)
        if ($idx -lt 0) { $t = $trest; $trest = '' } else { $t = $trest.Substring(0, $idx); $trest = $trest.Substring($idx + 1) }
        if ($t.Length -gt 0 -and (Fold-Ascii $t).Contains($termF)) { $metaHit = $true; break }
        if ($trest.Length -eq 0) { break }
      }
    }
    if ($metaHit) { $score += 3 }
    $view = ViewBytes ([IO.File]::ReadAllBytes($recPath))
    $lines = Split-Lf $view
    $c = 0; $hits = 0
    foreach ($line in $lines) {
      $ln = $line
      if ($ln.Length -gt 0 -and [int][char]$ln[$ln.Length - 1] -eq 0x0D) { $ln = $ln.Substring(0, $ln.Length - 1) }
      if ($c -lt 2 -and $ln -ceq '---') { $c++; continue }
      if ($c -ge 2) {
        if ((Fold-Ascii $ln).Contains($termF)) { $hits++ }
      }
    }
    $score += $hits
  }
  return $score
}

function Need-Val([string]$flag, [string[]]$ArgList, [int]$i) {
  if ($i + 1 -ge $ArgList.Count) { Die 2 "flag '$flag' needs a value" }
  $nxt = View ([string]$ArgList[$i + 1])
  if ($nxt.StartsWith('--', [StringComparison]::Ordinal)) { Die 2 "flag '$flag' needs a value" }
}

function Invoke-Add([string[]]$cmdArgs) {
  $root = ''; $kind = ''; $title = ''; $bodyPath = ''; $source = ''; $tagsRaw = ''; $supRaw = ''; $harness = ''
  $seen = @{ root=0; kind=0; title=0; body=0; source=0; tags=0; sup=0; harness=0 }
  $i = 0
  while ($i -lt $cmdArgs.Count) {
    $a = View ([string]$cmdArgs[$i])
    switch -CaseSensitive ($a) {
      '--root' { Need-Val '--root' $cmdArgs $i; if ($seen.root) { Die 2 "repeated flag '--root'" }; $seen.root=1; $root = [string]$cmdArgs[$i+1]; $i += 2; continue }
      '--kind' { Need-Val '--kind' $cmdArgs $i; if ($seen.kind) { Die 2 "repeated flag '--kind'" }; $seen.kind=1; $kind = View ([string]$cmdArgs[$i+1]); $i += 2; continue }
      '--title' { Need-Val '--title' $cmdArgs $i; if ($seen.title) { Die 2 "repeated flag '--title'" }; $seen.title=1; $title = View ([string]$cmdArgs[$i+1]); $i += 2; continue }
      '--body' { Need-Val '--body' $cmdArgs $i; if ($seen.body) { Die 2 "repeated flag '--body'" }; $seen.body=1; $bodyPath = [string]$cmdArgs[$i+1]; $i += 2; continue }
      '--source' { Need-Val '--source' $cmdArgs $i; if ($seen.source) { Die 2 "repeated flag '--source'" }; $seen.source=1; $source = View ([string]$cmdArgs[$i+1]); $i += 2; continue }
      '--tags' { Need-Val '--tags' $cmdArgs $i; if ($seen.tags) { Die 2 "repeated flag '--tags'" }; $seen.tags=1; $tagsRaw = View ([string]$cmdArgs[$i+1]); $i += 2; continue }
      '--supersedes' { Need-Val '--supersedes' $cmdArgs $i; if ($seen.sup) { Die 2 "repeated flag '--supersedes'" }; $seen.sup=1; $supRaw = View ([string]$cmdArgs[$i+1]); $i += 2; continue }
      '--harness' { Need-Val '--harness' $cmdArgs $i; if ($seen.harness) { Die 2 "repeated flag '--harness'" }; $seen.harness=1; $harness = View ([string]$cmdArgs[$i+1]); $i += 2; continue }
      default {
        if ($a.StartsWith('--', [StringComparison]::Ordinal)) { Die 2 "unknown flag '$a'" }
        Die 2 "unexpected argument '$a'"
      }
    }
  }
  if (-not $seen.kind) { Die 2 "'add' requires --kind" }
  if (-not $seen.title) { Die 2 "'add' requires --title" }
  if (-not $seen.body) { Die 2 "'add' requires --body" }
  if (-not (Test-Kind $kind)) { Die 2 'invalid --kind' }
  if ($seen.harness -and -not (Test-Harness $harness)) { Die 2 'invalid --harness' }
  if (Has-ControlBytes $source) { Die 2 'invalid --source' }
  try { $tagsItems = Normalize-TagsList $tagsRaw } catch { Die 2 'invalid --tags' }
  try { $supItems = Parse-List $supRaw 'id' } catch { Die 2 'invalid --supersedes' }
  $memNow = [Environment]::GetEnvironmentVariable('MEMORY_NOW')
  if ($memNow) {
    $mn = View $memNow
    if (-not (Test-Re $mn $Script:ReMemNow)) { Die 2 'invalid MEMORY_NOW' }
  }
  if (-not $seen.root) { $root = Get-DefaultRoot }
  $root = Resolve-Root $root
  if (-not (Test-File $bodyPath)) { Die 4 "body file not found: $(View $bodyPath)" }
  $normBody = New-TmpFile
  $bodyTmp = Prepare-BodyFile $bodyPath
  [IO.File]::Copy($bodyTmp, $normBody, $true)
  $redBody = New-TmpFile
  Memory-RedactFile $normBody $redBody $true
  $redBodyN = $Script:RedactN
  $redBodyC = $Script:RedactClasses
  $titleIn = New-TmpFile
  $titleOut = New-TmpFile
  [IO.File]::WriteAllBytes($titleIn, (Latin1Bytes $title))
  Memory-RedactFile $titleIn $titleOut $false
  $title = ViewBytes ([IO.File]::ReadAllBytes($titleOut))
  $Script:RedactN = $redBodyN + $Script:RedactN
  Merge-RedactClasses $redBodyC $Script:RedactClasses
  $tlen = $title.Length
  if ($tlen -lt 1 -or $tlen -gt 120) { Die 2 'invalid --title' }
  if ($title.Contains('"') -or $title.Contains('\') -or (Has-ControlBytes $title)) { Die 2 'invalid --title' }
  $bodyBytes = [IO.File]::ReadAllBytes($redBody)
  if ($bodyBytes.Length -lt 1 -or $bodyBytes.Length -gt 4096) { Die 2 'invalid body' }
  $sha = Get-Sha256Hex $bodyBytes
  if ($memNow) { $now = View $memNow } else { $now = Utc-NowPrefix }
  $id = "$now-$($sha.Substring(0,8))"
  $date = "{0}-{1}-{2}" -f $id.Substring(0,4), $id.Substring(4,2), $id.Substring(6,2)
  $commit = Get-CommitShort $root
  $store = Store-Dir $root
  foreach ($sid in $supItems) {
    if (-not (Test-File (Id-ToRecord $store $sid))) { Die 4 "supersedes id not found: $sid" }
  }
  $dupId = ''
  foreach ($f in (Get-DedupeFiles $store)) {
    if ([string]::IsNullOrEmpty($f)) { continue }
    $fm = @{}; $ref = [ref]$fm
    if (-not (Read-Frontmatter $f $ref)) {
      Write-Stderr (Latin1Bytes "memory: skipped malformed $(Rel-Path $root $f)`n")
      continue
    }
    if ([string]::Equals($fm.sha256, $sha, [StringComparison]::Ordinal)) {
      if ([string]::IsNullOrEmpty($dupId) -or [string]::CompareOrdinal($fm.id, $dupId) -lt 0) { $dupId = $fm.id }
    }
  }
  if ($dupId) {
    $recP = Id-ToRecord $store $dupId
    if (Test-File $recP) { $rel = Rel-Path $root $recP } else { $rel = Rel-Path $root (Id-ToQuarantine $store $dupId) }
    Print-AddNotices
    Write-Stdout (Latin1Bytes "memory: duplicate $dupId $rel`n")
    exit 0
  }
  $meta = @{
    id=$id; kind=$kind; title=$title; date=$date; source=$source; commit=$commit; harness=$harness
    tagsItems=$tagsItems; supItems=$supItems; sha=$sha
  }
  if (Test-Admission $title $redBody) {
    $path = Id-ToQuarantine $store $id
    $rel = Rel-Path $root $path
    if (Test-File $path) { Die 4 "record exists $rel" }
    Write-RecordFile $path $meta $bodyBytes $true
    Print-AddNotices
    Write-Stdout (Latin1Bytes "memory: quarantined $id $rel`n")
    exit 5
  }
  $path = Id-ToRecord $store $id
  $rel = Rel-Path $root $path
  if (Test-File $path) { Die 4 "record exists $rel" }
  Write-RecordFile $path $meta $bodyBytes $false
  Print-AddNotices
  Write-Stdout (Latin1Bytes "memory: added $id $rel`n")
  exit 0
}

function Invoke-Redact([string[]]$cmdArgs) {
  $root = ''; $seenRoot = 0
  $i = 0
  while ($i -lt $cmdArgs.Count) {
    $a = View ([string]$cmdArgs[$i])
    if ($a -ceq '--root') {
      Need-Val '--root' $cmdArgs $i
      if ($seenRoot) { Die 2 "repeated flag '--root'" }
      $seenRoot = 1; $root = [string]$cmdArgs[$i+1]; $i += 2; continue
    }
    if ($a.StartsWith('--', [StringComparison]::Ordinal)) { Die 2 "unknown flag '$a'" }
    Die 2 "unexpected argument '$a'"
  }
  if (-not $seenRoot) { $root = Get-DefaultRoot }
  $root = Resolve-Root $root
  $in = New-TmpFile
  $out = New-TmpFile
  $ms = [IO.MemoryStream]::new()
  $stdin = [Console]::OpenStandardInput()
  $buf = [byte[]]::new(8192)
  while (($n = $stdin.Read($buf, 0, $buf.Length)) -gt 0) { $ms.Write($buf, 0, $n) }
  [IO.File]::WriteAllBytes($in, $ms.ToArray())
  Memory-RedactFile $in $out $true
  Write-Stdout ([IO.File]::ReadAllBytes($out))
  Print-RedactNotice
  exit 0
}

function Invoke-IndexCmd([string[]]$cmdArgs) {
  $root = ''; $seenRoot = 0
  $i = 0
  while ($i -lt $cmdArgs.Count) {
    $a = View ([string]$cmdArgs[$i])
    if ($a -ceq '--root') {
      Need-Val '--root' $cmdArgs $i
      if ($seenRoot) { Die 2 "repeated flag '--root'" }
      $seenRoot = 1; $root = [string]$cmdArgs[$i+1]; $i += 2; continue
    }
    if ($a.StartsWith('--', [StringComparison]::Ordinal)) { Die 2 "unknown flag '$a'" }
    Die 2 "unexpected argument '$a'"
  }
  if (-not $seenRoot) { $root = Get-DefaultRoot }
  $root = Resolve-Root $root
  Run-Index $root $false
  exit 0
}

function Invoke-Show([string[]]$cmdArgs) {
  $root = ''; $id = ''; $seenRoot = 0
  $i = 0
  while ($i -lt $cmdArgs.Count) {
    $a = View ([string]$cmdArgs[$i])
    if ($a -ceq '--root') {
      Need-Val '--root' $cmdArgs $i
      if ($seenRoot) { Die 2 "repeated flag '--root'" }
      $seenRoot = 1; $root = [string]$cmdArgs[$i+1]; $i += 2; continue
    }
    if ($a.StartsWith('--', [StringComparison]::Ordinal)) { Die 2 "unknown flag '$a'" }
    if ($id) { Die 2 "unexpected argument '$a'" }
    $id = $a; $i++
  }
  if (-not $id) { Die 2 "'show' requires id" }
  if (-not (Test-Re $id $Script:ReId)) { Die 2 'invalid id' }
  if (-not $seenRoot) { $root = Get-DefaultRoot }
  $root = Resolve-Root $root
  $store = Store-Dir $root
  $rec = Id-ToRecord $store $id
  $q = Id-ToQuarantine $store $id
  if (Test-File $rec) { Write-Stdout ([IO.File]::ReadAllBytes($rec)); exit 0 }
  if (Test-File $q) { Write-Stdout ([IO.File]::ReadAllBytes($q)); exit 0 }
  Die 4 "record not found: $id"
}

function Invoke-Search([string[]]$cmdArgs) {
  $root = ''; $kindRaw = ''; $limit = '10'; $engine = 'grep'; $includeSup = $false
  $seen = @{ root=0; kind=0; limit=0; engine=0; include=0 }
  $Script:SearchTerms = @()
  $parsingFlags = $true
  $i = 0
  while ($i -lt $cmdArgs.Count) {
    $a = View ([string]$cmdArgs[$i])
    if ($parsingFlags) {
      if ($a -ceq '--') { $parsingFlags = $false; $i++; continue }
      switch -CaseSensitive ($a) {
        '--root' { Need-Val '--root' $cmdArgs $i; if ($seen.root) { Die 2 "repeated flag '--root'" }; $seen.root=1; $root = [string]$cmdArgs[$i+1]; $i += 2; continue }
        '--kind' { Need-Val '--kind' $cmdArgs $i; if ($seen.kind) { Die 2 "repeated flag '--kind'" }; $seen.kind=1; $kindRaw = View ([string]$cmdArgs[$i+1]); $i += 2; continue }
        '--limit' { Need-Val '--limit' $cmdArgs $i; if ($seen.limit) { Die 2 "repeated flag '--limit'" }; $seen.limit=1; $limit = View ([string]$cmdArgs[$i+1]); $i += 2; continue }
        '--engine' { Need-Val '--engine' $cmdArgs $i; if ($seen.engine) { Die 2 "repeated flag '--engine'" }; $seen.engine=1; $engine = View ([string]$cmdArgs[$i+1]); $i += 2; continue }
        '--include-superseded' { if ($seen.include) { Die 2 "repeated flag '--include-superseded'" }; $seen.include=1; $includeSup = $true; $i++; continue }
        default {
          if ($a.StartsWith('--', [StringComparison]::Ordinal)) { Die 2 "unknown flag '$a'" }
          $Script:SearchTerms += $a; $i++; continue
        }
      }
    } else {
      $Script:SearchTerms += $a; $i++
    }
  }
  if ($Script:SearchTerms.Count -eq 0) { Die 2 'search requires at least one term' }
  foreach ($t in $Script:SearchTerms) { if ([string]::IsNullOrEmpty($t)) { Die 2 'empty search term' } }
  if (-not (Test-Re $limit $Script:ReLimit)) { Die 2 'invalid --limit' }
  if ($limit.Length -gt 3) { Die 2 'invalid --limit' }
  $limNum = [int]::Parse($limit, [cultureinfo]::InvariantCulture)
  if ($limNum -gt 100) { Die 2 'invalid --limit' }
  if ($engine -cne 'grep' -and $engine -cne 'fts') { Die 2 'invalid --engine' }
  $kindFilter = @()
  if ($seen.kind) {
    try { $kindFilter = Parse-List $kindRaw 'kind' } catch { Die 2 'invalid --kind' }
    if ($kindFilter.Count -eq 0) { Die 2 'invalid --kind' }
  }
  if (-not $seen.root) { $root = Get-DefaultRoot }
  $root = Resolve-Root $root
  if (Test-IndexStale $root) { Run-Index $root $true }
  $store = Store-Dir $root
  $man = Join-Path $store '.index/manifest.tsv'
  if (-not (Test-Path -LiteralPath $man)) { Run-Index $root $true }
  if ($engine -ceq 'fts') {
    if (-not (Test-Fts5)) { Die 4 'fts engine unavailable' }
    if (-not (Test-File (Join-Path $store '.index/fts.db'))) { Die 4 'fts engine unavailable' }
  }
  $manView = ViewBytes ([IO.File]::ReadAllBytes($man))
  $mLines = Split-Lf $manView
  $cand = [Collections.Generic.List[string]]::new()
  for ($mi = 1; $mi -lt $mLines.Count; $mi++) {
    $line = $mLines[$mi]
    if ($line.Length -eq 0) { continue }
    if ($line.Length -gt 0 -and [int][char]$line[$line.Length - 1] -eq 0x0D) { $line = $line.Substring(0, $line.Length - 1) }
    $parts = $line.Split([char]9, 8)
    if ($parts.Count -lt 8) { continue }
    $rid = $parts[0]; $rkind = $parts[1]; $rdate = $parts[2]; $rtitle = $parts[3]; $rtags = $parts[4]; $rpath = $parts[5]; $rsup = $parts[6]; $rsby = $parts[7]
    if (-not $includeSup -and $rsby.Length -gt 0) { continue }
    if ($kindFilter.Count -gt 0 -and ([Array]::IndexOf($kindFilter, $rkind) -lt 0)) { continue }
    $f = Join-Path $root $rpath
    $fm = @{}; $ref = [ref]$fm
    if (-not (Read-Frontmatter $f $ref)) { continue }
    $tagUs = Parse-Brackets $fm.tags
    $score = Grep-Score $fm.title $tagUs $f
    if ($score -le 0) { continue }
    [void]$cand.Add("$rid$($Script:Tab)$rkind$($Script:Tab)$rdate$($Script:Tab)$score$($Script:Tab)$rtitle$($Script:Tab)$rpath$($Script:Tab)$score")
  }
  if ($cand.Count -eq 0) { Die 0 '0 results' }
  $outLines = [Collections.Generic.List[string]]::new()
  if ($engine -ceq 'grep') {
    $arr = $cand.ToArray()
    [Array]::Sort($arr, [Comparison[string]]{
      param($x,$y)
      $px = $x.Split([char]9); $py = $y.Split([char]9)
      $sc = [int64]$py[3] - [int64]$px[3]
      if ($sc -ne 0) { return [int][math]::Sign($sc) }
      $c = [string]::CompareOrdinal($py[0], $px[0])
      if ($c -ne 0) { return $c }
      return [string]::CompareOrdinal($x, $y)
    })
    $take = [Math]::Min($limNum, $arr.Length)
    for ($ti = 0; $ti -lt $take; $ti++) {
      $p = $arr[$ti].Split([char]9)
      [void]$outLines.Add("$($p[0])$($Script:Tab)$($p[1])$($Script:Tab)$($p[2])$($Script:Tab)$($p[3])$($Script:Tab)$($p[4])$($Script:Tab)$($p[5])")
    }
  } else {
    $matchParts = [Collections.Generic.List[string]]::new()
    foreach ($term in $Script:SearchTerms) {
      $esc = $term -replace '"','""'
      [void]$matchParts.Add('"' + $esc + '"')
    }
    $expr = $matchParts -join ' OR '
    $sqlText = "SELECT id, bm25(records) FROM records WHERE records MATCH '$(Sql-Escape $expr)';`n"
    $sqlFile = New-TmpFile
    $sqlBytes = Latin1Bytes $sqlText
    [IO.File]::WriteAllBytes($sqlFile, $sqlBytes)
    $qfile = New-TmpFile
    $sqliteExe = Get-Sqlite3Exe
    $qrc = Invoke-Sqlite $sqliteExe (Join-Path $store '.index/fts.db') $sqlFile $qfile ([string]$Script:Tab) $false
    if ($qrc -ne 0) { [IO.File]::WriteAllBytes($qfile, [byte[]]@()) }
    $qview = ViewBytes ([IO.File]::ReadAllBytes($qfile))
    $qSplit = Split-Lf $qview
    $qLines = @($qSplit | Where-Object { $_.Length -gt 0 })
    $ranked = [Collections.Generic.List[object]]::new()
    foreach ($line in $cand) {
      $cid = $line.Split([char]9)[0]
      $bm = $null
      foreach ($ql in $qLines) {
        $qp = $ql.Split([char]9)
        if ([string]::Equals($qp[0], $cid, [StringComparison]::Ordinal)) { $bm = $qp[1]; break }
      }
      if ($null -ne $bm) {
        [void]$ranked.Add([pscustomobject]@{ pri=0; bmStr=$bm; bm=[double]::Parse($bm, [cultureinfo]::InvariantCulture); line=$line })
      } else {
        [void]$ranked.Add([pscustomobject]@{ pri=1; bmStr='0'; bm=0.0; line=$line })
      }
    }
    $rankArr = $ranked.ToArray()
    [Array]::Sort($rankArr, [Comparison[object]]{
      param($a,$b)
      if ($a.pri -ne $b.pri) { return $a.pri - $b.pri }
      if ($a.bm -lt $b.bm) { return -1 }
      if ($a.bm -gt $b.bm) { return 1 }
      $c = [string]::CompareOrdinal(($b.line.Split([char]9)[0]), ($a.line.Split([char]9)[0]))
      if ($c -ne 0) { return $c }
      $rowA = "$($a.pri)$($Script:Tab)$($a.bmStr)$($Script:Tab)$($a.line)"
      $rowB = "$($b.pri)$($Script:Tab)$($b.bmStr)$($Script:Tab)$($b.line)"
      return [string]::CompareOrdinal($rowA, $rowB)
    })
    $take = [Math]::Min($limNum, $rankArr.Length)
    for ($ti = 0; $ti -lt $take; $ti++) {
      $p = $rankArr[$ti].line.Split([char]9)
      [void]$outLines.Add("$($p[0])$($Script:Tab)$($p[1])$($Script:Tab)$($p[2])$($Script:Tab)$($p[3])$($Script:Tab)$($p[4])$($Script:Tab)$($p[5])")
    }
  }
  if ($outLines.Count -eq 0) { Die 0 '0 results' }
  $blob = (($outLines | ForEach-Object { $_ + "`n" }) -join '')
  Write-Stdout (Latin1Bytes $blob)
  exit 0
}

try {
  if ($args.Count -eq 0) { Show-UsageStderr; exit 2 }
  $sub = View ([string]$args[0])
  if ($sub -ceq '--help') { Show-UsageStdout; exit 0 }
  if ([Array]::IndexOf(@('add', 'index', 'search', 'show', 'redact', 'check', 'rm', 'capture', 'backfill'), $sub) -lt 0) {
    Show-UsageStderr
    Die 2 "unknown subcommand '$sub'"
  }
  $rest = @()
  if ($args.Count -gt 1) { $rest = @($args[1..($args.Count - 1)]) }
  if ($rest.Count -gt 0 -and (View ([string]$rest[0])) -ceq '--help') { Show-UsageStdout; exit 0 }
  switch -CaseSensitive ($sub) {
    'add' { Invoke-Add $rest }
    'index' { Invoke-IndexCmd $rest }
    'search' { Invoke-Search $rest }
    'show' { Invoke-Show $rest }
    'redact' { Invoke-Redact $rest }
    'check' { Invoke-BashOnlySub 'check' }
    'rm' { Invoke-BashOnlySub 'rm' }
    'capture' { Invoke-BashOnlySub 'capture' }
    'backfill' { Invoke-BashOnlySub 'backfill' }
  }
} finally {
  foreach ($p in $Script:TmpPaths) {
    if (Test-Path -LiteralPath $p) {
      if (Test-Path -LiteralPath $p -PathType Container) { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue }
      else { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
    }
  }
}
