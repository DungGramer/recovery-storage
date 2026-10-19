# Amendment 02 (2026-10-19): review round 2 (identity by operator, last write, guard tokenizer)

Approved by the user after the second code review (findings N1-N16). Spec for `test-designer` (tests first) and
the implementer. Reproductions written by the reviewer (use them as the source of the cases):
`C:\Users\DUNGGR~1\AppData\Local\Temp\claude\D--Downloads-Documents-CODE-recovery-storage\bfb532d0-e3c0-4903-b95a-b5f625927a8d\scratchpad\{scen.py, scen2.py, selftest.py, guard_corpus.py}`.

## A. Identity changes only by the operator (N1, N4, N16)

- `gate close` never changes a device fingerprint. If the device is not found exactly (not attached, conflict,
  ambiguous, or only its on-media id differs), the gate is closed with `identity_drift = 1` and a `drift_reason`
  (`media-id-changed` when exactly one attached disk is the same hardware with another MBR signature / GPT guid,
  else `device-changed`). The close output prints the operator command `device link <observation> <device>`.
- `device link <observation> <device>` and `device link <observation> --new` require the operator at the console
  (amendment 01 mechanism; prompt `Type YES to link observation <obs> (<model>, <bytes> bytes, <os_path>) to
  <device>: `; no console -> exit 3 `operator-console-required`; answer not `YES` -> exit 3 `operator-declined`).
- An operator link to an existing device: learns the observation's on-media ids when the hardware matches (model,
  bytes, USB ids, trusted serial / EUI / WWN), and clears `identity_drift` on every closed gate of that device whose
  close happened before the linked observation. A link to a device with different hardware is refused exit 3
  `hardware-mismatch` (use `--new`).
- Ambiguous inventories (exit 5, B16) still need `device link`; tests answer `YES`.

## B. Last write (N2, N9)

- `last_write_ts(device)` = the latest of: `closed_ts` of a closed gate whose kind writes the source, and
  `closed_ts` of an aborted gate whose kind writes the source and that had been confirmed (`confirmed_ts` set),
  across all sessions; None if no such gate.
- Data state: `secured` / `waived` count for a write gate only if recorded after `last_write_ts(device)`.
  A stale secured state from before the last write -> `data-not-secured` (scenario: S1 secured + format gate closed;
  S2 data-recovery on the same device -> refused).
- Verdict window start = max(session start, `last_write_ts(device)`).

## C. Secured needs an image gate (N15)

- `session data-state <s> <d> secured --evidence E` additionally requires a gate of kind `image-ddrescue` on that
  device, state `closed`, outcome `success`, closed in this session, and the evidence ingested after that gate was
  confirmed. Missing -> exit 3 `image-gate-missing`. (`secured --attested` and `waived` unchanged.)
- Test helper `secure()`: open + operator-confirm + close an `image-ddrescue` gate (dest = another attached device)
  before ingesting the full-coverage mapfile.

## D. Snapshot identity (N7)

- `collect` (and gate before/after snapshots) attach a smartctl result to a device only when the answering
  identity matches it (exact / probable / weak), or when model and bytes are equal and no strong id differs;
  otherwise exit 3 `identity-conflict` and nothing is stored. The check also runs on the `-d sat` retry result.

## E. Self-test hours wrap (N8)

- ATA self-test `lifetime_hours` is 16-bit. With `latest_poh` = power-on hours of the snapshot, an entry is inside
  the window when `(latest_poh - h) % 65536 <= latest_poh - since_hours`; "after" ordering between entries uses that
  distance. Cases: since 70000, pass logged at 10000 (60000 h ago) -> not counted; fail logged at raw 4564 (= 70100)
  after a pass at raw 4500 -> PASS refused.

## F. SSD read verify (N13)

- For ssd-sata / nvme / external-ssd, an f3read pass counts as read verify only with coverage >= the flash coverage
  parameter (`verdict.CAPACITY_COVERAGE`) of the device bytes; ddrescue needs the full-coverage mapfile (amendment
  01); attested pass still counts (plan decision Q3).

## G. Operator command text (N5)

- `--reason`, `--note`, `--file` and `--home` values that would be echoed into a printed operator command must not
  contain `"` `$` backtick `;` `&` `|` `<` `>` or a newline: exit 2 `unsafe-characters` before anything is stored.

## H. Guard tokenizer (N3, N10, N11)

Must BLOCK (no open gate): `sudo -n mkfs.ext4 /dev/sdb1`, `sudo -E wipefs -a /dev/sdb`, `sudo -S dd if=x of=/dev/sdb`,
`sudo -u root -E mkfs.vfat /dev/sdb1`, `env -i wipefs -a /dev/sdb`, `xargs -t mkfs.ext4`, PowerShell
`$null = Clear-Disk -Number 2 -RemoveData -Confirm:$false`, `$r = Format-Volume -DriveLetter E`,
`echo x &> /dev/sdb`, `cat img > /dev/disk/by-id/usb-X`, `cp img /dev/mapper/vg-lv`, `cat img > /dev/md0`,
`cat img > /dev/dm-0`, `cat img > /dev/loop0`.
Must ALLOW: `command -v mkfs.ext4`, `command -v ddrescue f3probe`, a heredoc whose body mentions tools
(`cat <<'EOF' > notes.md` / body line `` run `mkfs.ext4` later `` / `EOF`), a multi-line `git commit -m "..."` whose
message mentions mkfs / Clear-Disk, `cp /dev/sdb disk.img`, `pv /dev/sdb > disk.img`, `parted /dev/sdb print free`,
`parted -s /dev/sdb unit B print`, `fsck -N /dev/sdb1`.
Rules: per-wrapper value-flag tables compared case-sensitively; `name =` / `$name =` assignment prefixes skipped;
`command -v|-V` never executes; tokenize the whole text (newlines are separators outside quotes) and drop heredoc
bodies; `cp`/`tee`/`pv` judged only by the write target; `&>` and `>&` are redirects; device targets include
`/dev/disk/by-*`, `/dev/mapper/*`, `/dev/md*`, `/dev/dm-*`, `/dev/loop*`.
