"""Install the skill by linking <skills-dir>/recovery-storage -> this repo's recovery-storage/ folder.

Windows: directory junction (no admin needed); elsewhere: symlink. Idempotent. Never deletes or replaces an
existing target: a real folder or a link to another place -> exit 3, untouched. No processes spawned.
Usage: python install_junction.py [--skills-dir DIR]   (default ~/.claude/skills)
"""
import argparse
import os
import pathlib
import stat
import sys

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
NAME = "recovery-storage"


def _is_link(p):
    if os.path.islink(p) or (hasattr(os.path, "isjunction") and os.path.isjunction(p)):
        return True
    # Python < 3.12 has no isjunction: a junction is a directory reparse point
    attrs = getattr(os.lstat(p), "st_file_attributes", 0) if os.path.lexists(p) else 0
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _points_here(p):
    try:
        return os.path.samefile(p, SKILL_DIR)
    except OSError:
        return False


def _link(src, dst):
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(src), str(dst))
    else:
        os.symlink(src, dst, target_is_directory=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skills-dir", default=str(pathlib.Path.home() / ".claude" / "skills"))
    a = ap.parse_args(argv)
    skills = pathlib.Path(a.skills_dir)
    target = skills / NAME
    if os.path.lexists(target):
        if _is_link(target) and _points_here(target):
            print(f"already installed: {target} -> {SKILL_DIR}")
            return 0
        kind = "link to another folder" if _is_link(target) else "existing folder/file"
        print(f"refused: {target} is an {kind}; move it away yourself, nothing was changed", file=sys.stderr)
        return 3
    try:
        skills.mkdir(parents=True, exist_ok=True)
        _link(SKILL_DIR, target)
    except OSError as e:
        print(f"cannot create link {target}: {e}", file=sys.stderr)
        return 4
    print(f"installed: {target} -> {SKILL_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
