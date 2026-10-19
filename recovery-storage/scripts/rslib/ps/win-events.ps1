# R0 read-only. Storage-related System log events (Critical/Error/Warning) in a lookback window.
# Parameters come from env (validated by the runner): RS_LOOKBACK_HOURS, RS_MAX_EVENTS, RS_MESSAGE_CHARS.
# Providers are queried one by one: a provider with no events must not hide the others.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

$hours = [int]$env:RS_LOOKBACK_HOURS
$max = [int]$env:RS_MAX_EVENTS
$chars = [int]$env:RS_MESSAGE_CHARS
$since = (Get-Date).AddHours(-$hours)
$providers = @('disk', 'Ntfs', 'exfat', 'fastfat', 'volmgr', 'partmgr', 'storahci', 'stornvme',
    'UASPStor', 'USBSTOR', 'sdbus', 'Microsoft-Windows-Kernel-PnP')

$events = @()
$errors = @()
foreach ($p in $providers) {
    try {
        $found = Get-WinEvent -MaxEvents $max -FilterHashtable @{
            LogName = 'System'; ProviderName = $p; Level = 1, 2, 3; StartTime = $since
        } -ErrorAction Stop
        foreach ($e in $found) {
            $msg = [string]$e.Message
            if ($msg.Length -gt $chars) { $msg = $msg.Substring(0, $chars) }
            $events += [pscustomobject]@{
                time     = $e.TimeCreated.ToUniversalTime().ToString('o')
                provider = $e.ProviderName
                id       = $e.Id
                level    = $e.Level
                message  = $msg
            }
        }
    } catch {
        # No events, or provider not registered on this host: normal empty case. Anything else is reported.
        if ($_.FullyQualifiedErrorId -notmatch 'NoMatchingEventsFound|NoMatchingProvidersFound') {
            $errors += [pscustomobject]@{ provider = $p; error = $_.FullyQualifiedErrorId }
        }
    }
}

[pscustomobject]@{
    schema         = 'win-events/1'
    since          = $since.ToUniversalTime().ToString('o')
    lookback_hours = $hours
    events         = $events
    errors         = $errors
} | ConvertTo-Json -Depth 5 -Compress
