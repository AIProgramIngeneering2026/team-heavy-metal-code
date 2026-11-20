
import pytest

from core.readme_sections import ReadmeSectionsTool
from core.tool_contract import (
    RepositorySnapshot,
    ToolCall,
    ToolError,
    ToolResult,
)


@pytest.fixture
def snapshot():
    return RepositorySnapshot(
        repository_url="https://github.com/example/project",
        commit_sha="abc123",
        paths=("README.md", "CONTRIBUTING.md"),
        text_files={
            "README.md": (
                "# Описание проекта\n"
                "\n"
                "## Запуск\n"
                "\n"
                "### Тестирование\n"
                "\n"
                "Установка упоминается только в тексте.\n"
                "\n"
                "```python\n"
                "## Скрытый раздел\n"
                "```\n"
            )
        },
    )


def test_all_required_sections_present(snapshot):
    # Arrange
    call = ToolCall(
        snapshot=snapshot,
        params={
            "readme_path": "README.md",
            "required_sections": [
                "Описание проекта",
                "Запуск",
                "Тестирование",
            ],
        },
    )

    # Act
    result = ReadmeSectionsTool().execute(call)

    # Assert
    assert isinstance(result, ToolResult)
    assert result.tool == "readme_sections"
    assert [item.status for item in result.results] == [
        True, True, True
    ]
    assert [item.check_name for item in result.results] == [
        "section:README.md:Описание проекта",
        "section:README.md:Запуск",
        "section:README.md:Тестирование",
    ]
    assert all(item.details for item in result.results)


def test_missing_section_is_failed_check(snapshot):
    call = ToolCall(
        snapshot=snapshot,
        params={
            "readme_path": "README.md",
            "required_sections": ["Запуск", "Развёртывание"],
        },
    )

    result = ReadmeSectionsTool().execute(call)

    assert isinstance(result, ToolResult)
    assert [item.status for item in result.results] == [
        True, False
    ]


def test_word_in_paragraph_is_not_heading(snapshot):
    call = ToolCall(
        snapshot=snapshot,
        params={
            "readme_path": "README.md",
            "required_sections": ["Установка"],
        },
    )

    result = ReadmeSectionsTool().execute(call)

    assert isinstance(result, ToolResult)
    assert result.results[0].status is False


def test_heading_inside_code_block_is_ignored(snapshot):
    call = ToolCall(
        snapshot=snapshot,
        params={
            "readme_path": "README.md",
            "required_sections": ["Скрытый раздел"],
        },
    )

    result = ReadmeSectionsTool().execute(call)

    assert isinstance(result, ToolResult)
    assert result.results[0].status is False


def test_heading_is_case_sensitive(snapshot):
    call = ToolCall(
        snapshot=snapshot,
        params={
            "readme_path": "README.md",
            "required_sections": ["запуск"],
        },
    )

    result = ReadmeSectionsTool().execute(call)

    assert isinstance(result, ToolResult)
    assert result.results[0].status is False


def test_section_name_is_trimmed(snapshot):
    call = ToolCall(
        snapshot=snapshot,
        params={
            "readme_path": "README.md",
            "required_sections": ["  Запуск  "],
        },
    )

    result = ReadmeSectionsTool().execute(call)

    assert isinstance(result, ToolResult)
    assert result.results[0].status is True
    assert result.results[0].check_name == (
        "section:README.md:Запуск"
    )


def test_missing_readme_returns_all_failed_checks():
    snapshot = RepositorySnapshot(
        repository_url="https://github.com/example/project",
        commit_sha="abc123",
        paths=("CONTRIBUTING.md",),
        text_files={},
    )

    call = ToolCall(
        snapshot=snapshot,
        params={
            "readme_path": "README.md",
            "required_sections": [
                "Описание проекта",
                "Запуск",
                "Тестирование",
            ],
        },
    )

    result = ReadmeSectionsTool().execute(call)

    assert isinstance(result, ToolResult)
    assert len(result.results) == 3
    assert all(not item.status for item in result.results)


def test_incomplete_snapshot_returns_error():
    snapshot = RepositorySnapshot(
        repository_url="https://github.com/example/project",
        commit_sha="abc123",
        paths=("README.md",),
        text_files={},
    )

    call = ToolCall(
        snapshot=snapshot,
        params={
            "readme_path": "README.md",
            "required_sections": ["Запуск"],
        },
    )

    result = ReadmeSectionsTool().execute(call)

    assert isinstance(result, ToolError)
    assert result.code == "snapshot_incomplete"


@pytest.mark.parametrize(
    "params, expected_field",
    [
        (
            {"required_sections": ["Запуск"]},
            "params.readme_path",
        ),
        (
            {
                "readme_path": "../README.md",
                "required_sections": ["Запуск"],
            },
            "params.readme_path",
        ),
        (
            {
                "readme_path": 123,
                "required_sections": ["Запуск"],
            },
            "params.readme_path",
        ),
        (
            {
                "readme_path": "README.md",
                "required_sections": [],
            },
            "params.required_sections",
        ),
        (
            {
                "readme_path": "README.md",
                "required_sections": "Запуск",
            },
            "params.required_sections",
        ),
        (
            {
                "readme_path": "README.md",
                "required_sections": ["Запуск", "Запуск"],
            },
            "params.required_sections[1]",
        ),
        (
            {
                "readme_path": "README.md",
                "required_sections": [123],
            },
            "params.required_sections[0]",
        ),
        (
            {
                "readme_path": "README.md",
                "required_sections": [""],
            },
            "params.required_sections[0]",
        ),
    ],
)
def test_invalid_parameters(snapshot, params, expected_field):
    call = ToolCall(
        snapshot=snapshot,
        params=params,
    )

    result = ReadmeSectionsTool().execute(call)

    assert isinstance(result, ToolError)
    assert result.code == "invalid_tool_parameters"
    assert result.details is not None
    assert result.details["field"] == expected_field
    assert result.message
