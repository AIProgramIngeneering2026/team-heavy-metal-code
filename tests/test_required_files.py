
import pytest


from core.required_files import RequiredFilesTool
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
        paths=("README.md", "CONTRIBUTING.md", "src/main.py"),
        text_files={"README.md": "# Описание проекта"},
    )


def test_all_required_files_present(snapshot):
    # Arrange
    tool = RequiredFilesTool()
    call = ToolCall(
        snapshot=snapshot,
        params={
            "required_paths": ["README.md", "CONTRIBUTING.md"]
        },
    )

    # Act
    result = tool.execute(call)

    # Assert
    assert isinstance(result, ToolResult)
    assert result.tool == "required_files"
    assert [item.check_name for item in result.results] == [
        "file:README.md",
        "file:CONTRIBUTING.md",
    ]
    assert [item.status for item in result.results] == [True, True]
    assert all(item.details for item in result.results)


def test_missing_file_is_not_technical_error(snapshot):
    # Arrange
    tool = RequiredFilesTool()
    call = ToolCall(
        snapshot=snapshot,
        params={"required_paths": ["README.md", "LICENSE"]},
    )

    # Act
    result = tool.execute(call)

    # Assert
    assert isinstance(result, ToolResult)
    assert [item.status for item in result.results] == [True, False]
    assert result.results[1].check_name == "file:LICENSE"
    assert result.results[1].details


def test_missing_readme_returns_failed_check():
    # Arrange
    snapshot = RepositorySnapshot(
        repository_url="https://github.com/example/project",
        commit_sha="abc123",
        paths=("CONTRIBUTING.md",),
        text_files={},
    )
    call = ToolCall(
        snapshot=snapshot,
        params={"required_paths": ["README.md"]},
    )

    # Act
    result = RequiredFilesTool().execute(call)

    # Assert
    assert isinstance(result, ToolResult)
    assert result.results[0].status is False


@pytest.mark.parametrize(
    "required_paths, expected_field",
    [
        (None, "params.required_paths"),
        ([], "params.required_paths"),
        ("README.md", "params.required_paths"),
        (["README.md", "README.md"], "params.required_paths[1]"),
        (["../README.md"], "params.required_paths[0]"),
        (["/README.md"], "params.required_paths[0]"),
        ([""], "params.required_paths[0]"),
        ([123], "params.required_paths[0]"),
        (["C:/README.md"], "params.required_paths[0]"),
    ],
)
def test_invalid_required_paths(
    snapshot, required_paths, expected_field
):
    # Arrange
    call = ToolCall(
        snapshot=snapshot,
        params={"required_paths": required_paths},
    )

    # Act
    result = RequiredFilesTool().execute(call)

    # Assert
    assert isinstance(result, ToolError)
    assert result.code == "invalid_tool_parameters"
    assert result.details["field"] == expected_field
    assert result.message



@pytest.mark.parametrize(
    "invalid_params",
    [
        None,
        [],
        "wrong_params",
    ],
)
def test_invalid_params_type_returns_error(snapshot, invalid_params):
    # Arrange
    # Намеренно передаём некорректный тип для проверки валидации.
    # noinspection PyTypeChecker
    call = ToolCall(
        snapshot=snapshot,
        params=invalid_params,
    )

    # Act
    result = RequiredFilesTool().execute(call)

    # Assert
    assert isinstance(result, ToolError)
    assert result.code == "invalid_tool_parameters"
    assert result.details is not None
    assert result.details["field"] == "params"
    assert result.message

