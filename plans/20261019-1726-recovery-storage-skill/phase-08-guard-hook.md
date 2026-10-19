# Phase 08 - Guard hook: second barrier against ungated destructive commands

## Context Links
- Decision Q1 (2026-10-19): add a PreToolUse hook. Verified by main agent from code.claude.com/docs/en/hooks.md and skills.md:
  - SKILL.md frontmatter `hooks:` -> `PreToolUse: - matcher: "Bash|PowerShell"  hooks: - type: command  command: "..."`.
  - Skill hooks register when the skill is invoked and stay active for the REST OF THE SESSION.
  - Input JSON on stdin has `tool_name` and `tool_input.command` (same field for PowerShell).
  - Deny = exit code 2 (stderr shown to Claude) or JSON `permissionDecision: deny`.
  - On Windows, shell-form hook commands run in Git Bash when installed.
  - `${CLAUDE_SKILL_DIR}` documented for skill markdown / allowed-tools, NOT confirmed inside hook commands.
  - UNVERIFIED: whether a deny is enforced under `bypassPermissions` (docs imply hooks run before the permission prompt). The user runs bypass permissions.
- Gate states and store: [phase-04](phase-04-gate-and-verdict.md); home resolution: [phase-01](phase-01-foundation-runner-store-session.md); SKILL.md: [phase-06](phase-06-skill-md-and-references.md); junction: [phase-07](phase-07-scenarios-hardening-install.md)

## Overview
- Priority: P1. Status: Todo. Depends on 04 (gates), 06 (SKILL.md), 07 (junction installed for the live test).
- Separate phase, not folded into 07: it is a new mechanism with its own artifact (hook script + frontmatter), its own pattern corpus, and a live test that depends on the session permission mode. Folding it into 07 would mix "prove existing parts" with "add a new part" and hide whether the hook works.
- Deliverables: `scripts/guard_hook.py`, `rslib/guard_patterns.py`, SKILL.md `hooks:` block, leak list in SKILL.md and `references/safety-and-gates.md`.

## Key Insights
- This is a deny-list over arbitrary shell text, so it is LEAKY by construction. It is a second barrier behind the gate protocol, SKILL.md rules and permission prompts, never the primary control. Known leaks (stated in SKILL.md verbatim):
  - obfuscation: variables, aliases, `eval`, string building, base64 piped to a shell (undecodable `-EncodedCommand` is closed by H5b: treated as destructive-class);
  - script files: `python x.py`, `./x.sh`, `x.ps1`, batch files;
  - GUI tools (H2testw, MPTool, Disk Management, vendor utilities) and tools not in the list;
  - MCP / non-Bash tools; commands the user runs outside Claude;
  - any `open` gate unlocks every matched command on every device (the hook cannot map command paths to devices reliably);
  - sessions where the skill was never invoked have no hook.
- Deliberate scope: the hook targets commands that write to a device or change device state. Gated R1 kinds that only read or change OS state (`badblocks` read-only, `wsl --mount --bare`, `mountvol`) are not hook-matched; the gate protocol in SKILL.md still applies to them.
- Session-wide scope: once the skill is invoked, unrelated destructive disk commands later in the same session are blocked until a gate is open or a new session starts. Accepted consequence; the deny message says so.
- Exit 2 means deny for EVERY Bash/PowerShell call. Python exits 2 when the script file is missing ("can't open file"). A bare `python <path>` hook command with a wrong path would therefore block the whole session: the command must check the file first and exit non-2 when missing.
- Fail-closed only where it matters: a matched destructive command plus an unreadable gate store -> deny. Non-matching commands never touch the store and are never blocked.

## Requirements
Hook command (frontmatter), resolved by the step-1 probe:
- Preferred form if the probe shows `${CLAUDE_SKILL_DIR}` is substituted in hook commands: path `${CLAUDE_SKILL_DIR}/scripts/guard_hook.py`.
- Fallback form (default until proven otherwise): `$HOME/.claude/skills/recovery-storage/scripts/guard_hook.py` (the phase 07 junction).
- Wrapper logic in the command string: if the file does not exist -> print `recovery-storage guard: hook script not found at <path>; guard inactive` to stderr and exit 1 (non-blocking). Interpreter: `python` on Windows (`$OS == Windows_NT`, avoids the Store `python3` stub), `python3` elsewhere; interpreter missing -> shell exit 127 (non-blocking).
`guard_hook.py` behaviour:
1. Read stdin JSON. Unparseable -> exit 1, stderr `guard: unreadable hook input`.
2. `tool_name` not in {`Bash`, `PowerShell`} -> exit 0.
3. Split `tool_input.command` into segments (`;`, `&&`, `||`, `|`, `&`, newlines), strip leading wrappers (`sudo [-u x]`, `env A=B`, `nohup`, `time`, `command`, `exec`), unwrap nested shells (`bash|sh -c "<s>"`, `cmd /c <s>`, `powershell|pwsh [-NoProfile] -Command|-c "<s>"`, `-EncodedCommand <b64>` decoded as UTF-16LE, `wsl [-e|--exec|--] <s>`), recurse to a fixed depth parameter. Executable = basename without directory and `.exe`/`.com`, case-insensitive for Windows names.
4. Match each segment against `guard_patterns.RULES` (rule id, executable regex, argument predicate). First matching rule wins.
5. No match -> exit 0, no stdout, store not opened.
6. Match -> open `<home>/rs.sqlite` read-only (`file:...?mode=ro`, home = env `RECOVERY_STORAGE_HOME` else `~/.recovery-storage`); if any row in `gates` has `state = 'open'` -> exit 0 (no stdout, so normal permission flow continues). Else exit 2 with stderr: rule id, the matched segment (truncated to a parameter length), "no gate is open in <home>", and the next commands (`rs.py gate open <session> <device> <kind>`, `rs.py gate confirm <gate> --phrase ...`, then use the path printed by confirm). `pending` gates do not count; message then says "gate <id> is pending: run gate confirm".
7. Store missing / unreadable / locked beyond the connect timeout / schema newer -> for a matched command exit 2 with reason `cannot read gate store: <error>`.
8. Uncaught exception before a match decision -> exit 1 (non-blocking) with the error on stderr.
9. Best-effort audit line appended to `<home>/guard.log`: UTC time, rule id, decision, gate id, sha256 of the command (not the command text). Logging failure never changes the decision.
Pattern rules (v1, from the decision; each with its pass-through condition):
| rule | blocked when | passes when |
|---|---|---|
| diskpart | any invocation | - |
| Format-Volume, Clear-Disk, Initialize-Disk, Set-Disk, New-Partition, Remove-Partition, Resize-Partition, Set-Partition | any invocation (PowerShell, case-insensitive) | - |
| Repair-Volume | any flag other than `-Scan` | only `-Scan` |
| format (cmd) | `format` / `format.com` with a drive-letter arg | PowerShell `Format-Table/List/Wide/Custom/Hex` never match |
| chkdsk | any of `/f /r /x /b /spotfix /offlinescanandfix /forceofflinefix` | no flags or only read-only flags |
| mkfs, mkfs.*, mke2fs, mkntfs, mkdosfs, mkexfatfs, mkswap | any | `--help`, `-V`/`--version` |
| wipefs | `-a/--all`, `-o/--offset` without `-n/--no-act` | listing, or `-n` |
| sgdisk, gdisk, parted, fdisk, sfdisk, cfdisk | any write-capable form | `sgdisk -p/-i/-v`, `gdisk -l`, `parted -l` or only `print`, `fdisk -l`, `sfdisk -l/-d/-J/--dump/--list` |
| dd | `of=` naming a block device (`/dev/...`, `\\.\PhysicalDrive...`) | `of=` a regular path |
| ddrescue | any | `--help`, `-V`/`--version` (ddrescuelog never matches) |
| f3probe, f3write, f3fix, f3brew | any | `--help`, `--version` (f3read never matches) |
| badblocks | `-w` or `-n` (also inside combined flags like `-wsv`) | read-only invocation |
| testdisk | `/cmd` list containing `write` | `/list`, `/cmd` without `write` |
| hdparm | `--security-*`, `--write-sector`, `--repair-sector`, `--make-bad-sector`, `--trim-sector-ranges*`, `--fwdownload*`, `--dco-restore`, `--dco-setmax` | `-I`, other read flags |
| nvme | subcommands `format, sanitize, fw-download, fw-commit, fw-activate, ns-delete, ns-create, write, write-zeroes, write-uncor, dsm, device-self-test` | `list, smart-log, id-ctrl, id-ns, error-log`, other reads |
| smartctl | `-t/--test`, `-s/--smart`, `-o/--offlineauto`, `-S/--saveauto`, `-X/--abort`, `-C/--captive` | read flags (`-j -x -a -i -H -A -c -l --scan[-open] -V`) |
| blkdiscard | any | `--help` |
| fsck, fsck.*, e2fsck, ntfsfix, xfs_repair, dosfsck, exfatfsck | without `-n` | with `-n` (`ntfsfix -n`, `xfs_repair -n`) |
Rule ids and predicates live only in `guard_patterns.py`; SKILL.md lists rule ids via a pointer, not the table (single source).

## Architecture
```
recovery-storage/SKILL.md               frontmatter hooks: PreToolUse matcher "Bash|PowerShell" -> command (wrapper above)
recovery-storage/scripts/guard_hook.py  stdin JSON -> segments -> match -> gate lookup -> exit 0/1/2 (no subprocess)
recovery-storage/scripts/rslib/guard_patterns.py  pure: split(command) -> segments; match(segment) -> rule|None
recovery-storage/scripts/rslib/paths.py           reused for home resolution (guard_hook inserts its own dir on sys.path)
```
The hook never imports `runner.py` and never spawns processes (A18 static check extended to `guard_hook.py`).

## Related Code Files
Create: `recovery-storage/scripts/guard_hook.py`, `recovery-storage/scripts/rslib/guard_patterns.py`, tests `test_guard_patterns.py` (corpus), `test_guard_hook.py` (stdin/exit-code/store states, in-process plus one real-process run of the script).
Modify: `recovery-storage/SKILL.md` (frontmatter `hooks:` block, "Guard hook and its limits" section), `references/safety-and-gates.md` (leak list, what to do when blocked), `tests/test_skill_docs.py` (F1 accepts the `hooks` key and checks its matcher), `tests/test_no_subprocess_outside_runner.py` (also scans `guard_hook.py`).

## Implementation Steps
1. Spike first (gates the whole phase, see "Not Worth Doing If"): temporary frontmatter hook in the installed skill with command writing `${CLAUDE_SKILL_DIR}` to a probe file under `<home>`, plus a minimal deny of a sentinel; invoke the skill in a live session in the user's mode (bypassPermissions); record (a) whether `${CLAUDE_SKILL_DIR}` was substituted, (b) whether exit 2 blocked the Bash and the PowerShell tool call. Remove the spike hook.
2. `guard_patterns.py` with the corpus tests (frozen first).
3. `guard_hook.py` with store states tests.
4. Final frontmatter command (form chosen from step 1) + wrapper; docs.
5. Live test (step 1 repeated with the real hook), recorded in the phase review.

## Todo List
- [ ] spike: CLAUDE_SKILL_DIR substitution + deny enforced in bypassPermissions
- [ ] pattern module + corpus
- [ ] hook script + store states
- [ ] frontmatter + wrapper + docs (leaks)
- [ ] live test recorded

## Acceptance Criteria (observable)
Input handling
- H1 stdin `not json` -> exit 1, stderr contains `unreadable hook input`.
- H2 `{"tool_name":"Read","tool_input":{"file_path":"x"}}` -> exit 0, no output.
- H3 Non-matching Bash command with `RECOVERY_STORAGE_HOME` pointing at a directory whose `rs.sqlite` is a corrupt file -> exit 0 (store never opened).
Must block when no gate is open (each a corpus case; Bash unless marked PS):
- H4 `mkfs.ext4 /dev/sdb1`; `/usr/sbin/mkfs -t vfat /dev/sdc1`; `sudo wipefs -a /dev/sdb`; `wipefs --all /dev/sdb`; `sgdisk --zap-all /dev/sdb`; `parted -s /dev/sdb mklabel gpt`; `fdisk /dev/sdb`; `sfdisk /dev/sdb < layout.txt`; `dd if=/dev/zero of=/dev/sdb bs=1M`; `dd if=img of=\\.\PhysicalDrive2`; `ddrescue -f -n /dev/sdb img.dd map`; `f3probe --destructive /dev/sdb`; `f3write /media/usb`; `f3fix --last-sec=123 /dev/sdb`; `f3brew /dev/sdb`; `badblocks -wsv /dev/sdb`; `badblocks -n /dev/sdb`; `testdisk /cmd /dev/sdb analyze,quicksearch,write`; `hdparm --security-erase pw /dev/sdb`; `hdparm --write-sector 100 /dev/sdb`; `nvme format /dev/nvme0n1`; `nvme sanitize /dev/nvme0`; `smartctl -t short /dev/sda`; `smartctl -s on /dev/sda`; `smartctl --smart=off /dev/sda`; `smartctl -o on /dev/sda`; `smartctl -S on /dev/sda`; `blkdiscard /dev/sdb`; `fsck /dev/sdb1`; `e2fsck -f -y /dev/sdb1`; `ntfsfix /dev/sdb1`; `cmd /c format E: /FS:FAT32 /Q`; `chkdsk E: /f`; `chkdsk E: /r`; `chkdsk E: /x`.
- H5 Wrapped/compound: `echo ok && mkfs.vfat /dev/sdb1`; `bash -c "wipefs -a /dev/sdb"`; `wsl -e sudo ddrescue /dev/sdb img map`; `sudo -u root dd of=/dev/sdb if=x`; `ls; diskpart /s s.txt`; `powershell -NoProfile -Command "Clear-Disk -Number 2 -RemoveData"`; `powershell -EncodedCommand <UTF-16LE base64 of "Format-Volume -DriveLetter E">`.
- H5b `powershell -EncodedCommand <invalid base64 or not UTF-16LE>` and `pwsh -enc <same>` -> blocked without an open gate (plan.md R2); `powershell -EncodedCommand <UTF-16LE base64 of "Get-Disk">` -> allowed.
- H6 PS: `Format-Volume -DriveLetter E -FileSystem FAT32`; `format-volume -driveletter e`; `Clear-Disk -Number 2 -RemoveData`; `Initialize-Disk -Number 2`; `Set-Disk -Number 2 -IsOffline $true`; `Set-Disk 2 -IsReadOnly $false`; `Get-Disk 2 | Clear-Disk -RemoveData -Confirm:$false`; `diskpart /s script.txt`; `Repair-Volume -DriveLetter E -OfflineScanAndFix`.
- H7 Every blocked case: exit 2, stderr names the rule id, contains `no gate is open`, and the text `rs.py gate open`.
Must never block (gate or not; each a corpus case):
- H8 `smartctl -j -x /dev/sda`; `smartctl --scan-open -j`; `smartctl -a /dev/sda`; `fsck -n /dev/sdb1`; `e2fsck -n /dev/sdb1`; `ntfsfix -n /dev/sdb1`; `chkdsk`; `chkdsk E:`; `fdisk -l`; `sfdisk -l /dev/sdb`; `sfdisk -d /dev/sdb`; `parted -l`; `parted /dev/sdb print`; `sgdisk -p /dev/sdb`; `wipefs /dev/sdb`; `wipefs -n -a /dev/sdb`; `dd if=/dev/sdb of=image.img bs=1M`; `ddrescuelog -t map`; `ddrescue --version`; `f3read /media/usb`; `f3probe --help`; `badblocks -sv /dev/sdb`; `hdparm -I /dev/sdb`; `nvme list`; `nvme smart-log /dev/nvme0`; `lsblk -J -O -b`; `git commit -m "docs: mkfs and Clear-Disk notes"`; `echo "run mkfs.ext4 later"`; `grep -r Clear-Disk docs/`; `rg "dd of=/dev"`; `python rs.py gate open s1 d1 format`.
- H9 PS: `Get-Disk`; `Get-Disk | Format-Table -AutoSize`; `Get-Volume | Format-List`; `Write-Host "Format-Volume"`; `Get-Process | Format-Wide`; `Repair-Volume -DriveLetter E -Scan`.
Gate interplay (store built by phase 04 code in a temp home)
- H10 One gate `open` (any device, any session) -> every H4-H6 command exits 0 with no stdout.
- H11 Only a `pending` gate -> blocked, message names the pending gate and says to run `gate confirm`. Only `closed`/`aborted` gates -> blocked.
- H12 Fresh home without `rs.sqlite` + H4 command -> exit 2 (`no gate is open`). Corrupt DB, DB with newer `user_version`, or DB locked past the timeout + H4 command -> exit 2 with `cannot read gate store`. Same three DB states + H8 command -> exit 0.
- H13 `RECOVERY_STORAGE_HOME` set -> that home is read; unset -> `~/.recovery-storage`.
- H14 `guard.log` gets one line per matched decision with rule id, decision, gate id and a sha256 (the command text itself is absent); a read-only home still yields the correct exit code.
Registration and live behaviour
- H15 SKILL.md frontmatter parses with `hooks.PreToolUse[0].matcher == "Bash|PowerShell"` and one `type: command` hook.
- H16 Running the frontmatter command string in Git Bash with `HOME` pointing to a temp dir where the script is absent -> exit 1 and stderr `guard inactive` (never exit 2).
- H17 Live (recorded with date, Claude Code version, permission mode): after invoking the skill, Bash `blkdiscard /dev/rs-guard-sentinel` and PowerShell `Clear-Disk -Number 9999 -WhatIf` are denied with the guard message; Bash `smartctl -j -i /dev/sdz` runs; after `gate open` + `gate confirm` of an R1 kind on the USB stick the Bash sentinel is allowed (not installed on Windows, so it fails harmlessly); after `gate abort` it is denied again. Sentinels are chosen so that even an unblocked run cannot change any device.
- H18 SKILL.md "Guard hook and its limits" lists every leak from Key Insights and states that the hook stays active for the rest of the session.

## Pros / cons vs alternative
Chosen: skill-frontmatter PreToolUse hook with a pattern deny-list, gate-open check against the store.
- Pros: ships with the skill (no edit of user-level settings); active exactly in sessions that use the skill; catches the common direct-call mistakes (agent typing `mkfs`/`ddrescue`/`Format-Volume` without a gate); deterministic and corpus-tested.
- Cons: leaky (see list); session-wide after invocation; any open gate unlocks all devices; depends on unverified hook behaviour in bypassPermissions (step 1 spike).
Alternative: user-level `settings.json` hook (or `permissions.deny` rules) always active.
- Pros: covers sessions that never invoke the skill. Cons: edits the user's global configuration (outward-facing, needs explicit consent), affects every project and session, and still a deny-list. Rejected for v1; can reuse `guard_hook.py` unchanged if the user later wants it global.

## Not Worth Doing If
- The step-1 spike shows that an exit-2 PreToolUse deny is NOT enforced in the user's bypassPermissions mode and the user does not work in another mode: the hook would protect nothing in practice. Stop after the spike, record the result in the phase review and SKILL.md ("guard hook not enforced in bypassPermissions"), and do not build steps 2-5.

## Risk Assessment
- False positives block legitimate read-only work -> H8/H9 must-pass corpus; quoted strings are arguments, not executables; Format-Table family excluded explicitly.
- False negatives (leaks) -> documented, not hidden; gate + SKILL.md remain the primary control.
- Hook path wrong after repo move -> wrapper exits 1 with `guard inactive` (visible), never 2.
- `--home` sessions invisible to the hook -> SKILL.md says real sessions use `RECOVERY_STORAGE_HOME` or the default home; a `--home` session with a matched command is blocked (fail-closed), message names the home it read.
- Hook latency on every Bash/PowerShell call -> non-matching path does no file or DB IO.

## Security Considerations
- Hook reads only the gate table, read-only; writes only the best-effort audit line (no command text, no serials).
- Decoding `-EncodedCommand` is local and bounded by the input size; no execution of decoded text.

## Next Steps
- After done: if the user wants protection in sessions that never invoke the skill, register the same script in user-level settings (separate, consented change).
