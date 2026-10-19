# Requirement: SKILL recovery-storage (verbatim from user, 2026-10-19)

**Phạm vi:** USB, SD/microSD, HDD, SSD SATA/NVMe, ổ cứng ngoài, thiết bị lưu trữ qua USB bridge và các thiết bị flash có controller chuyên dụng.

**Mục tiêu:** Chẩn đoán, phục hồi dữ liệu, sửa chữa logic, khôi phục khả năng sử dụng, xác minh tính xác thực và đánh giá khả năng tiếp tục sử dụng của thiết bị lưu trữ.

## 1. Nguyên tắc vận hành

### 1.1. Xác định mục tiêu trước khi thao tác

Mỗi phiên xử lý phải xác định mục tiêu chính:

- `data-recovery`: ưu tiên cứu dữ liệu, không thay đổi dữ liệu nguồn nếu chưa có phương án được chấp thuận.
- `device-recovery`: khôi phục khả năng sử dụng, có thể xóa toàn bộ dữ liệu.
- `diagnosis-only`: chỉ kiểm tra và kết luận nguyên nhân; không sửa chữa.
- `authenticity-check`: xác minh dung lượng thực, thông tin phần cứng, dấu hiệu giả mạo.
- `health-assessment`: đánh giá tình trạng, độ tin cậy và khả năng tiếp tục sử dụng.
- `forensic-preservation`: bảo toàn bằng chứng, ghi nhận hiện trạng và hạn chế tối đa thay đổi lên thiết bị nguồn.

Một phiên có thể kết hợp nhiều mục tiêu. Nếu có dữ liệu quan trọng, mặc định ưu tiên cứu dữ liệu trước sửa chữa.

### 1.2. Thứ tự ưu tiên

1. Tránh làm mất dữ liệu không thể phục hồi.
2. Tránh làm thiết bị hỏng nặng hơn.
3. Thu thập bằng chứng trước khi đưa ra chẩn đoán.
4. Sử dụng công cụ phù hợp với đúng loại thiết bị và lỗi.
5. Kiểm chứng kết quả bằng phép thử độc lập.
6. Chỉ giữ lại thiết bị khi có đủ bằng chứng về khả năng hoạt động.

### 1.3. Ưu tiên công cụ có sẵn

Thứ tự lựa chọn:

1. Công cụ chẩn đoán và phục hồi mã nguồn mở đã được kiểm chứng.
2. Công cụ chính thức từ nhà sản xuất thiết bị hoặc controller.
3. Công cụ chuyên dụng của bên thứ ba có nguồn gốc và phiên bản xác định.
4. Script để kết nối, điều phối, thu thập kết quả và tự động hóa.
5. Phát triển công cụ riêng chỉ khi không có công cụ phù hợp hoặc thiếu khả năng tích hợp cần thiết.

Không tự viết công cụ thay thế các thành phần phức tạp như filesystem repair, forensic imaging, SMART parsing hoặc NAND decoding nếu đã có công cụ phù hợp.

## 2. Quy trình tổng thể

### Phase 0 - Xác định mục tiêu và mức độ rủi ro

Thu thập: mục tiêu phiên xử lý; loại thiết bị, model, dung lượng danh định; dữ liệu có cần bảo toàn hay không; hệ điều hành và kết nối hiện tại; triệu chứng, lịch sử lỗi và thao tác đã thực hiện; mức độ chấp nhận rủi ro và chi phí phục hồi.

Phân loại rủi ro:

- `R0 - Read-only`: chỉ thu thập thông tin, không ghi lên thiết bị.
- `R1 - Low-risk`: thao tác không phá hủy, có thể thay đổi trạng thái kết nối hoặc hệ điều hành.
- `R2 - Destructive`: format, sửa filesystem, ghi đè, tạo lại phân vùng hoặc thay đổi firmware.
- `R3 - Hardware-level`: mở thiết bị, sửa mạch, tháo chip hoặc sử dụng công cụ đọc NAND chuyên dụng.

Không chuyển sang R2/R3 khi chưa đánh giá ảnh hưởng đến mục tiêu phiên xử lý.

### Phase 1 - Sàng lọc phần cứng và xác định khả năng phục hồi

Mục đích: phát hiện các trường hợp không nên tiếp tục thử bằng phần mềm thông thường.

Kiểm tra: cổng kết nối, dây cáp, nguồn điện, adapter và enclosure; thiết bị có được hệ điều hành nhận dạng hay không; có tiếng lạch cạch, nóng bất thường, mất kết nối hoặc khởi động lặp lại hay không; HDD có lỗi cơ học, SSD có dấu hiệu lỗi controller hoặc USB có dấu hiệu hỏng mạch không; thiết bị có đọc được thông tin nhận dạng và dung lượng hay không.

Phân loại kết quả:

- `SOFTWARE_RECOVERY_CANDIDATE`: có thể tiếp tục chẩn đoán phần mềm.
- `CONTROLLER_RECOVERY_CANDIDATE`: cần điều tra controller, firmware hoặc chế độ chỉ đọc.
- `HARDWARE_DIAGNOSIS_REQUIRED`: cần kiểm tra phần cứng chuyên sâu.
- `STOP_UNSAFE`: có nguy cơ làm hỏng thiết bị hoặc mất dữ liệu nghiêm trọng.
- `UNDETERMINED`: chưa đủ bằng chứng để kết luận.

Không kết luận thiết bị chắc chắn không thể cứu chỉ vì không nhận trong Explorer, không có phân vùng hoặc một công cụ không nhận diện được.

### Phase 2 - Thu thập bằng chứng và phân tích nguyên nhân

#### 2.1. Nhận dạng thiết bị

Thu thập: hãng, model, serial, firmware revision; dung lượng danh định và dung lượng hệ điều hành nhận diện; bus, giao thức, VID/PID, USB descriptors; controller, Flash ID, NAND ID nếu công cụ có thể đọc; partition table, filesystem, sector size và trạng thái thiết bị; phiên bản firmware và công cụ chẩn đoán đã sử dụng.

Đối chiếu thông tin in trên vỏ, nhãn, thông tin firmware, thông tin controller và dữ liệu nhận dạng thực tế. Không xem bất kỳ nguồn thông tin đơn lẻ nào là bằng chứng tuyệt đối.

#### 2.2. Phân tích sức khỏe

HDD/SSD SATA/NVMe: SMART overall status; Reallocated Sector Count, Current Pending Sector, Uncorrectable Sector; Power-On Hours, Power Cycle Count; Temperature, error logs và self-test logs; Wear indicators, Percentage Used, Total Host Writes và các chỉ số NAND wear nếu được hỗ trợ; NVMe Critical Warning, Media and Data Integrity Errors, Available Spare.

USB flash và thẻ nhớ: VID/PID, controller, dung lượng được báo cáo; trạng thái chỉ đọc, lỗi giao tiếp, lỗi I/O và trạng thái media; Flash ID, NAND geometry và các thông tin wear nếu controller cho phép truy cập; dung lượng thực và tính nhất quán của dữ liệu ghi/đọc.

Không giả định mọi USB đều cung cấp SMART, TBW hoặc số chu kỳ ghi. TBW là chỉ số độ bền ghi thường được công bố cho SSD; không phải một trường phổ quát có thể đọc từ mọi thiết bị. Power Cycle Count thường viết tắt là PCC trong một số ngữ cảnh, nhưng cần xác minh tên trường cụ thể. Không suy diễn giá trị không có sẵn.

#### 2.3. Phân tích lỗi

Nhóm nguyên nhân: lỗi cổng, cáp, nguồn hoặc bridge; lỗi bảng phân vùng hoặc filesystem; bad sector hoặc lỗi đọc/ghi; lỗi controller hoặc firmware; NAND/flash degradation; sai dung lượng hoặc giả mạo thiết bị; thiết bị bị khóa ghi; lỗi mã hóa hoặc cơ chế bảo vệ; lỗi phần cứng vật lý.

Mỗi kết luận phải có mức độ tin cậy, bằng chứng hỗ trợ, giả thuyết thay thế và phép thử tiếp theo để xác nhận.

#### 2.4. Xác minh tính xác thực

Dấu hiệu: dung lượng báo cáo không tương ứng dung lượng thực; model, firmware, serial hoặc VID/PID không nhất quán; controller hoặc NAND khác với cấu hình được công bố; firmware có dấu hiệu giả mạo thông tin nhận dạng; dữ liệu bị ghi đè vòng lặp khi vượt dung lượng thực; thông tin SMART bất thường hoặc không phù hợp với thiết bị.

Phân biệt rõ thiết bị giả dung lượng, firmware bị sửa đổi và thiết bị chính hãng nhưng lỗi phần cứng. Một dấu hiệu đơn lẻ không đủ để kết luận hàng giả.

### Phase 3 - Chọn và thực hiện phương án phục hồi

Chọn phương án dựa trên nguyên nhân, không dựa riêng vào triệu chứng.

- Lỗi kết nối và nhận dạng: đổi cổng, cáp, adapter hoặc máy kiểm tra; xác minh bus và trạng thái thiết bị trước khi sửa dữ liệu.
- Lỗi filesystem hoặc phân vùng: ưu tiên tạo ảnh khi cần bảo toàn dữ liệu; sau đó dùng công cụ phục hồi tương ứng.
- Lỗi đọc và bad sector: ưu tiên công cụ imaging có khả năng bỏ qua vùng lỗi, lưu mapfile và tiếp tục đọc sau khi gián đoạn.
- Lỗi chỉ đọc: phân biệt thuộc tính phần mềm, chính sách hệ điều hành, trạng thái bảo vệ vật lý và cơ chế khóa ghi của controller.
- Lỗi controller/firmware: nhận dạng chính xác controller, phiên bản và cấu hình NAND; chỉ dùng MPTool tương thích. Không thử firmware ngẫu nhiên theo tên thương hiệu hoặc dung lượng.
- Nghi giả dung lượng: kiểm tra ghi/đọc toàn bộ dung lượng sau khi xác nhận không cần giữ dữ liệu. Không coi format thành công là bằng chứng dung lượng thật.
- Lỗi vật lý: dừng thao tác phần mềm có thể làm tăng rủi ro; đánh giá sửa phần cứng hoặc loại bỏ thiết bị.

Mỗi phương án phải ghi rõ điều kiện áp dụng, rủi ro, công cụ, kết quả kỳ vọng và tiêu chí dừng.

### Phase 4 - Thử phương án thay thế

Chỉ chuyển sang phương án khác khi: phương án hiện tại thất bại hoặc không tạo đủ bằng chứng; đã ghi lại lỗi và trạng thái trước/sau; phương án tiếp theo có cơ sở kỹ thuật rõ ràng; rủi ro không vượt quá mức chấp nhận của phiên.

Có thể thay đổi môi trường: Windows (nhận dạng thiết bị, Disk Management, công cụ nhà sản xuất, firmware utility); Linux (`smartctl`, `nvme-cli`, `lsusb`, `lsblk`, `dmesg`, `ddrescue`, `badblocks`, công cụ filesystem); môi trường live Linux (tách biệt driver, mount tự động, hành vi OS đang chạy); hệ điều hành hoặc máy khác (kiểm tra nhận dạng độc lập); công cụ chuyên dụng (chỉ khi đã xác minh nguồn và tương thích).

Việc đổi OS nhằm loại trừ nguyên nhân môi trường, không phải một cách tự động sửa lỗi phần cứng.

Không lặp vô hạn các phép thử giống nhau. Sau mỗi thất bại, phải cập nhật giả thuyết và đánh giá xem có bằng chứng mới đủ để thử tiếp hay không.

### Phase 5 - Kiểm định sau phục hồi

Thiết bị chỉ được đánh dấu phục hồi thành công khi vượt qua các phép thử phù hợp.

- Chung: nhận dạng ổn định qua nhiều lần kết nối; dung lượng và thông tin thiết bị nhất quán; không phát sinh lỗi I/O hoặc ngắt kết nối bất thường; ghi, đọc và xác minh dữ liệu thành công.
- HDD: đọc SMART sau phục hồi; chạy self-test phù hợp; kiểm tra bề mặt khi an toàn; so sánh các chỉ số lỗi trước và sau.
- SSD/NVMe: đọc health log và error log; kiểm tra trạng thái media, wear indicators và nhiệt độ; xác minh đọc/ghi theo quy trình không gây rủi ro không cần thiết.
- USB/thẻ nhớ: ghi/đọc dữ liệu thử trên toàn bộ dung lượng thực có thể sử dụng; xác minh hash hoặc nội dung dữ liệu; kiểm tra dung lượng thực và khả năng đọc lại sau khi tháo/cắm lại; không tiếp tục sử dụng nếu lỗi tái phát hoặc kết quả không nhất quán.

Trạng thái cuối cùng: `PASS` (vượt qua kiểm định), `PASS_LIMITED` (dùng được nhưng có giới hạn rõ ràng), `FAIL`, `REPAIR_REQUIRED` (cần sửa chữa phần cứng hoặc chuyên môn khác), `UNRESOLVED` (chưa đủ bằng chứng), `RETIRED` (loại khỏi sử dụng).

Không sử dụng thiết bị `PASS_LIMITED` cho dữ liệu duy nhất hoặc quan trọng.

## 3. Bộ công cụ tham chiếu

| Nhu cầu | Công cụ tham chiếu |
|---|---|
| SMART và health log | smartmontools, nvme-cli |
| USB enumeration | USB Device Tree Viewer, usbutils |
| Phục hồi phân vùng | TestDisk |
| Khôi phục file | PhotoRec |
| Tạo ảnh từ thiết bị lỗi | GNU ddrescue |
| Kiểm tra filesystem | Công cụ native của filesystem/OS |
| Kiểm tra bề mặt HDD | badblocks hoặc công cụ phù hợp với thiết bị |
| Kiểm tra dung lượng flash | H2testw, F3 |
| Kiểm tra USB giả dung lượng | F3 và phép thử ghi/đọc toàn bộ |
| Phục hồi controller USB | MPTool tương ứng controller, firmware utility của nhà sản xuất |
| Phân tích sự kiện Windows | Event Viewer, Device Manager, PowerShell |
| Quản lý kết quả | CSV hoặc SQLite |

Không áp dụng máy móc một công cụ cho mọi loại thiết bị. `badblocks` không phải công cụ mặc định để kiểm tra SSD hoặc USB flash; bài kiểm tra ghi có thể tạo lượng ghi lớn và phá hủy dữ liệu.

## 4. Quy tắc an toàn bắt buộc

1. Nhận dạng thiết bị bằng nhiều thuộc tính; không dựa duy nhất vào số Disk hoặc ký tự ổ.
2. Trước thao tác phá hủy, hiển thị model, serial, dung lượng và thiết bị đích để người vận hành xác nhận.
3. Không chạy `clean`, format, ghi đè, firmware flashing hoặc các thao tác phá hủy nếu mục tiêu cứu dữ liệu chưa được giải quyết.
4. Không mount hoặc sửa filesystem trên nguồn khi cần bảo toàn bằng chứng; ưu tiên thiết bị chặn ghi và bản ảnh phù hợp.
5. Không tự động lặp lệnh ghi khi thiết bị đang treo, quá nóng hoặc mất kết nối.
6. Không tải và chạy firmware từ nguồn không xác minh được.
7. Mọi thao tác R2/R3 phải có ghi nhận trước/sau và điều kiện dừng.
8. Không tuyên bố "đã sửa" chỉ vì lệnh kết thúc thành công; phải kiểm định đầu ra.
9. Nếu có dấu hiệu lỗi cơ học, ưu tiên dừng sớm hơn là tiếp tục stress test.
10. Không ghi thông tin nhạy cảm hoặc nội dung dữ liệu người dùng vào log không cần thiết.

## 5. Kiến trúc triển khai skill

Skill điều phối quy trình, không thay thế các công cụ chuyên dụng.

Đầu vào: mô tả lỗi, mục tiêu, thiết bị, hệ điều hành và dữ liệu đã thu thập.

Bộ điều phối: 1. Xác định mục tiêu. 2. Xây dựng hồ sơ thiết bị. 3. Chọn các bước kiểm tra không phá hủy. 4. Tổng hợp kết quả và đánh giá giả thuyết. 5. Đề xuất hành động tiếp theo. 6. Yêu cầu xác nhận khi thao tác có tính phá hủy. 7. Kiểm định và tạo báo cáo cuối.

Lưu trữ kết quả: một hồ sơ cho mỗi thiết bị, chứa mã định danh phiên, thông tin thiết bị, công cụ và phiên bản, kết quả, lỗi, hành động đã chạy và trạng thái cuối cùng.

Tự động hóa: ưu tiên CLI/API và khả năng xuất log của công cụ hiện có. Chỉ viết script cho việc phát hiện thiết bị, chuẩn hóa đầu ra, điều phối quy trình, lưu kết quả và quản lý trạng thái. Không tự viết một hệ thống sửa chữa tổng quát thay cho các công cụ chuyên dụng.

## 6. Kế hoạch triển khai theo giai đoạn

- GĐ 1 - MVP chẩn đoán an toàn: chuẩn hóa đầu vào và mục tiêu; kiểm kê thiết bị; thu thập thông tin nhận dạng, SMART và log; phân loại lỗi và tạo báo cáo; không tự thực hiện thao tác phá hủy.
- GĐ 2 - Phục hồi theo loại thiết bị: nhánh HDD, SSD/NVMe, USB và thẻ nhớ; tích hợp công cụ phục hồi phù hợp; chuẩn hóa tiêu chí dừng và kết quả; bước xác nhận riêng cho mỗi hành động ghi/xóa.
- GĐ 3 - Xử lý hàng loạt: quản lý nhiều thiết bị; lưu lịch sử và so sánh kết quả qua các lần kiểm tra; tự động phân nhóm thiết bị theo triệu chứng; không chạy đồng thời các thao tác phá hủy trên nhiều thiết bị nếu chưa có kiểm soát an toàn.
- GĐ 4 - Kiểm định và hoàn thiện: bộ ca kiểm thử cho từng nhóm lỗi; kiểm tra nhận dạng sai thiết bị, thiết bị ngắt kết nối và lỗi công cụ; xác minh quy trình không vượt qua bước xác nhận; đánh giá độ tin cậy của kết luận và tính đầy đủ của báo cáo.

## 7. Định dạng báo cáo cuối cùng

Mỗi thiết bị phải có: mục tiêu xử lý; thông tin nhận dạng; triệu chứng và bằng chứng; chẩn đoán cùng mức độ tin cậy; các phương án đã thử; công cụ, phiên bản và kết quả; các thay đổi đã thực hiện; kết quả kiểm định sau phục hồi; trạng thái cuối cùng; hạn chế còn tồn tại và khuyến nghị sử dụng.

Kết luận phải phân biệt rõ điều đã xác minh, suy luận kỹ thuật và điều chưa thể xác định.

## 8. Tiêu chí hoàn thành skill

- Có thể phân loại thiết bị và lỗi mà không cần sửa chữa ngay.
- Không tự ý chạy thao tác phá hủy.
- Biết khi nào cần chuyển từ phần mềm sang chẩn đoán phần cứng.
- Ưu tiên đúng công cụ hiện có thay vì viết lại chức năng.
- Có khả năng dừng khi không đủ bằng chứng hoặc rủi ro quá cao.
- Không coi format thành công là phục hồi thành công.
- Mỗi kết luận có bằng chứng, tiêu chí kiểm định và trạng thái cuối.

---

# Decisions settled with the user (2026-10-19)

- Scope: build GĐ 1-4 (user chose full scope over the recommended GĐ 1+2).
- Stack: Python >= 3.10, stdlib only at runtime (subprocess, json, sqlite3, argparse, hashlib). No pip deps at runtime. pytest for tests.
- Collectors: smartctl 7.x is the single SMART/NVMe collector on both OSes (`-j`); Windows enumeration via `powershell.exe` 5.1 Storage cmdlets/CIM to JSON; Linux via `lsblk -J -O -b`, `udevadm`, `lsusb`/sysfs. nvme-cli optional on Linux only.
- Case store: SQLite + per-session JSON evidence under `~/.recovery-storage/` (outside repo; contains serials). Overridable by `--home` / env var.
- Repo layout: skill lives at `./recovery-storage/` (SKILL.md, references/, scripts/); junction `~/.claude/skills/recovery-storage` -> that folder.
- Git: repo initialised on `main`.
- Plan approved 2026-10-19 with: guard hook (PreToolUse, skill frontmatter, leaky second barrier) as phase 08; operator-attested H2testw counts for PASS (labelled ATTESTED); risk-based triage (failing-but-readable HDD -> SOFTWARE_RECOVERY_CANDIDATE + image-first by default; HARDWARE_DIAGNOSIS_REQUIRED when data irreplaceable AND risk tolerance low, or media counters rise within the session; STOP_UNSAFE on mechanical-noise / not-spinning); session fields `--data-value irreplaceable|important|replaceable|unknown` and `--risk-tolerance low|medium|high`; Python 3.10 via `uv python install 3.10`, suite on 3.10 and 3.12. Details: plan.md "Decisions 2026-10-19".

# Facts verified on this machine (Windows 11 26200, smartctl 7.5, non-admin, 2026-10-19)

- `smartctl --scan-open -j` lists NVMe disks as `/dev/sda`, `/dev/sdb` (type nvme), exit 0 without admin.
- `smartctl -j -i /dev/pd1` addresses `Get-Disk` Number 1 (Samsung 980 PRO), exit 0. `/dev/pdN` == Disk Number N.
- Windows `Get-Disk`/`Get-PhysicalDisk` `SerialNumber` for NVMe is the EUI-64 string (`0025_38XX_XXXX_XXXX.`), NOT the smartctl `serial_number` (`S6Z1XXXXXXXXXXX`). Join key: `Get-Disk.UniqueId` (`eui.002538XXXXXXXXXX`) == smartctl `nvme_namespaces[].eui64` (oui=9528 -> `002538`, ext_id -> 10 hex digits), plus model and exact byte size.
- `Get-Disk.Size` == smartctl `user_capacity.bytes` exactly (1000204886016). `Win32_DiskDrive.Size` is geometry-truncated (1000202273280) and `InterfaceType` reports NVMe as `SCSI` -> do not use those two fields.
- `Get-StorageReliabilityCounter` without admin fails: "Access to a CIM resource was not available to the client." -> optional, admin-only.
- PnP parent chain via `Get-PnpDeviceProperty -KeyName DEVPKEY_Device_Parent` works without admin.
- Event log: provider `Ntfs` id 55 = "A corruption was discovered in the file system structure on volume %1". Other storage IDs not confirmed from provider manifests -> query by provider name + level (Error/Warning) + time window, do not hard-code an ID list as the only filter.
- Git Bash rewrites `/dev/sda` into `C:/Program Files/Git/dev/sda` unless `MSYS_NO_PATHCONV=1`. Python `subprocess` with argv list is unaffected.
- PowerShell 5.1 `>` writes UTF-16LE; capture tool output via subprocess, not shell redirection.
- smartctl missing device: exit_status 1 with message severity error "Unable to detect device type".
- Real smartctl `-x -j` NVMe samples: raw originals git-ignored under `research/samples/`; redacted copies in `recovery-storage/scripts/tests/fixtures/` (`SOURCES.md`).
- USB stick `VID_ABCD&PID_1234` "General UDisk": `smartctl -j -x /dev/pd2` exit 1, message "Unknown USB bridge [0xabcd:0x1234]"; `-d sat` non-admin exit 2 "Open failed, Error=5" = needs elevation (collection status `needs_elevation`, not a device failure). NVMe needs no admin.
- USB disks: Get-Disk `SerialNumber` is a 1-char junk string (`"\t"`, `"["`) while Get-PhysicalDisk `SerialNumber` is null for the same disk -> serial_trust absent. The PnP `USB\VID_xxxx&PID_xxxx\<instance>` node has a Windows-generated instance id (contains `&`) -> no USB serial. Get-Disk `UniqueId` for USB is `USBSTOR\...:<HOSTNAME>` (host-specific, not a cross-host identity).
- USB stick: MBR partition type 7 present but NO volume object (filesystem not recognised) -> evidence for `raw-or-unreadable-fs`. SD card in reader `VID_05E3&PID_0751`: FAT32 volume, MBR `Signature` 0 (Signature 0 never counts as an identity match); the reader hides the card's own identity.
- PS 5.1 `Select-Object` emits enum fields as strings here (`BusType` "USB"/"NVMe", `HealthStatus` "Healthy") -> parsers accept string and numeric forms.
- `win-events`: providers not registered on a host (USBSTOR, sdbus, fastfat) are a normal empty case (`NoMatchingProvidersFound` ignored by the script).
- [UNVERIFIED] VID 0xABCD / PID 0x1234 is commonly reported on no-name/counterfeit sticks: weak authenticity hint in references only, never a rule.
- `wsl --mount <Disk> --bare` exists on this machine (attaches whole disk to WSL2 without mounting).
