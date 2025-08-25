param([Parameter(Mandatory=$true)][string]$Link)

function Follow-Redirect([string]$url, [int]$max=5) {
  $current = $url
  for ($i=0; $i -lt $max; $i++) {
    try {
      $resp = Invoke-WebRequest -Uri $current -Method Head -MaximumRedirection 0 -ErrorAction Stop
      return $current  # no redirect => this is final
    } catch {
      $ex = $_.Exception
      $res = $ex.Response
      if (-not $res) { throw }
      $loc = $res.Headers['Location']
      if (-not $loc) { return $current }
      $current = $loc
      # ensure download=1 to force binary
      if ($current -notmatch 'download=1') {
        $current += ($current -match '\?') ? '&download=1' : '?download=1'
      }
    }
  }
  return $current
}

$final = Follow-Redirect $Link 10
Write-Output $final
