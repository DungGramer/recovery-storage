"""Phase 07 install junction (G12). Spec: phase-07 Requirements 'Install', Architecture install note, Security
'Installer never deletes an existing target' + G12. Uses a temp skills dir (never the real ~/.claude)."""
import os
import sys

import pytest

from conftest import SKILL_DIR


def install(skills_dir):
    import install_junction

    return install_junction.main(["--skills-dir", str(skills_dir)])


def is_link(p):
    return os.path.islink(p) or (hasattr(os.path, "isjunction") and os.path.isjunction(p))


def make_link(src, dst):
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(src), str(dst))
    else:
        os.symlink(src, dst, target_is_directory=True)


def test_G12_install_creates_link_to_repo_skill(tmp_path):
    """G12. Mutation: copy the folder instead of linking, or link the wrong folder -> red."""
    skills = tmp_path / "skills"
    assert install(skills) == 0
    target = skills / "recovery-storage"
    assert is_link(target)
    assert os.path.samefile(target / "SKILL.md", SKILL_DIR / "SKILL.md")


def test_G12_rerun_is_noop(tmp_path):
    """G12 idempotent. Mutation: second run errors 'exists' or recreates -> red."""
    skills = tmp_path / "skills"
    assert install(skills) == 0
    assert install(skills) == 0
    assert os.path.samefile(skills / "recovery-storage" / "SKILL.md", SKILL_DIR / "SKILL.md")


def test_G12_existing_regular_dir_refused_untouched(tmp_path):
    """G12 + Security. Mutation: delete and replace the existing folder -> red."""
    skills = tmp_path / "skills"
    target = skills / "recovery-storage"
    target.mkdir(parents=True)
    (target / "mine.txt").write_text("user data", encoding="utf-8")
    assert install(skills) == 3
    assert not is_link(target)
    assert (target / "mine.txt").read_text(encoding="utf-8") == "user data"


def test_G12_link_to_other_folder_refused(tmp_path):
    """Requirements 'refuses if the target exists and is not a junction to this folder'. Mutation: accept any link -> red."""
    skills = tmp_path / "skills"
    skills.mkdir()
    other = tmp_path / "other-skill"
    other.mkdir()
    make_link(other, skills / "recovery-storage")
    assert install(skills) == 3
    assert os.path.samefile(skills / "recovery-storage", other)
