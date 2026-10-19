# Research Report: Storage health rules (SMART/NVMe) for deterministic verdicts
Date: 2026-10-19 (rev 2: drivedb whitelist and nvmeprint keys verified from source; Google 2007 numbers removed)

## Summary
Build verdicts from STRONG signals (media error counters and their growth between two snapshots, NVMe critical_warning, spare below threshold) and treat temperature, wear estimates, err-log counts, CRC as WEAK or context. A clean SMART report must not give high-confidence "healthy": Backblaze found 23.3% of failed drives showed none of the five stats. Return `unknown` whenever a needed field is absent.

Wear attributes are only interpretable through a (attribute ID + smartctl name + model family) whitelist (section 2). drivedb gives NAMES and raw formats only, not normalized semantics; the semantics below are inferred from the names and from drivedb comments, and flagged where not stated in source.

Verified this session: Backblaze 2016 post; drivedb.h (main branch); nvmeprint.cpp (main branch); Intel NVMe notes. NOT verified: Google 2007 paper (PDF unreadable here, so no numbers cited; qualitative only), NVMe Base Spec PDF, Seagate packed-raw layouts.

## Method
Backblaze blog; GitHub API (default branch `main`); raw.githubusercontent.com for `drivedb/drivedb.h` (7699 lines) and `src/nvmeprint.cpp`. Note `src/drivedb.h` 404s; the file lives at `drivedb/drivedb.h`. Line numbers below refer to those files as fetched 2026-10-19 and will drift with commits (pin a commit when encoding the table).

## Findings

### 1. HDD SMART predictors
- Backblaze (Klein, 2016-10-06, 67,814 drives, one data center): any raw > 0 on SMART 5, 187, 188, 197, 198 -> 76.7% of failed drives vs 4.2% of operational drives; 23.3% of failed drives had none. [1]
- Same post: no single stat appears in all failures; a lone non-zero value may mean little; most are cumulative so time window matters, 197 is the exception (can drop); 197 and 198 strongly correlated, others largely independent; some vendors expose only one of 197/198; may not generalize. [1]
- Google 2007 (Pinheiro et al.) [2]: not parsed this session. Only the widely known qualitative claims are safe to restate (some failed drives show no SMART warning; temperature is a weak predictor). Do not quote numbers until the PDF is read.
- Rule: non-zero raw on 5/187/197/198 -> warning; growth between snapshots matters more than absolute count.
- 188 Command_Timeout: Seagate raw may pack several counters (weak secondary source [3], layout unverified). Use only when smartctl shows a plausible single count; else weak/unknown.
- Seagate 1/7/195 raw values are packed and not error counts (unverified vs Seagate docs). Judge by normalized VALUE vs THRESH only; VALUE <= THRESH on a pre-fail attribute is a hard trip.
- 199 UDMA_CRC_Error_Count: link/cable/bridge, not media. Alt hypothesis cable/port/USB bridge; do not raise a media verdict from it. Note drivedb names it SATA_FIS_CRC_Errors / SATA_CRC_Error for some SSD families (lines ~401, ~2427).

### 2. SATA SSD wear whitelist (drivedb.h, `drivedb/drivedb.h`)
Direction legend: REM = normalized VALUE counts down from 100 as life remains (name says Remain/Left/Remaining/Wearout); USED = name says Used (VALUE direction NOT stated; exclude from % remaining logic until confirmed); RAW-ONLY = not a life percentage.

| ID | smartctl name | drivedb scope (line) | Meaning | Direction |
|---|---|---|---|---|
| 177 | Wear_Leveling_Count | DEFAULT preset (99), Samsung usage | wear leveling, normalized = life left (convention; not stated in drivedb) | REM (assumed) |
| 233 | Media_Wearout_Indicator | DEFAULT preset (145); many Intel presets keep it commented out (e.g. 1548, 1564) | Intel wearout, normalized 100 -> 1 (convention) | REM (assumed) |
| 231 | SSD_Life_Left | SandForce (1054), Maxio variant 1 (639), others (700, 742, 907, 1165, 1212, 2142) | life left | REM |
| 231 | Percent_Lifetime_Remain | ATP SATA III Value Line (372) | life remaining | REM |
| 231 | Life_Remaining_Percent / Lifetime_Left | lines 230, 309, 331 | life remaining | REM |
| 202 | Percent_Lifetime_Remain | Crucial/Micron Client SSDs (592, comment "norm = max(100-raw,0); raw = percent_lifetime_used"); Micron 5100/52x0/5300/5400 (847, comment "Remaining endurance, trips at 10%"); line 880 | normalized = remaining, raw = used | REM |
| 202 | Percent_Lifetime_Used / Perc_Rated_Life_Used | ATP Superior (402), Crucial RealSSD C300 and m4 families (437, 475, 508, 531) | used | USED (unverified direction) |
| 173 | Percent_Lifetime_Remain | Intel 730 / DC S35x0/3610/3700 (1857, comment "100 - Percentage Used Endurance Indicator") | remaining | REM |
| 173 | Percent_Life_Used / Drive_Life_Used% | Sandisk ESS families (2486, 2512-2516) | used | USED |
| 173 | Wear_Leveling_Count / Ave_Block-Erase_Count / Avg_Write/Erase_Count | 461, 494, 526, 580, 2340, 2420 | erase-count statistics | RAW-ONLY (not a percentage) |
| 169 | Remaining_Lifetime_Perc | Innodisk (1433), line 1490 | remaining | REM |
| 169 / 248 | Lifetime_Remaining% | StorFly CFast (1074-1075) | remaining | REM |
| 177 | Lifetime_Remaining% / DriveLife_Remaining% | Sandisk ESS (2486, 2518) | remaining | REM |
| 233 | Remaining_Lifetime_Perc | Indilinx Barefoot 3 (1307), line 1343 | remaining | REM |
| 233 | Flash_Writes_GiB / Flash_Writes_32MiB | 1167, 1213, 1454 | NAND writes | RAW-ONLY |
| 230 | Media_Wearout_Indicator | SandForce (932) | wearout | REM (assumed) |
| 232 | Available_Reservd_Space | DEFAULT (144) | spare blocks % | not wear |
| 241/242 | Total_LBAs_Written/Read (DEFAULT 148-149); Host_Writes_GiB; Host_Writes_32MiB; Lifetime_Writes_GiB | per preset | unit differs per family | RAW-ONLY, unit from name |

Encoding rules:
- Match on (name, model family); same ID with different names must not share logic (233 is Media_Wearout_Indicator, Remaining_Lifetime_Perc, Flash_Writes or NAND_Write_Sector_Cnt depending on preset; 202 is Remaining on some Crucial/Micron and Used on others).
- Unknown name/family -> `unknown` for wear; never infer. Treat USED rows as unusable for "% remaining" until a sample is checked.
- Prefer ATA Device Statistics page 0x07 "Percentage Used Endurance Indicator" (`smartctl -x`; JSON `ata_device_statistics`): 0 = new, 100 = projected end of life, may exceed 100 [4]. Not present on older drives.
- Confirm VALUE direction empirically on a fixture for each whitelisted family (VALUE=100 on a new drive and falling) before shipping.

### 3. NVMe health (verified against nvmeprint.cpp, smartmontools main) [5]
JSON paths (root `nvme_smart_health_information_log`, nvmeprint.cpp line 469):
- `critical_warning` (474, integer bitmask), `available_spare` (484), `available_spare_threshold` (486), `percentage_used` (492), `data_units_written` (503), `media_errors` (525), `num_err_log_entries` (527), `warning_temp_time` (532), `critical_comp_time` (536), `temperature` (Celsius = Kelvin - 273, ~line 478). Time fields printed only if id-ctrl threshold or value is non-zero (530, 534).
- Decoded bit booleans under `smart_status.nvme` (430-457): `value`, `spare_below_threshold` (0x01), `temperature_above_or_below_threshold` (0x02), `reliability_degraded` (0x04), `media_read_only` (0x08), `volatile_memory_backup_failed` (0x10), `persistent_memory_region_unreliable` (0x20, text: "persistent memory region has become read-only or unreliable"), `other` (bits 6-7). Bit 5 meaning therefore confirmed in smartmontools source; NVMe spec PDF itself not opened.
- Thresholds: `nvme_composite_temperature_threshold.warning` / `.critical` (WCTEMP/CCTEMP minus 273, 340, 344) and `temperature.op_limit_max` / `critical_limit_max`; emitted only when the controller reports non-zero (339, 343). Absent -> temperature verdict `unknown`.
- Data Units Written unit: smartctl multiplies by `1000*512` (501-507) and exports `host_writes.bytes_per_unit = 512000`. Counter is 128-bit; clamp-to-uint64 used for display (use Python int from the JSON). Intel/libnvme describe the same unit [6].
- percentage_used: vendor endurance estimate, 100 = rated endurance consumed, may exceed 100, reported up to 255 [6].
- spare vs threshold: spare < threshold sets bit 0 (strong). num_err_log_entries is lifetime count and often benign (weak; inspect log entries). media_errors > 0 is an unrecovered integrity error count; growth is strong.

### 4. TBW / host writes
- Rated TBW comes from vendor datasheets per model; not readable from the device. Never output TBW remaining without a user-supplied datasheet value.
- NVMe: host_written_bytes = data_units_written * 512000 (nvmeprint.cpp 501-507).
- SATA: prefer devstat "Logical Sectors Written" (standardized) x logical sector size; attribute 241 only with a name-defined unit (LBAs, GiB, 32MiB; table above). Report as host writes, not NAND wear or write amplification.

### 5. HDD temperature (heuristic)
- No authoritative per-vendor threshold retrieved. Heuristic bands: <=45C ok, 46-54C watch if sustained, >=55C concerning, >=60C critical (check drive datasheet; many 3.5" HDDs spec 60C max). Temperature is weak evidence for a health verdict but strong for an immediate action (cool, pause heavy imaging). Use `temperature.current` from smartctl JSON (attribute 190/194 raw packs min/max on some vendors).

### 6. Deterministic verdict design
Verdicts: healthy, watch, degraded, failing, unknown. Each result: {verdict, confidence, evidence[], alternative_hypothesis, next_test}.
- STRONG: overall-health FAILED; pre-fail VALUE <= THRESH; NVMe critical_warning bits 0/2/3/4/5; spare < threshold; growth of 5/187/197/198/media_errors across snapshots; self-test read failure.
- MEDIUM: static non-zero 5/187/197/198 (Backblaze); media_errors > 0 static; percentage_used >= 90 or devstat endurance >= 90; failed self-test.
- WEAK/context: temperature, 188, 199, 10, num_err_log_entries, power-on hours, unsafe shutdowns, USED-direction wear rows, RAW-ONLY rows.
Mapping (first match wins):
1. failing (high confidence): health FAILED, pre-fail trip, critical_warning bit 0 or 3, spare < threshold, or rising counters across snapshots with read errors.
2. degraded (medium): any non-zero 5/187/197/198, media_errors > 0, bit 2/4/5, percentage_used >= 100, failed self-test. Alt: old stable remap; cable for 199.
3. watch: percentage_used 80-99, spare falling above threshold, high temp, 199/188 non-zero, err-log entries.
4. healthy: expected strong/medium signals present and clean. Cap HDD confidence at medium; next_test = extended self-test or full surface read.
5. unknown: SMART not exposed (USB bridge, SD, USB flash), required field missing, or family not in whitelist. For flash/SD next_test = full read + hash compare.
Each rule declares required fields; a missing field skips the rule, never defaults to 0.

Two-snapshot delta: delta = after - before on 5, 187, 197, 198, media_errors, percentage_used, num_err_log_entries. Positive delta on 5/187/197/198/media_errors = active degradation; escalate at least to degraded, failing if several rise or growth continues at idle. Falling 197 with rising 5 is a remap (still degradation). Invalid pair (serial changed, power_on_hours decreased, counters fell except 197) -> `unknown`. Store timestamp, serial, firmware, smartctl version, bridge type, command used so absent != zero.

## Sources
[1] https://www.backblaze.com/blog/what-smart-stats-indicate-hard-drive-failures/ (read)
[2] https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf (fetched, unreadable here)
[3] https://www.netdata.cloud/guides/smartctl-disk-monitoring/smartctl-command-timeout/ (weak, secondary)
[4] https://lists.opensuse.org/opensuse/2013-07/msg00167.html (smartctl man page excerpt, devstat endurance); sample: https://www.smartmontools.org/attachment/ticket/106/Ticket106-sample.txt
[5] https://raw.githubusercontent.com/smartmontools/smartmontools/main/src/nvmeprint.cpp (read)
[6] https://www.intel.com/content/www/us/en/support/articles/000056596.html ; https://www.mankier.com/2/nvme_smart_log
[7] https://raw.githubusercontent.com/smartmontools/smartmontools/main/drivedb/drivedb.h (read; GitHub API says default branch `main`)

## Unresolved questions
- Google 2007 findings: extract PDF text, then add verified numbers or leave qualitative.
- NVMe Base Spec: Data Units Written definition (1000 x 512) and critical_warning bit 5 are confirmed only via smartctl source; open the spec section "SMART / Health Information (Log Identifier 02h)" for primary confirmation.
- VALUE direction (remaining vs used) for 202/173 "Used" rows and for 177/233 defaults is inferred, not stated in drivedb; verify on fixtures.
- Seagate 188 and 1/7/195 packed layouts: no authoritative source.
- HDD temperature thresholds: need vendor datasheets.
- Pin a drivedb commit hash and re-derive line numbers when encoding the table.
