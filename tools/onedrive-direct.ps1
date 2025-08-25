param([Parameter(Mandatory=$true)][string]$Link)

# Follow redirects with a normal GET (HEAD can be flaky on OneDrive)
try {
    $resp = Invoke-WebRequest -Uri $Link -Method Get -MaximumRedirection 25 -Headers @{
        "User-Agent" = "Mozilla/5.0"
    }
} catch {
    # Even when it "fails", we often get a response with a final URI
    $resp = $_.Exception.Response
    if (-not $resp) { throw }
}

# Try to extract the final absolute URL
$final = $null
if ($resp -is [Microsoft.PowerShell.Commands.HtmlWebResponseObject]) {
    $final = $resp.BaseResponse.ResponseUri.AbsoluteUri
} elseif ($resp -is [System.Net.HttpWebResponse]) {
    $final = $resp.ResponseUri.AbsoluteUri
}

if (-not $final) {
    throw "Couldn't resolve final URL."
}

# If the final host is onedrive.live.com and path is /redir, convert to /download
# preserving cid, resid, authkey. This yields a TRUE direct-download link.
$uri = [Uri]$final
if ($uri.Host -like "onedrive.live.com" -and $uri.AbsolutePath -like "*/redir*") {
    # Parse query string
    Add-Type -AssemblyName System.Web | Out-Null
    $qs = [System.Web.HttpUtility]::ParseQueryString($uri.Query)
    $cid = $qs["cid"]; $resid = $qs["resid"]; $authkey = $qs["authkey"]
    if ($cid -and $resid) {
        $builder = [System.UriBuilder]$uri
        $builder.Path = "/download"
        # rebuild query
        $pairs = @("cid=$cid","resid=$resid")
        if ($authkey) { $pairs += "authkey=$authkey" }
        # ALWAYS force direct download
        $pairs += "download=1"
        $builder.Query = ($pairs -join "&")
        $final = $builder.Uri.AbsoluteUri
    }
}

# If it’s not yet forcing download, add download=1
if ($final -notmatch "download=1") {
    $u = [Uri]$final
    $builder = [System.UriBuilder]$u
    $q = $builder.Query.TrimStart('?')
    if ([string]::IsNullOrWhiteSpace($q)) { $builder.Query = "download=1" }
    else { $builder.Query = $q + "&download=1" }
    $final = $builder.Uri.AbsoluteUri
}

Write-Output $final
