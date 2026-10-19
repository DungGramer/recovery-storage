# R0 read-only. Disk inventory: Get-Disk + Get-PhysicalDisk + Win32_DiskDrive + partitions + volumes.
# Win32_DiskDrive.Size is geometry-truncated and InterfaceType reports NVMe as SCSI: kept for PNP join only.
# Volume labels and mount paths are user data: not collected.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

$disks = @(Get-Disk | Select-Object Number, FriendlyName, SerialNumber, UniqueId, Guid, Signature,
    BusType, Size, PartitionStyle, IsOffline, IsReadOnly, IsBoot, IsSystem,
    HealthStatus, OperationalStatus, Location, Path, LogicalSectorSize, PhysicalSectorSize)

$physical = @(Get-PhysicalDisk | Select-Object DeviceId, FriendlyName, SerialNumber, UniqueId,
    MediaType, BusType, FirmwareVersion, Size, HealthStatus, OperationalStatus,
    LogicalSectorSize, PhysicalSectorSize)

$wmi = @(Get-CimInstance Win32_DiskDrive | Select-Object Index, PNPDeviceID, Model, InterfaceType,
    Size, FirmwareRevision, MediaType, Status)

$partitions = @(Get-Partition -ErrorAction SilentlyContinue | Select-Object DiskNumber, PartitionNumber,
    DriveLetter, Offset, Size, Type, GptType, MbrType, IsReadOnly, IsOffline, IsHidden, IsSystem, IsBoot, IsActive)

# Volume per partition, letter or not: a RAW/unrecognised volume often has no letter.
$volumes = @(foreach ($p in Get-Partition -ErrorAction SilentlyContinue) {
    $v = $p | Get-Volume -ErrorAction SilentlyContinue
    if ($v) {
        [pscustomobject]@{
            DiskNumber = $p.DiskNumber; PartitionNumber = $p.PartitionNumber; DriveLetter = $v.DriveLetter
            FileSystem = $v.FileSystem; DriveType = $v.DriveType; HealthStatus = $v.HealthStatus
            OperationalStatus = $v.OperationalStatus; Size = $v.Size; SizeRemaining = $v.SizeRemaining
        }
    }
})

[pscustomobject]@{
    schema     = 'win-disks/1'
    disks      = $disks
    physical   = $physical
    wmi        = $wmi
    partitions = $partitions
    volumes    = $volumes
} | ConvertTo-Json -Depth 6 -Compress
