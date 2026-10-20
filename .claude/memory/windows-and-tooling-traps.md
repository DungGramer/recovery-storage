# Windows and tooling traps hit while building recovery-storage (2026-10-19)

- Bash tool heredocs: `\\` inside a heredoc arrives as `\`, so Python source written through
  `python - <<'EOF'` with `"\\n"` became a real newline (broke string literals three times). Write files with the
  Write/Edit tools when the text contains backslashes.
- Python on Windows: `sys.stdin.isatty()` is True for the NUL device (`< /dev/null` in Git Bash). A real console is
  confirmed with `GetConsoleMode` on the handle (`rslib/operator.py:_is_console`).
- `rslib/operator.py` shadows the stdlib `operator` module when Python runs with `rslib/` as CWD and without `-I`
  (`python -c ...` inside rslib/ fails importing enum). Always `python -I` there; never put an entry script in rslib/.
- PowerShell 5.1 `>` writes UTF-16LE; capture tool output through subprocess, not shell redirection.
- Git Bash rewrites `/dev/sda` into a Windows path unless `MSYS_NO_PATHCONV=1`; Python `-I`/argv lists are unaffected.
- The user's global PreToolUse hook blocks literal destructive strings (`mkfs.`, `> /dev/sd*`) in any shell command,
  including test strings: put such corpora in script files.
- smartctl sets `passed: true` for self-tests "in progress" (status nibble 0xF): classify by `status.value >> 4`.
- Windows `Get-Disk` reports a removed SD card in a reader as Size 0, OperationalStatus `No Media`: not a controller
  fault (`no_media` observation fact).
- Real run 2026-10-19: Git Bash also rewrites `/root/...` args passed to `wsl` (`sh: cannot open C:/Program
  Files/Git/root/...`); `wslpath` on a Git Bash `C:/...` path drops the separators. Set `MSYS_NO_PATHCONV=1`, use
  `/mnt/c/Users/<long name>/...` directly.
- f3write on WSL drvfs: the volume filling up comes back as EIO, not ENOSPC: "Write failure: Input/output error" on
  the last file with final free space 0. f3read then aborts (exit 134, `size % SECTOR_SIZE` assertion) on that
  partial file: truncate it to a 512 multiple and rerun f3read. Check Windows System events to rule out a device error.
- `wsl.exe -- sh -c "..."`: WSL hands the joined argv to the Linux login shell, which expands `$var` / `$(...)`
  inside the double quotes BEFORE `sh` runs, even when escaped for Git Bash (2026-10-20: a size guard saw empty
  values and refused). Put anything with variables in a script file, copy it into WSL, run `sh /root/x.sh`.
- WSL 2.4.11 kernel 5.15.167 has no usb-storage (`CONFIG_USB_STORAGE is not set`): usbipd-attached USB disks never
  appear. `wsl --update` (3.0.3, kernel 6.18) ships it as a module; it also restarts Docker Desktop's distros.
- f3read right after f3write through WSL drvfs reads the Windows host cache, not the device (2026-10-19/20: stick
  276 MB/s, card 159 MB/s; after an operator replug 14 / 17 MB/s). I recorded a PASS on a cached read and had to
  re-verify; amendment 07 now refuses it (`f3read-not-after-replug`). Check the f3read rate against the device.
- Windows reuses drive letters across media in the same reader: event text "volume E:" is not a device id (2026-10-20:
  a 32 GB card's 25 Ntfs 55 events became evidence on a 4 GB card). Amendment 09 attributes by the nearest observation
  holding the letter; any new event matcher must do the same.
- Files written on Windows by the Write tool / agents land CRLF while git stores LF (`core.autocrlf=input`, status
  stays clean): 59 frozen files carried CRLF hashes, a fresh clone mismatched (fixed 2026-10-21, manifest entry
  `eol-lf`). Freeze hashes over the git blob bytes; check with `git show HEAD:<path>` before re-freezing.
- Verification gates (f3write-f3read...) write the source: before amendment 04 their close moved the PASS window
  past the evidence they produced. A green suite never ran the real run-ingest-close order; real runs find these.
