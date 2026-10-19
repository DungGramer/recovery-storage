"""Phase 08 pattern corpus (H4, H5, H5b, H6, H8, H9). Spec: phase-08 Requirements 'guard_hook.py behaviour' step 3-4,
'Pattern rules (v1)' table + H4-H9. Pure: rslib.guard_patterns.find(command)."""
import base64

import pytest


def enc(text):
    return base64.b64encode(text.encode("utf-16-le")).decode("ascii")


H4 = [
    "mkfs.ext4 /dev/sdb1", "/usr/sbin/mkfs -t vfat /dev/sdc1", "sudo wipefs -a /dev/sdb", "wipefs --all /dev/sdb",
    "sgdisk --zap-all /dev/sdb", "parted -s /dev/sdb mklabel gpt", "fdisk /dev/sdb", "sfdisk /dev/sdb < layout.txt",
    "dd if=/dev/zero of=/dev/sdb bs=1M", r"dd if=img of=\\.\PhysicalDrive2", "ddrescue -f -n /dev/sdb img.dd map",
    "f3probe --destructive /dev/sdb", "f3write /media/usb", "f3fix --last-sec=123 /dev/sdb", "f3brew /dev/sdb",
    "badblocks -wsv /dev/sdb", "badblocks -n /dev/sdb", "testdisk /cmd /dev/sdb analyze,quicksearch,write",
    "hdparm --security-erase pw /dev/sdb", "hdparm --write-sector 100 /dev/sdb", "nvme format /dev/nvme0n1",
    "nvme sanitize /dev/nvme0", "smartctl -t short /dev/sda", "smartctl -s on /dev/sda", "smartctl --smart=off /dev/sda",
    "smartctl -o on /dev/sda", "smartctl -S on /dev/sda", "blkdiscard /dev/sdb", "fsck /dev/sdb1",
    "e2fsck -f -y /dev/sdb1", "ntfsfix /dev/sdb1", "cmd /c format E: /FS:FAT32 /Q", "chkdsk E: /f", "chkdsk E: /r",
    "chkdsk E: /x",
]
H5 = [
    "echo ok && mkfs.vfat /dev/sdb1", 'bash -c "wipefs -a /dev/sdb"', "wsl -e sudo ddrescue /dev/sdb img map",
    "sudo -u root dd of=/dev/sdb if=x", "ls; diskpart /s s.txt",
    'powershell -NoProfile -Command "Clear-Disk -Number 2 -RemoveData"',
    "powershell -EncodedCommand " + enc("Format-Volume -DriveLetter E"),
]
H5B_BLOCK = [
    "powershell -EncodedCommand !!!not-base64!!!",
    "powershell -EncodedCommand " + base64.b64encode(b"\xff\xfe\xfd").decode("ascii"),
    "pwsh -enc !!!not-base64!!!",
    "pwsh -enc " + base64.b64encode(b"\xff\xfe\xfd").decode("ascii"),
]
H5B_ALLOW = ["powershell -EncodedCommand " + enc("Get-Disk")]
H6 = [  # PowerShell tool
    "Format-Volume -DriveLetter E -FileSystem FAT32", "format-volume -driveletter e", "Clear-Disk -Number 2 -RemoveData",
    "Initialize-Disk -Number 2", "Set-Disk -Number 2 -IsOffline $true", "Set-Disk 2 -IsReadOnly $false",
    "Get-Disk 2 | Clear-Disk -RemoveData -Confirm:$false", "diskpart /s script.txt",
    "Repair-Volume -DriveLetter E -OfflineScanAndFix",
]
H8 = [
    "smartctl -j -x /dev/sda", "smartctl --scan-open -j", "smartctl -a /dev/sda", "fsck -n /dev/sdb1",
    "e2fsck -n /dev/sdb1", "ntfsfix -n /dev/sdb1", "chkdsk", "chkdsk E:", "fdisk -l", "sfdisk -l /dev/sdb",
    "sfdisk -d /dev/sdb", "parted -l", "parted /dev/sdb print", "sgdisk -p /dev/sdb", "wipefs /dev/sdb",
    "wipefs -n -a /dev/sdb", "dd if=/dev/sdb of=image.img bs=1M", "ddrescuelog -t map", "ddrescue --version",
    "f3read /media/usb", "f3probe --help", "badblocks -sv /dev/sdb", "hdparm -I /dev/sdb", "nvme list",
    "nvme smart-log /dev/nvme0", "lsblk -J -O -b", 'git commit -m "docs: mkfs and Clear-Disk notes"',
    'echo "run mkfs.ext4 later"', "grep -r Clear-Disk docs/", 'rg "dd of=/dev"', "python rs.py gate open s1 d1 format",
]
H9 = [  # PowerShell tool
    "Get-Disk", "Get-Disk | Format-Table -AutoSize", "Get-Volume | Format-List", 'Write-Host "Format-Volume"',
    "Get-Process | Format-Wide", "Repair-Volume -DriveLetter E -Scan",
]
BLOCK = [("Bash", c) for c in H4 + H5 + H5B_BLOCK] + [("PowerShell", c) for c in H6]
ALLOW = [("Bash", c) for c in H8 + H5B_ALLOW] + [("PowerShell", c) for c in H9]


def find(cmd):
    from rslib.guard_patterns import find as f

    return f(cmd)


@pytest.mark.parametrize("cmd", H4)
def test_H4_destructive_commands_match(cmd):
    """H4. Mutation per case: drop that rule/flag predicate -> that case red."""
    m = find(cmd)
    assert m is not None
    from rslib.guard_patterns import RULES

    assert m.rule_id in {r.id for r in RULES}


@pytest.mark.parametrize("cmd", H5)
def test_H5_wrapped_and_compound_match(cmd):
    """H5. Mutation: no segment split / wrapper strip / nested-shell unwrap / EncodedCommand decode -> red."""
    assert find(cmd) is not None


@pytest.mark.parametrize("cmd", H5B_BLOCK)
def test_H5b_undecodable_encoded_command_is_destructive_class(cmd):
    """H5b (plan R2). Mutation: undecodable payload passes -> red."""
    assert find(cmd) is not None


@pytest.mark.parametrize("cmd", H5B_ALLOW)
def test_H5b_decodable_read_only_encoded_command_allowed(cmd):
    """H5b. Mutation: block every -EncodedCommand -> red."""
    assert find(cmd) is None


@pytest.mark.parametrize("cmd", H6)
def test_H6_powershell_destructive_cmdlets_match(cmd):
    """H6. Mutation: case-sensitive cmdlet names (format-volume) or pipeline not split -> red."""
    assert find(cmd) is not None


@pytest.mark.parametrize("cmd", H8)
def test_H8_read_only_and_text_mentions_never_match(cmd):
    """H8. Mutation: substring matching (quoted 'mkfs' in git/echo/grep) or -n flags ignored -> red."""
    assert find(cmd) is None


@pytest.mark.parametrize("cmd", H9)
def test_H9_powershell_read_only_never_match(cmd):
    """H9. Mutation: Format-Table matched as format, or Repair-Volume -Scan blocked -> red."""
    assert find(cmd) is None


def test_match_reports_the_segment():
    """Requirements step 6 'the matched segment' (stderr). Mutation: report the whole compound command -> red."""
    m = find("echo ok && mkfs.vfat /dev/sdb1")
    assert "mkfs.vfat" in m.segment and "echo ok" not in m.segment
