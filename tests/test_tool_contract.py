
import pytest
from typing import MutableMapping, cast

from core.tool_contract import RepositorySnapshot



def test_snapshot_text_files_cannot_be_modified():
    # Arrange
    snapshot = RepositorySnapshot(
        repository_url="https://github.com/example/project",
        commit_sha="abc123",
        paths=("README.md",),
        text_files={"README.md": "# Проект"},
    )

    # Act / Assert
    mutable_view = cast(
        MutableMapping[str, str],
        snapshot.text_files,
    )

    with pytest.raises(TypeError):
        mutable_view["README.md"] = "# Изменённый проект"

    assert snapshot.text_files["README.md"] == "# Проект"



def test_snapshot_is_independent_of_original_dictionary():
    # Arrange
    original_files = {"README.md": "# Проект"}

    snapshot = RepositorySnapshot(
        repository_url="https://github.com/example/project",
        commit_sha="abc123",
        paths=("README.md",),
        text_files=original_files,
    )

    # Act
    original_files["README.md"] = "# Изменённый проект"

    # Assert
    assert snapshot.text_files["README.md"] == "# Проект"
