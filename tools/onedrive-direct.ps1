param([Parameter(Mandatory=$true)][string]$Link)

try {
  $resp = Invoke-WebRequest -Uri $Link -Method Get -MaximumRedirection 25 -Headers @{ "User-Agent" = "Mozilla/5.0" }
} catch {
  $resp = $_.Exception.Response
  if (-not $resp) { throw }
}

$final = $null
if ($resp -is [Microsoft.PowerShell.Commands.HtmlWebResponseObject]) { $final = $resp.BaseResponse.ResponseUri.AbsoluteUri }
elseif ($resp -is [System.Net.HttpWebResponse]) { $final = $resp.ResponseUri.AbsoluteUri }
if (-not $final) { throw "Couldn't resolve final URL." }

$uri = [Uri]$final
if ($uri.Host -like "onedrive.live.com" -and $uri.AbsolutePath -like "*/redir*") {
  Add-Type -AssemblyName System.Web | Out-Null
  $qs = [System.Web.HttpUtility]::ParseQueryString($uri.Query)
  $cid = $qs["cid"]; $resid = $qs["resid"]; $authkey = $qs["authkey"]
  if ($cid -and $resid) {
    $b = [System.UriBuilder]$uri
    $b.Path = "/download"
    $pairs = @("cid=$cid","resid=$resid")
    if ($authkey) { $pairs += "authkey=$authkey" }
    $pairs += "download=1"
    $b.Query = ($pairs -join "&")
    $final = $b.Uri.AbsoluteUri
  }
}
$U = [Uri]$final
$B = [System.UriBuilder]$U
$q = $B.Query.TrimStart('?')
if ([string]::IsNullOrEmpty($q)) { $B.Query = "download=1" } else { if ($q -notlike "*download=1*") { $B.Query = "$q&download=1" } }
$final = $B.Uri.AbsoluteUri

Write-Output $final
