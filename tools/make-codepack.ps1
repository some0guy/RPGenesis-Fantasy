param(
  [string]$OutName = "RPGenesis-Fantasy.codepack.txt",
  [string]$Root    = (git rev-parse --show-toplevel).Trim()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Choose which files to include in the readable bundle
$patterns = @("*.py","*.json","*.md","*.txt","*.ini","*.cfg","*.yaml","*.yml")
$excludeDirs = @(".git",".venv","venv","__pycache__",".mypy_cache",".pytest_cache","build","dist")

$all = Get-ChildItem -Path $Root -Recurse -File |
  Where-Object {
    $rel = Resolve-Path $_.FullName -Relative
    -not ($excludeDirs | ForEach-Object { $rel -like ".\$_\*" }) -and
    ($patterns | Where-Object { $_ -as [string]; $_ }) -and
    ($patterns | ForEach-Object { $_ }) | Out-Null
  }

# Better matching: filter by extension separately
$all = Get-ChildItem -Path $Root -Recurse -File | Where-Object {
  $rel = $_.FullName.Substring($Root.Length).TrimStart('\','/')
  -not ($excludeDirs | Where-Object { $rel -like "$_/*" -or $rel -like "$_\*" }) -and
  (".py",".json",".md",".txt",".ini",".cfg",".yaml",".yml") -contains $_.Extension.ToLower()
}

$outPath = Join-Path $Root $OutName
if (Test-Path $outPath) { Remove-Item $outPath -Force }

# Write banner + each file with clear delimiter
"==== RPGenesis-Fantasy CODEPACK ====" | Out-File -FilePath $outPath -Encoding UTF8
"Generated: $(Get-Date -Format o)"     | Out-File -FilePath $outPath -Append -Encoding UTF8
"Repo root: $Root"                      | Out-File -FilePath $outPath -Append -Encoding UTF8
""                                      | Out-File -FilePath $outPath -Append -Encoding UTF8

foreach ($f in $all | Sort-Object FullName) {
  $rel = $f.FullName.Substring($Root.Length).TrimStart('\','/')
  "-----8<----- FILE: $rel -----" | Out-File -FilePath $outPath -Append -Encoding UTF8
  try {
    Get-Content -Raw -Encoding UTF8 $f.FullName | Out-File -FilePath $outPath -Append -Encoding UTF8
  } catch {
    # If a file isn’t UTF-8, try default encoding
    Get-Content -Raw $f.FullName | Out-File -FilePath $outPath -Append
  }
  "`n" | Out-File -FilePath $outPath -Append -Encoding UTF8
}
"===== END OF CODEPACK =====" | Out-File -FilePath $outPath -Append -Encoding UTF8
Write-Host "Wrote $outPath"
