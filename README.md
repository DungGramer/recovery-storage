# recovery-storage

A Claude Code skill that diagnoses and recovers storage devices (USB flash, SD/microSD, HDD, SATA/NVMe SSD, external drives, USB bridges). It collects read-only evidence with smartctl and OS inventory, triages, puts every risky action behind an identity re-check and a human confirmation (the gate), keeps a case history in SQLite, refuses a PASS verdict without evidence and renders a per-device report. It drives existing tools (ddrescue, TestDisk, PhotoRec, F3, H2testw); it never images, repairs, flashes or tests capacity itself.

## Install

Prerequisites: Python >= 3.10, smartmontools 7.x (`winget install smartmontools.smartmontools` or `scoop install smartmontools` on Windows, package `smartmontools` on Linux). Optional, used by the playbooks: ddrescue, TestDisk/PhotoRec, F3.

```powershell
python recovery-storage/scripts/install_junction.py
```

This links `~/.claude/skills/recovery-storage` to the skill folder (junction on Windows, symlink elsewhere; `--skills-dir DIR` to change the target). It is idempotent and refuses to replace an existing real folder. The case store is created on first use in `~/.recovery-storage` (override with `--home` or `RECOVERY_STORAGE_HOME`); it holds device serials and is outside the repo.

## Use

Ask Claude about a failing device; the skill drives `python recovery-storage/scripts/rs.py ...`. Run `rs.py --help` for the commands and `rs.py rules` for the rule tables.

## The operator confirms in their own terminal

Steps the agent must not give itself need a human at an interactive console: `gate confirm`, data-state waivers and attestations, `ingest attested`, `device link`. When the agent runs one, the CLI exits 3 with `operator-console-required` and prints the exact command. Run that command in your own terminal, for example:

```powershell
python "<repo>\recovery-storage\scripts\rs.py" gate confirm G...
```

Type the phrase shown by `gate open` (the last 4 characters of the trusted serial, or the exact byte count), or `YES` where asked. Confirm only after checking model, serial and size on the printed block. Then run the action yourself against the OS path `gate confirm` prints, and let the agent run `gate close`.

A guard hook (active once the skill is invoked) denies matched destructive shell commands unless a gate is open. It is a second barrier with known leaks, listed in `recovery-storage/SKILL.md`.

## Tests

From PowerShell in the repo root:

```powershell
python -m pytest -q -p no:cacheprovider
```

Tests marked `live` (real devices, admin, other interpreters, a live Claude Code session) are deselected; run them with `-m live`. The suite is a frozen spec-first suite; see `docs/code-standards.md` before changing it.

Known environment notes:

- H16 (guard hook through a real shell) needs Git for Windows with `C:\Program Files\Git\cmd` first on `PATH`.
- G12 fails on Python 3.10 because the frozen test helper lacks `os.path.isjunction`.

## Documentation

See [docs/README.md](docs/README.md). Plan, requirements and amendments are under `plans/20261019-1726-recovery-storage-skill/`.
