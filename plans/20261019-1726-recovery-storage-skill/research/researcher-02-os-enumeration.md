# Research Report: OS enumeration cho recovery-storage (Windows 11 + Linux)
Date: 2026-10-19

Ky hieu: [V] = da doc nguon trong phien nay; [K] = kien thuc da biet, CHUA fetch duoc nguon (3/5 fetch learn.microsoft.com tra 404, gioi han 5 tool call). Moi muc [K] phai test tren may that truoc khi khoa vao script.

## Summary
Dinh danh thiet bi nen dung "fingerprint" nhieu thuoc tinh: model + serial (da chuan hoa) + size bytes + bus + VID/PID + (Windows) UniqueId/ContainerId + (disk) GPT GUID / MBR signature. Khong dung Disk Number, PhysicalDriveN, drive letter, /dev/sdX lam khoa. Tat ca lenh ben duoi la doc-only; thao tac "chan ghi" la thay doi chinh sach OS, can tach rieng, mac dinh khong tu chay.
Windows: dung module Storage (CIM, root/Microsoft/Windows/Storage) cho Disk/PhysicalDisk/Partition/Volume, Win32_DiskDrive cho PNPDeviceID, roi di nguoc cay PnP (DEVPKEY_Device_Parent) toi node `USB\VID_xxxx&PID_xxxx\serial`. Linux: lsblk + udevadm + sysfs; VID/PID doc truc tiep tu /sys/bus/usb/devices.
Rui ro lon nhat: cau USB re bao serial rong/trung/byte-swapped; UAS khong co USBSTOR trong PNPDeviceID; mount tu dong cua OS (journal replay) co the ghi vao thiet bi hong.

## Method
Fetch: man7 blockdev [V], uwe-sieber UsbTreeView page [V]; MS Learn (event 153, MSFT_StorageReliabilityCounter, StorageDevicePolicies) 404 -> [K]. Khong co WebSearch bo sung do gioi han 5 call.

## 1. Windows enumeration
Cmdlet (module Storage, CIM-backed; docs: https://learn.microsoft.com/powershell/module/storage/get-disk , .../get-physicaldisk , .../get-storagereliabilitycounter) [K]
- `Get-Disk`: Number, FriendlyName, SerialNumber, UniqueId, Guid, Signature, Path, Location, BusType, Size, PartitionStyle, IsOffline, IsReadOnly, IsBoot/IsSystem, HealthStatus, OperationalStatus. Khong can admin de doc (thuong) [K].
- `Get-PhysicalDisk`: DeviceId (thuong = Disk Number, nhung KHONG dam bao voi Storage Spaces), FriendlyName, SerialNumber, UniqueId, MediaType, BusType, FirmwareVersion, Size, SpindleSpeed, HealthStatus, OperationalStatus, CanPool. Lien ket voi Disk qua UniqueId (khong dung DeviceId) [K].
- `Get-PhysicalDisk | Get-StorageReliabilityCounter` (MSFT_StorageReliabilityCounter): Temperature, TemperatureMax, Wear, ReadErrorsTotal/Corrected/Uncorrected, WriteErrorsTotal/Corrected/Uncorrected, PowerOnHours, StartStopCycleCount, LoadUnloadCycleCount, ManufactureDate, Read/Write/FlushLatencyMax. Thuong CAN ADMIN (non-admin tra rong/loi); nhieu truong $null tren USB bridge, SD, o tuy driver; bridge USB gan nhu khong chuyen SMART [K]. Day khong thay SMART day du: SMART raw can smartctl (ngoai pham vi nay).
- `Get-CimInstance Win32_DiskDrive`: DeviceID (`\\.\PHYSICALDRIVEn`), Index (= Disk Number), Model, SerialNumber, PNPDeviceID, InterfaceType (USB/IDE/SCSI/1394; NVMe va UAS thuong hien SCSI), Size, FirmwareRevision, MediaType, Status, Capabilities [K].
- BusType (enum MSFT_Disk/PhysicalDisk) [K]: 0 Unknown, 1 SCSI, 2 ATAPI, 3 ATA, 4 1394, 5 SSA, 6 FibreChannel, 7 USB, 8 RAID, 9 iSCSI, 10 SAS, 11 SATA, 12 SD, 13 MMC, 14 Virtual, 15 FileBackedVirtual, 16 Spaces, 17 NVMe, 18 SCM, 19 UFS. PS 5.1 Get-Disk tra ten chu; MSFT_* CIM raw tra so -> map ca hai.
- Partition/volume: `Get-Partition -DiskNumber n` (PartitionNumber, DriveLetter, Offset, Size, Type, GptType, Guid, IsReadOnly, IsHidden), `Get-Volume` (DriveLetter, FileSystem, FileSystemLabel, Size, SizeRemaining, DriveType, HealthStatus, OperationalStatus, Path, UniqueId). Noi Volume<->Partition qua `Get-Partition | Get-Volume` hoac AccessPaths. Doc-only, nhung FS hong thuong hien FileSystem rong/RAW [K].
- HealthStatus: Healthy / Warning / Unhealthy / Unknown. OperationalStatus (disk): OK, Offline, Failed, No Media, Lost Communication, IO Error, Predictive Failure, Starting/Stopping/In Service, Transient Error, Degraded, Unrecognized Metadata... "Warning/Unhealthy" khong bang thiet bi chet; chi la tin hieu, doi chieu event log [K].

Mapping Disk Number <-> PhysicalDriveN <-> PNP <-> USB:
1. Get-Disk.Number == Win32_DiskDrive.Index; DeviceID = `\\.\PHYSICALDRIVE<Number>`. Doc 1 lan, snapshot, vi so co the doi khi re-enumerate.
2. Win32_DiskDrive.PNPDeviceID: bulk-only = `USBSTOR\DISK&VEN_x&PROD_y&REV_z\<serial>&0`; UAS = `SCSI\DISK&VEN_..\...` (khong co USBSTOR); NVMe = `SCSI\DISK&...` hoac `PCI\...` [K].
3. Di nguoc: `Get-PnpDeviceProperty -InstanceId <id> -KeyName DEVPKEY_Device_Parent` lap lai den khi InstanceId bat dau `USB\VID_xxxx&PID_xxxx\`; parse VID/PID/serial tu do. Them DEVPKEY_Device_ContainerId (nhom vat ly), DEVPKEY_Device_LocationInfo / DEVPKEY_Device_LocationPaths (port chain), DEVPKEY_Device_BusReportedDeviceDesc [K]. Get-PnpDevice/Get-PnpDeviceProperty khong can admin de doc [K].
4. Truong hop UAS: parent chain van toi `USB\VID&PID` composite/UASP; chi parse khi tim duoc, neu khong ghi `usb: null` thay vi doan.

JSON: `... | ConvertTo-Json -Depth 6 -Compress`; mac dinh Depth=2 cat cut object long. Chon property tuong minh (Select-Object) thay vi dump CimInstance (co CimClass/CimSystemProperties gay nhieu). Dat `[Console]::OutputEncoding=[Text.Encoding]::UTF8`. Enum trong 5.1 co the ra so hoac chuoi tuy cmdlet: chuan hoa trong Python [K].

Pitfalls [K]:
- Serial: Win32_DiskDrive.SerialNumber tren SATA/USB co the la hex ma hoa, doi cap byte (byte-swapped), con NVMe co dang `XXXX_XXXX_..._` voi dau `.` cuoi; Get-Disk/PhysicalDisk SerialNumber hay co khoang trang dem. Chuan hoa: trim, bo `_`/`.`, thu hex-decode + swap, luu ca "raw" va "normalized". USB re: serial rong, mac dinh hoac trung (nhieu USB cung "0000000000"/"0123456789ABCDEF") -> danh dau `serial_trust: low`.
- Windows PowerShell 5.1 (powershell.exe, co san) vs 7 (pwsh): Storage module chay native tren 5.1; tren 7 co the phai qua compat layer (`-UseWindowsPowerShell`) va co khac biet kieu enum/JSON. Khuyen nghi: goi `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File/-Command` co dinh 5.1, hoac truy van CIM truc tiep (`Get-CimInstance -Namespace root/Microsoft/Windows/Storage -ClassName MSFT_Disk`) de bo phu thuoc module.
- Doc Get-Disk tren dia hong co the treo/timeout lau: dung timeout o subprocess.

## 2. Windows event log (System) - doc-only
Query [K; Get-WinEvent: https://learn.microsoft.com/powershell/module/microsoft.powershell.diagnostics/get-winevent]:
`Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date).AddDays(-7); ProviderName='disk','Ntfs','volmgr','stornvme','storahci','Microsoft-Windows-Kernel-PnP'} -MaxEvents 500` roi loc Id trong Python/PS. Luon dat StartTime (+EndTime) va MaxEvents; FilterHashtable nhanh hon Where-Object. System log doc duoc khong can admin; log Operational cua Kernel-PnP/Configuration, DriverFrameworks, USB-USBHUB3 co the can admin [K]. Message co `\Device\HarddiskN\DRn` -> chi la so tai thoi diem do; map ve thiet bi bang thoi gian + Disk Number luc do, khong tin sau re-enumerate.
| Provider | Id | Y nghia |
|---|---|---|
| disk | 7 | bad block |
| disk | 11 | controller error |
| disk | 15 | not ready (khong truy cap duoc) |
| disk | 51 | paging error |
| disk | 52 | SMART predicts failure (neu bao) |
| disk | 153 | IO retried (co the la `\Device\HarddiskN\DRn` + LBA) |
| disk | 157 | disk surprise removed |
| Ntfs | 55 (cau truc FS hong), 98 (volume can chkdsk), 130/137/140 (loi ghi/flush/transaction) | |
| volmgr | 46 (crashdump init), 161 (dump file creation failed) | |
| storahci / stornvme | 129 | reset to device |
| Microsoft-Windows-Kernel-PnP | 410/411 (start/removal), 400/401, 219 (driver fail to load) | |
| USB: usbhub / Microsoft-Windows-USB-USBHUB3 | enumeration/overcurrent | ID cu the chua xac minh |
Muc [K] chua xac minh: Id cua partmgr, UASPStor, USBHUB3; kiem tra tren may that (Event Viewer) truoc khi hardcode. Ntfs 55/98/140 va 7/11/51/153/157 la tap quen thuoc nhat.

## 3. Chan ghi / chan automount tren Windows
Nguyen tac: Windows co the ghi len thiet bi ngay khi attach (mount, replay NTFS journal, tao System Volume Information, indexer). Chan truoc khi cam. Chan mem KHONG thay write blocker phan cung cho an toan bang chung/du lieu quy.
| Cach | Pham vi / luu tru | Admin | Rui ro |
|---|---|---|---|
| `mountvol /N` (hoac `diskpart automount disable`) | OS-wide, persistent (registry mountmgr), khong ghi len thiet bi | Co | Thap voi thiet bi; tac dong moi o USB khac, nho `mountvol /E` de khoi phuc |
| `Set-Disk -Number n -IsOffline $true` | thuoc tinh disk trong OS, khong mount volume | Co | Thap; van bi truy cap raw; co the can doi ten disk khi re-enumerate |
| `Set-Disk -Number n -IsReadOnly $true` / `diskpart attributes disk set readonly` | co read-only cap disk luu trong CSDL cua OS theo disk (kha nang khong ghi vao media), nhung mot so tai lieu noi la thuoc tinh persistent cua disk; chua xac minh | Co | Trung binh; ghi la thay doi trang thai co the sot lai -> doc ky truoc khi dung |
| Registry `HKLM\SYSTEM\CurrentControlSet\Control\StorageDevicePolicies\WriteProtect=1` | OS policy, ap cho moi USB mass storage, can replug/reboot | Co | Thap voi thiet bi; anh huong toan he thong; khong chan ghi raw tu cong cu co quyen |
| Write blocker phan cung | chan o tang bus | khong | Thap nhat; khuyen nghi cho dia quan trong |
Nguon cho muc nay: [K] (MS Learn diskpart/attributes disk, mountvol, Set-Disk); registry WriteProtect khong xac minh duoc doc MS (404). Mac dinh script chi doc va CANH BAO; hanh dong chan ghi la buoc rieng can nguoi dung dong y.

## 4. Linux
- `lsblk -J -O -b` [K, man7 lsblk(8)]: -J JSON, -O moi cot, -b byte. Cot dung: name, path, model, vendor, serial, wwn, size, tran (usb/sata/nvme), rev, hotplug, ro, rm, type, pttype, ptuuid, fstype, uuid, mountpoints, state, subsystems. Ban util-linux cu (<2.37) xuat so dang chuoi o mot so cot -> ep kieu trong Python. Khong can root.
- `udevadm info --query=property --name=/dev/sdX` [K, man7 udevadm(8)]: ID_BUS, ID_MODEL, ID_VENDOR_ID, ID_MODEL_ID, ID_SERIAL, ID_SERIAL_SHORT, ID_WWN, ID_PATH, ID_USB_DRIVER (usb-storage hoac uas), ID_USB_INTERFACES, DEVPATH. Khong can root.
- USB sysfs: tu `readlink -f /sys/block/sdX/device` di len thu muc cha co `idVendor`; doc idVendor, idProduct, serial, manufacturer, product, busnum, devnum, speed, bcdDevice. `lsusb -v -d vid:pid` day du hon nhung mot so descriptor (BOS) can root. Cung nguon [K, kernel docs: https://www.kernel.org/doc/html/latest/driver-api/usb/ ; ABI sysfs-bus-usb].
- Log loi: `dmesg --time-format iso` (co the can root neu `kernel.dmesg_restrict=1`) hoac `journalctl -k -o json --since` (can group systemd-journal/adm). Mau: `blk_update_request: I/O error, dev sdX, sector N`, `Buffer I/O error on dev`, `reset high-speed USB device number N`, `reset SuperSpeed USB device`, `uas_eh_...`/`uas: ... reset`, `usb ... disconnect, device number N`, `Medium Error`, `Unrecovered read error`, `ata\d+: ... exception`, `nvme nvme0: ... timeout`. Cac mau [K].
- Read-only: `blockdev --getsize64 /dev/sdX`, `--getro` in 1 neu RO [V man7 blockdev(8)]. `--setro` chi dat co kernel trong bo nho (can root), "may not affect access that is already active; a filesystem mounted read-write keeps access" [V] -> dung truoc khi mount, khong persistent qua replug. Ben vung hon: udev rule dat ro, hoac mount `-o ro,noload` (ext4) / `ro,norecovery` (xfs).
- Tat automount [K]: udev rule `ENV{UDISKS_IGNORE}="1"` (chinh xac theo ID_SERIAL/VID:PID); hoac `systemctl stop/mask udisks2`; GNOME `gsettings set org.gnome.desktop.media-handling automount false`. Chi la chinh sach OS, khong ghi thiet bi. Probe udev (blkid) chi doc.
- SD: `/sys/block/mmcblk0/device/{cid,csd,scr,manfid,oemid,name,serial,date,fwrev,hwrev,type}` (dir nay = /sys/class/mmc_host/mmcN/mmcN:xxxx) chi co khi SD qua host MMC/SDHCI native. Dau doc the USB hien la `sdX` qua SCSI (chi INQUIRY vendor/product cua dau doc, khong co CID the) [K; ABI sysfs-devices-mmc?]. Script: neu khong co cac file nay thi `sd_native: false`.

## 5. Cong cu descriptor USB
- USB Device Tree Viewer (uwe-sieber.de/usbtreeview_e.html) [V]: co XML report (ghi/doc, v3.3+, khong tuong thich USBView) va copy screenshot vao clipboard. Trang KHONG neu tuy chon dong lenh -> chua xac minh CLI; khong nen phu thuoc (GUI, ben thu ba). Thay the: PnP property + `pnputil /enum-devices /connected /properties` (Win11 co) [K], hoac Microsoft USBView (sample, GUI).
- `usbutils` (lsusb, lsusb -t cay, `usb-devices` script in sysfs) [K, https://github.com/gregkh/usbutils]; ma doc sysfs truc tiep it phu thuoc hon.

## 6. Phat hien ngat ket noi / re-enumerate trong phien
Doi do ben vung vs khong ben vung [K]:
- Doi khi re-enumerate: Disk Number, PhysicalDriveN, /dev/sdX, drive letter, USB devnum (tang moi lan), port chain neu cam cong khac, Container ID khong doi (cung cong), instance id thay doi voi serial rong.
- Dung de nhan lai: serial (neu trust), model, size bytes, VID/PID, bcdDevice, firmware rev, UniqueId/WWN, GPT disk GUID / MBR signature (doc LBA0/GPT header qua Get-Disk.Guid/Signature, lsblk ptuuid), cong vat ly.
- Phat hien: poll snapshot (2-5 s) va diff theo fingerprint; hoac Windows `Register-CimIndicationEvent -ClassName Win32_DeviceChangeEvent` / Event 410,157; Linux `udevadm monitor --subsystem-match=block --property` hoac `journalctl -k -f` thay "USB disconnect".
- Quy tac khop: 3 muc: exact (serial trust cao + size + VID/PID + model), probable (khong serial: size + VID/PID + model + ptuuid + cung port), ambiguous -> hoi nguoi dung, KHONG tu gan. Ghi su kien "disconnect/reconnect" vao JSON, kem timestamp, de doi chieu voi dmesg/event log (dau hieu bridge/cap/nguon).
- Thiet bi hong thuong re-enumerate lien tuc -> cap nhat Disk Number moi roi moi chay lenh sau; khong cache so cu.

## Sources
- https://man7.org/linux/man-pages/man8/blockdev.8.html [V]
- https://www.uwe-sieber.de/usbtreeview_e.html [V]
- https://learn.microsoft.com/powershell/module/storage/get-disk , get-physicaldisk , get-storagereliabilitycounter , get-partition , get-volume [K, khong fetch]
- https://learn.microsoft.com/powershell/module/microsoft.powershell.diagnostics/get-winevent [K]
- https://learn.microsoft.com/windows-hardware/drivers/storage/ (event 153 URL tra 404) ; https://learn.microsoft.com/windows-server/administration/windows-commands/mountvol [K]
- https://man7.org/linux/man-pages/man8/lsblk.8.html , udevadm.8 [K]; https://www.kernel.org/doc/html/latest/driver-api/mmc/ [K]; https://github.com/gregkh/usbutils [K]

## Unresolved questions
1. URL MS Learn dung cho event 153/157, StorageReliabilityCounter, StorageDevicePolicies: can fetch lai (3 URL bi 404).
2. `Set-Disk -IsReadOnly` / diskpart readonly: luu o dau, co ghi byte nao len thiet bi khong? Can test tren dia thu hoac doc Microsoft docs.
3. Get-StorageReliabilityCounter co that su can admin tren Win11 hien tai, va tra gi cho USB/SD?
4. Id su kien cu the cua partmgr, UASPStor, USBHUB3 tren Win11 26200.
5. UsbTreeView co CLI export khong (trang chinh khong noi).
6. Storage module tren pwsh 7 co chay native hay qua compat tren Win11 hien tai.
7. UAS: parent chain tu `SCSI\DISK` toi `USB\VID_` co on dinh tren tat ca cau hinh (can test).
