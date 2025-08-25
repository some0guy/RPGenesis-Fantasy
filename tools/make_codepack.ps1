param(
  [string]$OutName = "RPGenesis-Fantasy.codepack.txt",
  [string]$Root    = (git rev-parse --show-toplevel).Trim()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$exts = @(".py",".json",".md",".txt",".ini",".cfg",".yaml",".yml",".toml",".csv")
$excludeDirs = @(".git",".venv","venv","env","__pycache__",".mypy_cache",".pytest_cache","build","dist",".idea",".vscode")

$files = Get-ChildItem -Path $Root -Recurse -File | Where-Object {
  $rel = $_.FullName.Substring($Root.Length).TrimStart('\','/')
  -not ($excludeDirs | Where-Object { $rel -like "$_/*" -or $rel -like "$_\*" }) -and
  ($exts -contains $_.Extension.ToLower())
}

$outPath = Join-Path $Root $OutName
if (Test-Path $outPath) { Remove-Item $outPath -Force }

"==== RPGenesis-Fantasy CODEPACK ====" | Out-File -FilePath $outPath -Encoding UTF8
"Generated: $(Get-Date -Format o)"     | Out-File -FilePath $outPath -Append -Encoding UTF8
"Repo root: $Root"                      | Out-File -FilePath $outPath -Append -Encoding UTF8
""                                      | Out-File -FilePath $outPath -Append -Encoding UTF8

foreach ($f in $files | Sort-Object FullName) {
  $rel = $f.FullName.Substring($Root.Length).TrimStart('\','/')
  "-----8<----- FILE: $rel -----" | Out-File -FilePath $outPath -Append -Encoding UTF8
  try {
    Get-Content -Raw -Encoding UTF8 $f.FullName | Out-File -FilePath $outPath -Append -Encoding UTF8
  } catch {
    Get-Content -Raw $f.FullName | Out-File -FilePath $outPath -Append
  }
  "`n" | Out-File -FilePath $outPath -Append -Encoding UTF8
}
"===== END OF CODEPACK =====" | Out-File -FilePath $outPath -Append -Encoding UTF8

Write-Host "Wrote codepack: $outPath"
