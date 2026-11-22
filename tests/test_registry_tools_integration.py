"""Run configured profiles through the real Tool contract and implementations."""

import pytest

from core.profiles import register_basic_profile
from core.registry import Registry
from core.required_files import RequiredFilesTool
from core.readme_sections import ReadmeSectionsTool
from core.tool_contract import RepositorySnapshot, ToolCall, ToolError, ToolResult


@pytest.fixture
def registry():
    configured = Registry()
    configured.register(RequiredFilesTool())
    configured.register(ReadmeSectionsTool())
    register_basic_profile(configured)
    return configured


def snapshot(paths, text_files):
    return RepositorySnapshot(
        repository_url="https://github.com/example/project",
        commit_sha="a" * 40,
        paths=paths,
        text_files=text_files,
    )


def test_configured_basic_profile_produces_all_five_successful_checks(registry):
    source = snapshot(
        ("README.md", "CONTRIBUTING.md"),
        {"README.md": "# Описание проекта\n## Запуск\n## Тестирование\n"},
    )

    results = [
        tool.execute(ToolCall(snapshot=source, params=params))
        for tool, params in registry.get_tools_for_profile("basic")
    ]

    assert all(isinstance(result, ToolResult) for result in results)
    checks = [check for result in results for check in result.results]
    assert [check.check_name for check in checks] == [
        "file:README.md",
        "file:CONTRIBUTING.md",
        "section:README.md:Описание проекта",
        "section:README.md:Запуск",
        "section:README.md:Тестирование",
    ]
    assert all(check.status for check in checks)


def test_missing_readme_is_a_violation_with_all_five_results(registry):
    source = snapshot(("CONTRIBUTING.md",), {})

    results = [
        tool.execute(ToolCall(snapshot=source, params=params))
        for tool, params in registry.get_tools_for_profile("basic")
    ]

    assert all(isinstance(result, ToolResult) for result in results)
    checks = [check for result in results for check in result.results]
    assert [check.status for check in checks] == [False, True, False, False, False]


def test_missing_content_for_an_existing_readme_is_a_technical_error(registry):
    source = snapshot(("README.md", "CONTRIBUTING.md"), {})
    tool, params = registry.get_tools_for_profile("basic")[1]

    result = tool.execute(ToolCall(snapshot=source, params=params))

    assert isinstance(result, ToolError)
    assert result.code == "snapshot_incomplete"


def test_the_tool_validates_parameters_returned_by_registry():
    configured = Registry()
    configured.register(RequiredFilesTool())
    configured.register_profile("invalid", [("required_files", {"paths": ["README.md"]})])
    tool, params = configured.get_tools_for_profile("invalid")[0]

    result = tool.execute(ToolCall(snapshot=snapshot((), {}), params=params))

    assert isinstance(result, ToolError)
    assert result.code == "invalid_tool_parameters"
    assert result.details["field"] == "params.required_paths"
