"""Codex learnings must reach an instruction file Codex actually loads."""

from pathlib import Path

import pytest

from headroom.learn.models import ProjectInfo, Recommendation, RecommendationTarget
from headroom.learn.plugins.codex import CodexPlugin
from headroom.learn.writer import CodexWriter


def test_writer_merges_preferences_and_legacy_rules_into_agents(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# User instructions\nKeep my instructions.\n")
    legacy = tmp_path / "instructions.md"
    legacy.write_text(
        "Personal notes\n<!-- headroom:learn:start -->\n"
        "### Existing preference\n- Keep this learned rule.\n"
        "<!-- headroom:learn:end -->\n"
    )
    legacy_before = legacy.read_bytes()
    project = ProjectInfo(
        name="codex",
        project_path=tmp_path,
        data_path=tmp_path / "sessions",
        context_file=agents,
        memory_file=legacy,
    )
    rules = [
        Recommendation(target=target, section=section, content=content)
        for target, section, content in (
            (RecommendationTarget.CONTEXT_FILE, "Environment", "- Use the project runtime."),
            (RecommendationTarget.MEMORY_FILE, "Preferences", "- Avoid duplicate polling."),
        )
    ]
    writer = CodexWriter()
    preview = writer.write(rules, project, dry_run=True)
    assert preview.files_written == [agents, tmp_path / "AGENTS.headroom.md"]
    assert "Avoid duplicate polling" in preview.content_by_file[agents]
    assert "Keep this learned rule" in preview.content_by_file[agents]
    assert agents.read_text() == "# User instructions\nKeep my instructions.\n"

    result = writer.write(rules, project, dry_run=False)
    assert result.files_written == [agents, tmp_path / "AGENTS.headroom.md"]
    content = agents.read_text()
    assert content.startswith("# User instructions\nKeep my instructions.\n")
    assert "Personal notes" not in content
    assert legacy.read_bytes() == legacy_before
    writer.write(rules, project, dry_run=False)
    assert agents.read_text() == content


@pytest.mark.parametrize("override", [None, "", "# Override\n"])
def test_discovery_selects_active_global_instructions(tmp_path: Path, override: str | None) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "session.jsonl").write_text("{}\n")
    if override is not None:
        (tmp_path / "AGENTS.override.md").write_text(override)
    project = CodexPlugin(codex_dir=tmp_path).discover_projects()[0]
    expected = "AGENTS.override.md" if override else "AGENTS.md"
    assert project.context_file == tmp_path / expected


def test_memory_only_rules_do_not_create_instructions_md(tmp_path: Path) -> None:
    project = ProjectInfo(name="codex", project_path=tmp_path, data_path=tmp_path / "sessions")
    rules = [
        Recommendation(
            target=RecommendationTarget.MEMORY_FILE,
            section="Preferences",
            content="- Keep it brief.",
        )
    ]
    CodexWriter().write(rules, project, dry_run=False)
    assert "Keep it brief" in (tmp_path / "AGENTS.md").read_text()
    assert not (tmp_path / "instructions.md").exists()


def test_bounds_active_instructions_and_archives_complete_rules(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# User instructions\nKeep these bytes.\n")
    project = ProjectInfo(name="codex", project_path=tmp_path, data_path=tmp_path / "sessions")
    rules = [
        Recommendation(
            target=RecommendationTarget.MEMORY_FILE,
            section=f"Rule {i}",
            content=f"- Keep learned rule {i}. " + ("é" * 120),
        )
        for i in range(8)
    ]
    writer = CodexWriter(max_bytes=1500, max_managed_bytes=1200)
    preview = writer.write(rules, project, dry_run=True)
    assert agents.read_text() == "# User instructions\nKeep these bytes.\n"
    assert len(preview.content_by_file[agents].encode("utf-8")) <= 1500
    managed = (
        preview.content_by_file[agents]
        .split("<!-- headroom:learn:start -->", 1)[1]
        .split("<!-- headroom:learn:end -->", 1)[0]
    )
    assert (
        len(managed.encode("utf-8"))
        + len("<!-- headroom:learn:start --><!-- headroom:learn:end -->")
        <= 1200
    )
    assert "consult the complete archive" in preview.content_by_file[agents]

    writer.write(rules, project, dry_run=False)
    archive = tmp_path / "AGENTS.headroom.md"
    assert archive.exists()
    assert len(agents.read_bytes()) <= 1500
    assert "Rule 7" in archive.read_text()
    assert "é" in archive.read_text()
    assert agents.read_text().startswith("# User instructions\nKeep these bytes.\n")
    active = agents.read_text()
    writer.write(rules, project, dry_run=False)
    assert agents.read_text() == active


def test_archive_keeps_omitted_rules_and_new_same_section_replaces_old(tmp_path: Path) -> None:
    project = ProjectInfo(name="codex", project_path=tmp_path, data_path=tmp_path / "sessions")
    writer = CodexWriter(max_bytes=500)
    rules = [
        Recommendation(
            target=RecommendationTarget.CONTEXT_FILE,
            section="One",
            content="- old one " + "a" * 100,
        ),
        Recommendation(
            target=RecommendationTarget.CONTEXT_FILE,
            section="Two",
            content="- retained " + "b" * 100,
        ),
    ]
    writer.write(rules, project, dry_run=False)
    updated = [
        Recommendation(
            target=RecommendationTarget.CONTEXT_FILE, section="One", content="- newest one"
        ),
    ]
    writer.write(updated, project, dry_run=False)
    archive = (tmp_path / "AGENTS.headroom.md").read_text()
    assert "- newest one" in archive
    assert "- old one" not in archive
    assert "- retained" in archive


def test_fails_before_writing_when_handwritten_content_exceeds_limit(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    original = "# Human instructions\n" + ("x" * 200)
    agents.write_text(original)
    project = ProjectInfo(name="codex", project_path=tmp_path, data_path=tmp_path / "sessions")
    rules = [
        Recommendation(target=RecommendationTarget.CONTEXT_FILE, section="Large", content="- rule")
    ]
    writer = CodexWriter(max_bytes=100)

    with pytest.raises(ValueError, match="handwritten.*exceeds.*100 bytes"):
        writer.write(rules, project, dry_run=False)

    assert agents.read_text() == original
    assert not (tmp_path / "AGENTS.headroom.md").exists()


def test_empty_recommendations_are_noop(tmp_path: Path) -> None:
    project = ProjectInfo(name="codex", project_path=tmp_path, data_path=tmp_path / "sessions")
    result = CodexWriter().write([], project, dry_run=False)
    assert result.files_written == []
    assert not (tmp_path / "AGENTS.md").exists()


def test_existing_archive_notes_survive_first_archive_creation(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "<!-- headroom:learn:start -->\n### Prior active\n- keep from active\n"
        "<!-- headroom:learn:end -->\n"
    )
    archive = tmp_path / "AGENTS.headroom.md"
    archive.write_text("# Archive notes\n\nKeep these human notes.\n")
    legacy = tmp_path / "instructions.md"
    legacy.write_text(
        "<!-- headroom:learn:start -->\n### Legacy preference\n- carry forward\n"
        "<!-- headroom:learn:end -->\n"
    )
    project = ProjectInfo(
        name="codex",
        project_path=tmp_path,
        data_path=tmp_path / "sessions",
        context_file=agents,
        memory_file=legacy,
    )
    current = [
        Recommendation(
            target=RecommendationTarget.CONTEXT_FILE,
            section="Current",
            content="- current rule",
        )
    ]

    CodexWriter().write(current, project, dry_run=False)

    content = archive.read_text()
    assert content.startswith("# Archive notes\n\nKeep these human notes.\n")
    assert "keep from active" in content
    assert "carry forward" in content
    assert "current rule" in content
