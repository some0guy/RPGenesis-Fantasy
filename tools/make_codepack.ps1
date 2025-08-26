param(
  [Parameter(Mandatory = $false)][string]$RepoRoot = (Get-Location).Path,
  [Parameter(Mandatory = $false)][string]$OutFile  = "code_pack\code_pack.txt",

  # Set to 0 for "no limit". Any positive value is KB limit per file.
  [int]$MaxFileSizeKB = 0,

  # Include .git internals? Set $true to include literally everything.
  [bool]$IncludeGit = $true
)

$ErrorActionPreference = "Stop"

# Resolve output path and ensure folder exists
$OutPath = Join-Path $RepoRoot $OutFile
$OutDir  = Split-Path -Parent $OutPath
if (-not (Test-Path -LiteralPath $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

# Header
"=== RPGenesis FULL Code Pack ===" | Set-Content -Path $OutPath -Encoding UTF8
"Generated : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Add-Content -Path $OutPath -Encoding UTF8
"Root      : $RepoRoot" | Add-Content -Path $OutPath -Encoding UTF8
"IncludeGit: $IncludeGit" | Add-Content -Path $OutPath -Encoding UTF8
"MaxFileKB : $MaxFileSizeKB (0 means unlimited)" | Add-Content -Path $OutPath -Encoding UTF8
"" | Add-Content -Path $OutPath -Encoding UTF8

function Test-IsBinary([string]$Path) {
  try {
    $fs = [System.IO.File]::OpenRead($Path)
    try {
      $buf = New-Object byte[] ( [Math]::Min(4096, [int]$fs.Length) )
      $read = $fs.Read($buf, 0, $buf.Length)
      if ($read -eq 0) { return $false }
      # Null byte check
      for ($i=0; $i -lt $read; $i++) { if ($buf[$i] -eq 0) { return $true } }
      # Heuristic: printable ratio
      $texty = 0
      for ($i=0; $i -lt $read; $i++) {
        $b = $buf[$i]
        if (($b -eq 9) -or ($b -eq 10) -or ($b -eq 13) -or ($b -ge 32 -and $b -le 126)) { $texty++ }
      }
      return ( ($texty / [double]$read) -lt 0.8 )
    } finally { $fs.Dispose() }
  } catch { return $false }
}

$maxBytes = $MaxFileSizeKB * 1KB

Write-Host "[INFO] Scanning directories…"
$dirs = Get-ChildItem -LiteralPath $RepoRoot -Recurse -Force -Directory | Sort-Object FullName
$dirCount = 0
foreach ($d in $dirs) {
  $rel = $d.FullName.Substring($RepoRoot.Length).TrimStart('\','/')
  # Optionally skip .git
  if (-not $IncludeGit) {
    $first = ($rel -split "[\\/]")[0]
    if ($first -eq ".git") { continue }
  }
  Add-Content -Path $OutPath -Value ("==== DIR: {0} ====" -f $rel) -Encoding UTF8
  $dirCount++
}

Write-Host "[INFO] Scanning files…"
$files = Get-ChildItem -LiteralPath $RepoRoot -Recurse -Force -File | Sort-Object FullName
$fileCount = 0
$binCount  = 0

foreach ($f in $files) {
  $rel = $f.FullName.Substring($RepoRoot.Length).TrimStart('\','/')

  # Skip the output file itself
  if ([System.IO.Path]::GetFullPath($f.FullName) -ieq [System.IO.Path]::GetFullPath($OutPath)) { continue }

  # Optionally skip .git internals
  if (-not $IncludeGit) {
    $first = ($rel -split "[\\/]")[0]
    if ($first -eq ".git") { continue }
  }

  # Size cap (only if a positive limit was set)
  if ( ($MaxFileSizeKB -gt 0) -and ($f.Length -gt $maxBytes) ) {
    Write-Host ("[SKIP] {0} (too large: {1:N0} KB > {2:N0} KB)" -f $rel, ($f.Length/1KB), $MaxFileSizeKB)
    Add-Content -Path $OutPath -Value ("==== FILE: {0} ====" -f $rel) -Encoding UTF8
    Add-Content -Path $OutPath -Value ("[SKIPPED: file too large ({0:N0} KB > {1:N0} KB)]" -f ($f.Length/1KB), $MaxFileSizeKB) -Encoding UTF8
    Add-Content -Path $OutPath -Value "" -Encoding UTF8
    continue
  }

  $isBinary = Test-IsBinary $f.FullName
  if ($isBinary) {
    Write-Host ("[ADD] {0} (binary->base64)" -f $rel)
    Add-Content -Path $OutPath -Value ("==== FILE (binary, base64): {0} ====" -f $rel) -Encoding UTF8
    try {
      $b64 = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($f.FullName))
      Add-Content -Path $OutPath -Value $b64 -Encoding UTF8
    } catch {
      Add-Content -Path $OutPath -Value ("[ERROR reading {0}: {1}]" -f $rel, $_) -Encoding UTF8
    }
    Add-Content -Path $OutPath -Value "" -Encoding UTF8
    $binCount++
  } else {
    Write-Host ("[ADD] {0}" -f $rel)
    Add-Content -Path $OutPath -Value ("==== FILE: {0} ====" -f $rel) -Encoding UTF8
    try {
      Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8 | Add-Content -Path $OutPath -Encoding UTF8
    } catch {
      try {
        $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
        $text  = [System.Text.Encoding]::UTF8.GetString($bytes)
        Add-Content -Path $OutPath -Value $text -Encoding UTF8
      } catch {
        Add-Content -Path $OutPath -Value ("[ERROR reading {0}: {1}]" -f $rel, $_) -Encoding UTF8
      }
    }
    Add-Content -Path $OutPath -Value "" -Encoding UTF8
  }

  $fileCount++
}

Add-Content -Path $OutPath -Value ("---`nTotal directories: {0}`nTotal files: {1}`nBinary files (base64): {2}" -f $dirCount, $fileCount, $binCount) -Encoding UTF8
Write-Host ("[OK] Code pack created: {0} (dirs: {1}, files: {2}, binary: {3})" -f $OutPath, $dirCount, $fileCount, $binCount)
