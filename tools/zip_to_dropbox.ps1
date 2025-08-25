param(
  [string]$ZipName = "RPGenesis-Fantasy.zip",
  [string]$DropboxFolder = "$env:UserProfile\Dropbox\RPGenesis\Builds",
  [switch]$UseRclone = $false,
  [string]$RcloneRemote = "dropbox:RPGenesis/Builds"
)

# Ensure we're inside a git repo
try { git rev-parse --is-inside-work-tree | Out-Null } catch { Write-Error "Not a git repo"; exit 0 }

# Resolve repo root and temp zip path
$repoRoot = (git rev-parse --show-toplevel).Trim()
$zipTemp = Join-Path $env:TEMP $ZipName

# Create zip from HEAD (tracked files only)
Push-Location $repoRoot
try {
  if (Test-Path $zipTemp) { Remove-Item $zipTemp -Force }
  git archive --format=zip -o $zipTemp HEAD
  Write-Host "Created archive: $zipTemp"
} finally {
  Pop-Location
}

# Also build a readable codepack
& pwsh -ExecutionPolicy Bypass -File (Join-Path $repoRoot "tools\make_codepack.ps1")
$codepack = Join-Path $repoRoot "RPGenesis-Fantasy.codepack.txt"

# Upload both via Dropbox sync folder (or rclone)
$destZip      = Join-Path $DropboxFolder $ZipName
$destCodepack = Join-Path $DropboxFolder "RPGenesis-Fantasy.codepack.txt"

Copy-Item $zipTemp $destZip -Force
Copy-Item $codepack $destCodepack -Force
Write-Host "Copied zip and codepack to Dropbox: $DropboxFolder"


if ($UseRclone) {
  # Upload to Dropbox via rclone remote (requires: rclone config + a 'dropbox' remote)
  $rclone = Get-Command rclone -ErrorAction SilentlyContinue
  if (-not $rclone) {
    Write-Warning "rclone not found; falling back to local Dropbox sync folder copy."
  } else {
    & rclone copy $zipTemp "$RcloneRemote" --progress
    if ($LASTEXITCODE -eq 0) {
      Write-Host "Uploaded to Dropbox via rclone: $RcloneRemote/$ZipName"
      exit 0
    } else {
      Write-Warning "rclone copy failed; falling back to local Dropbox sync folder copy."
    }
  }
}

# Fallback / default: copy into local Dropbox sync folder (Dropbox client will sync it)
if (-not (Test-Path $DropboxFolder)) { New-Item -ItemType Directory -Force -Path $DropboxFolder | Out-Null }
$dest = Join-Path $DropboxFolder $ZipName
Copy-Item $zipTemp $dest -Force
Write-Host "Copied to Dropbox sync folder: $dest"
