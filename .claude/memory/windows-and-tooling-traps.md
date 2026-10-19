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
- Verification gates (f3write-f3read...) write the source: before amendment 04 their close moved the PASS window
  past the evidence they produced. A green suite never ran the real run-ingest-close order; real runs find these.
