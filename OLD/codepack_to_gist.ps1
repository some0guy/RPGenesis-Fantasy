param(
  [Parameter(Mandatory=$true)][string]$GistId,
  [Parameter(Mandatory=$true)][string]$TokenPath,
  [Parameter(Mandatory=$true)][string]$FilePath,
  [string]$BaseName    = "codepack",  # files will be codepack_001.txt, codepack_002.txt, ...
  [int]   $PartChars   = 900000,      # per-file char budget (~0.9 MB) to stay under Gist limits
  [int]   $MaxParts    = 20,          # safety upper bound; adjust if needed
  [switch]$DeleteOldParts             # delete extra *_NNN.txt files that existed previously
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not (Test-Path -LiteralPath $FilePath)) { throw "File not found: $FilePath" }
if (-not (Test-Path -LiteralPath $TokenPath)) { throw "Token file not found: $TokenPath" }

$token = (Get-Content -LiteralPath $TokenPath -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($token)) { throw "Token file is empty: $TokenPath" }

# Read the whole pack as UTF-8
$content = Get-Content -LiteralPath $FilePath -Raw -Encoding UTF8
$len = $content.Length

function Escape-JsonString([string]$s) {
  # JSON-escape without external assemblies; works in PowerShell 5+ and 7+
  $e = $s `
    -replace '\\', '\\\\' `
    -replace '"', '\"' `
    -replace "`r", '\r' `
    -replace "`n", '\n' `
    -replace "`t", '\t'
  $e = $e -replace ([char]8), '\b'
  $e = $e -replace ([char]12), '\f'
  return $e
}

# Split into parts
$parts = @()
if ($len -le $PartChars) {
  $parts = ,$content
} else {
  for ($i = 0; $i -lt $len -and $i -lt ($PartChars * $MaxParts); $i += $PartChars) {
    $end = [Math]::Min($PartChars, $len - $i)
    $parts += $content.Substring($i, $end)
  }
  if ($len -gt $PartChars * $MaxParts) {
    Write-Warning "Content truncated at $($PartChars*$MaxParts) characters to respect MaxParts=$MaxParts."
  }
}

# Build JSON payload with multiple files: BaseName_001.txt, _002.txt, ...
# Also optionally delete old surplus parts by setting them to null.
# First, fetch the existing gist to know what files it has (for deletion logic and raw URLs)
$headers = @{
  Authorization = "token $token"     # or "Bearer $token" for fine-grained PATs
  "User-Agent"  = "RPGenesis-GistSync"
  Accept        = "application/vnd.github+json"
}
$uri = "https://api.github.com/gists/$GistId"

Write-Host "[INFO] Reading current gist $GistId ..."
$existing = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers

# Prepare files map
$filesMap = @{}

# Add/update the chunk files
for ($p = 0; $p -lt $parts.Count; $p++) {
  $n = "{0}_{1:D3}.txt" -f $BaseName, ($p+1)
  $escaped = Escape-JsonString $parts[$p]
  $filesMap[$n] = @{ content = $parts[$p] }  # keep original for raw_url calc
}

# Mark extra old parts for deletion if requested
if ($DeleteOldParts) {
  $pattern = "^$([Regex]::Escape($BaseName))_\d{3}\.txt$"
  foreach ($fname in $existing.files.PSObject.Properties.Name) {
    if ($fname -match $pattern) {
      # If this file name is not in the new set, schedule delete (null)
      if (-not $filesMap.ContainsKey($fname)) {
        $filesMap[$fname] = $null
      }
    }
  }
}

# Build payload JSON manually to keep 'content' as a JSON string
# (If value is $null, we emit null to delete that file)
$sb = New-Object System.Text.StringBuilder
[void]$sb.Append('{"files":{')
$first = $true
foreach ($key in $filesMap.Keys) {
  if (-not $first) { [void]$sb.Append(',') } else { $first = $false }
  [void]$sb.Append('"' + ($key -replace '"','\"') + '":')
  $val = $filesMap[$key]
  if ($null -eq $val) {
    [void]$sb.Append('null')  # delete this file
  } else {
    $escaped = Escape-JsonString $val.content
    [void]$sb.Append('{"content":"' + $escaped + '"}')
  }
}
[void]$sb.Append('}}')
$bodyJson = $sb.ToString()

Write-Host "[INFO] Updating gist $GistId with $($parts.Count) part(s) ..."
$response = Invoke-RestMethod -Method Patch -Uri $uri -Headers $headers `
  -ContentType 'application/json; charset=utf-8' -Body $bodyJson

Write-Host "[OK] Gist updated."

# Print raw URLs for the parts (versioned)
$pattern2 = "^$([Regex]::Escape($BaseName))_\d{3}\.txt$"
$urls = @()
foreach ($prop in $response.files.PSObject.Properties) {
  if ($prop.Name -match $pattern2) {
    $urls += $prop.Value.raw_url
  }
}

if ($urls.Count -gt 0) {
  $urls = $urls | Sort-Object
  Write-Host "Raw URLs:"
  $urls | ForEach-Object { Write-Host $_ }
} else {
  Write-Host "Open the gist and click 'Raw' on each part."
}
