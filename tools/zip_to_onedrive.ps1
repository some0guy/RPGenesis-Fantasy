param(
  [string]$ZipName = "RPGenesis-Fantasy.zip",
  [string]$OneDriveFolder = "T:\OneDrive\Coding",
  [switch]$UseRclone = $false,
  [string]$RcloneRemote = "onedrive:Coding"
)

# Ensure we're inside a git repo
try { git rev-parse --is-inside-work-tree | Out-Null } catch { Write-Error "Not a git repo"; exit 0 }

# Prepare paths
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

if ($UseRclone) {
  # rclone upload directly to OneDrive remote
  $rclone = Get-Command rclone -ErrorAction SilentlyContinue
  if (-not $rclone) {
    Write-Warning "rclone not found; falling back to OneDrive sync folder path."
  } else {
    & rclone copy $zipTemp "$RcloneRemote" --progress
    if ($LASTEXITCODE -eq 0) {
      Write-Host "Uploaded to OneDrive via rclone: $RcloneRemote/$ZipName"
      exit 0
    } else {
      Write-Warning "rclone copy failed; falling back to OneDrive sync folder path."
    }
  }
}

# Fallback: write into local OneDrive sync folder (client will sync)
if (-not (Test-Path $OneDriveFolder)) { New-Item -ItemType Directory -Force -Path $OneDriveFolder | Out-Null }
$dest = Join-Path $OneDriveFolder $ZipName
Copy-Item $zipTemp $dest -Force
Write-Host "Copied to OneDrive sync folder: $dest"
