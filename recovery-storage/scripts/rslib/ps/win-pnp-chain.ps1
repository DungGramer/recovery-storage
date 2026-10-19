# R0 read-only. PnP parent chain per disk, up to the first USB\VID_xxxx&PID_xxxx node (or root).
# UAS disks enumerate as SCSI\DISK..., so the USB node is only reachable by walking parents.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

$maxDepth = 8
$out = @(foreach ($d in Get-CimInstance Win32_DiskDrive) {
    $chain = @()
    $id = $d.PNPDeviceID
    for ($i = 0; $i -lt $maxDepth -and $id; $i++) {
        $dev = Get-PnpDevice -InstanceId $id -ErrorAction SilentlyContinue
        $chain += [pscustomobject]@{
            InstanceId   = $id
            Class        = $dev.Class
            FriendlyName = $dev.FriendlyName
            Service      = $dev.Service
            Status       = [string]$dev.Status
        }
        if ($id -match '^USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}') { break }
        $parent = Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_Device_Parent -ErrorAction SilentlyContinue
        $id = $parent.Data
    }
    [pscustomobject]@{ Index = $d.Index; PNPDeviceID = $d.PNPDeviceID; Chain = $chain }
})

[pscustomobject]@{ schema = 'win-pnp-chain/1'; disks = $out } | ConvertTo-Json -Depth 6 -Compress
