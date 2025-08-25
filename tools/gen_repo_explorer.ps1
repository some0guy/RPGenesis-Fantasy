param(
  [string]$CodepackName = "RPGenesis-Fantasy.codepack.txt",
  [string]$ExplorerName = "repo_explorer_embedded.html",
  [string]$TreeName     = "repo_tree.txt",
  [switch]$MakeTree     = $true,
  [string]$Title        = "RPGenesis Repo Explorer"
)

$ErrorActionPreference = "Stop"

function Ensure-Repo {
  try { git rev-parse --is-inside-work-tree | Out-Null }
  catch { throw "Not a git repo. Run from inside your repo root." }
  (git rev-parse --show-toplevel).Trim()
}

function Build-Codepack([string]$root, [string]$outPath) {
  $script = Join-Path $root "tools\make_codepack.ps1"
  if (-not (Test-Path $script)) { throw "Missing tools\make_codepack.ps1 in repo." }
  & pwsh -ExecutionPolicy Bypass -File $script -OutName (Split-Path $outPath -Leaf) -Root $root
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $outPath)) { throw "Codepack build failed." }
}

function Build-Tree([string]$root, [string]$treePath) {
  Push-Location $root
  try {
    if (Test-Path $treePath) { Remove-Item $treePath -Force }
    cmd /c "tree /F > `"$treePath`"" | Out-Null
  } finally { Pop-Location }
}

function Build-Explorer([string]$root, [string]$codepackPath, [string]$outHtml, [string]$title) {
  $script = Join-Path $root "tools\make_repo_explorer.ps1"
  if (-not (Test-Path $script)) { throw "Missing tools\make_repo_explorer.ps1 in repo." }
  & pwsh -ExecutionPolicy Bypass -File $script -CodepackPath $codepackPath -OutHtml $outHtml -Title $title
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $outHtml)) { throw "Explorer build failed." }
}

$repoRoot = Ensure-Repo
$codepackPath = Join-Path $repoRoot $CodepackName
$explorerPath = Join-Path $repoRoot $ExplorerName
$treePath     = Join-Path $repoRoot $TreeName

Build-Codepack $repoRoot $codepackPath
if ($MakeTree) { Build-Tree $repoRoot $treePath }
Build-Explorer $repoRoot $codepackPath $explorerPath $Title

Write-Host "Generated:"
Write-Host " - $codepackPath"
Write-Host " - $explorerPath"
if ($MakeTree) { Write-Host " - $treePath" }
