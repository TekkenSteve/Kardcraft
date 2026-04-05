"""Tests for agent_skills loading, parsing, and progressive disclosure."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from kardcraft.agent_skills.load import (
    MAX_SKILL_FILE_SIZE,
    SkillMetadata,
    _is_safe_path,
    _list_skills,
    _parse_skill_metadata,
    list_skills,
)


@pytest.fixture
def empty_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def skills_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        skill_dir = root / "example-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: example-skill\ndescription: An example skill for testing\n---\n\n# Example Skill\n\nSome content here.",
            encoding="utf-8",
        )
        yield root


class TestIsSafePath:
    def test_path_inside_base_dir(self, empty_dir):
        child = empty_dir / "sub" / "file.txt"
        child.parent.mkdir()
        child.touch()
        assert _is_safe_path(child, empty_dir) is True

    def test_path_outside_base_dir(self, empty_dir):
        other = Path(tempfile.gettempdir()) / "outside.txt"
        assert _is_safe_path(other, empty_dir) is False

    def test_symlink_inside_base_dir(self, empty_dir):
        target = empty_dir / "target.txt"
        target.touch()
        link = empty_dir / "link.txt"
        link.symlink_to(target)
        assert _is_safe_path(link, empty_dir) is True

    def test_symlink_outside_base_dir(self, empty_dir):
        outside = Path(tempfile.gettempdir()) / "outside_target.txt"
        outside.touch()
        link = empty_dir / "escape_link.txt"
        link.symlink_to(outside)
        assert _is_safe_path(link, empty_dir) is False

    def test_path_traversal_within_base_dir(self, empty_dir):
        escape = empty_dir / ".." / "etc" / "passwd"
        assert _is_safe_path(escape, empty_dir) is False

    def test_resolve_error_returns_false(self):
        class BadPath:
            def resolve(self):
                raise OSError("cannot resolve")

        assert _is_safe_path(BadPath(), Path(".")) is False


class TestParseSkillMetadata:
    def test_valid_frontmatter_returns_metadata(self, skills_dir):
        skill_path = skills_dir / "example-skill" / "SKILL.md"
        result = _parse_skill_metadata(skill_path, source="project")
        assert result is not None
        assert result["name"] == "example-skill"
        assert result["description"] == "An example skill for testing"
        assert result["path"] == str(skill_path)
        assert result["source"] == "project"

    def test_missing_frontmatter_returns_none(self, empty_dir):
        skill_dir = empty_dir / "no-frontmatter"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "No frontmatter here.\n\nJust content.", encoding="utf-8"
        )
        result = _parse_skill_metadata(skill_dir / "SKILL.md", source="user")
        assert result is None

    def test_missing_name_returns_none(self, empty_dir):
        skill_dir = empty_dir / "no-name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: Has no name\n---\n", encoding="utf-8"
        )
        result = _parse_skill_metadata(skill_dir / "SKILL.md", source="user")
        assert result is None

    def test_missing_description_returns_none(self, empty_dir):
        skill_dir = empty_dir / "no-description"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: no-description\n---\n", encoding="utf-8"
        )
        result = _parse_skill_metadata(skill_dir / "SKILL.md", source="user")
        assert result is None

    def test_file_too_large_returns_none(self, empty_dir):
        skill_dir = empty_dir / "too-large"
        skill_dir.mkdir()
        large_content = "---\nname: large\ndescription: x\n---\n" + "x" * (
            MAX_SKILL_FILE_SIZE + 1
        )
        (skill_dir / "SKILL.md").write_text(large_content, encoding="utf-8")
        result = _parse_skill_metadata(skill_dir / "SKILL.md", source="user")
        assert result is None

    def test_extra_frontmatter_fields_discarded(self, empty_dir):
        skill_dir = empty_dir / "extra-fields"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: extra-fields\ndescription: With extra fields\ncategory: testing\npriority: high\nkeywords:\n  - test\n  - unit\n---\n",
            encoding="utf-8",
        )
        result = _parse_skill_metadata(skill_dir / "SKILL.md", source="project")
        assert result is not None
        assert result["name"] == "extra-fields"
        assert result["description"] == "With extra fields"
        assert "category" not in result
        assert "priority" not in result

    def test_description_with_underscore_parsed(self, empty_dir):
        skill_dir = empty_dir / "underscore-desc"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: underscore\ndescription: Handles_underscores fine\n---\n",
            encoding="utf-8",
        )
        result = _parse_skill_metadata(skill_dir / "SKILL.md", source="user")
        assert result is not None
        assert result["description"] == "Handles_underscores fine"

    def test_file_not_found_returns_none(self, empty_dir):
        result = _parse_skill_metadata(
            empty_dir / "nonexistent" / "SKILL.md", source="user"
        )
        assert result is None

    def test_invalid_yaml_returns_none(self, empty_dir):
        skill_dir = empty_dir / "bad-yaml"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: x\n  invalid: [unclosed\n---\n", encoding="utf-8"
        )
        result = _parse_skill_metadata(skill_dir / "SKILL.md", source="user")
        assert result is None


class TestListSkills:
    def test_empty_directory_returns_empty_list(self, empty_dir):
        result = _list_skills(empty_dir, source="user")
        assert result == []

    def test_nonexistent_directory_returns_empty_list(self):
        result = _list_skills(Path("/nonexistent/path/to/skills"), source="user")
        assert result == []

    def test_directory_with_no_skills_returns_empty_list(self, empty_dir):
        (empty_dir / "not-a-skill").mkdir()
        result = _list_skills(empty_dir, source="user")
        assert result == []

    def test_single_skill_found(self, skills_dir):
        result = _list_skills(skills_dir, source="user")
        assert len(result) == 1
        assert result[0]["name"] == "example-skill"

    def test_skills_file_not_directory_skipped(self, empty_dir):
        (empty_dir / "SKILL.md").write_text(
            "---\nname: root-skill\ndescription: desc\n---\n", encoding="utf-8"
        )
        result = _list_skills(empty_dir, source="user")
        assert result == []

    def test_only_direct_subdirectories_checked(self, empty_dir):
        nested = empty_dir / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text(
            "---\nname: nested\ndescription: nested skill\n---\n", encoding="utf-8"
        )
        result = _list_skills(empty_dir, source="user")
        assert result == []


class TestListSkillsPublicAPI:
    def test_only_user_skills_dir(self, empty_dir):
        skill_dir = empty_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: My skill desc\n---\n", encoding="utf-8"
        )
        result = list_skills(user_skills_dir=empty_dir)
        assert len(result) == 1
        assert result[0]["source"] == "user"

    def test_only_project_skills_dir(self, empty_dir):
        skill_dir = empty_dir / "project-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: project-skill\ndescription: Project skill desc\n---\n",
            encoding="utf-8",
        )
        result = list_skills(project_skills_dir=empty_dir)
        assert len(result) == 1
        assert result[0]["source"] == "project"

    def test_both_dirs_user_and_project(self, empty_dir):
        user_dir = empty_dir / "user_skills"
        proj_dir = empty_dir / "project_skills"
        user_dir.mkdir()
        proj_dir.mkdir()

        u_skill = user_dir / "user-skill"
        u_skill.mkdir()
        (u_skill / "SKILL.md").write_text(
            "---\nname: user-skill\ndescription: User skill\n---\n", encoding="utf-8"
        )

        p_skill = proj_dir / "user-skill"
        p_skill.mkdir()
        (p_skill / "SKILL.md").write_text(
            "---\nname: user-skill\ndescription: Project override\n---\n",
            encoding="utf-8",
        )

        result = list_skills(user_skills_dir=user_dir, project_skills_dir=proj_dir)
        assert len(result) == 1
        assert result[0]["source"] == "project"
        assert result[0]["description"] == "Project override"

    def test_expanduser_called_on_skills_dir(self, skills_dir):
        tilde_path = Path(f"~/.cache/kardcraft-nonexistent")
        result = list_skills(user_skills_dir=tilde_path)
        assert result == []

    def test_multiple_skills_collected(self, empty_dir):
        for i in range(5):
            d = empty_dir / f"skill-{i}"
            d.mkdir()
            (d / "SKILL.md").write_text(
                f"---\nname: skill-{i}\ndescription: Skill number {i}\n---\n",
                encoding="utf-8",
            )
        result = list_skills(project_skills_dir=empty_dir)
        assert len(result) == 5
        names = {s["name"] for s in result}
        assert names == {"skill-0", "skill-1", "skill-2", "skill-3", "skill-4"}


class TestSkillMetadataShape:
    def test_required_fields_present(self, skills_dir):
        skills = list_skills(project_skills_dir=skills_dir)
        assert len(skills) == 1
        s = skills[0]
        assert "name" in s
        assert "description" in s
        assert "path" in s
        assert "source" in s
        assert s["source"] in ("user", "project")
