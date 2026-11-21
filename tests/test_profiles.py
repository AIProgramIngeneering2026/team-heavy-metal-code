"""The basic profile is configuration rather than Dispatcher logic."""

import pytest

from core.profiles import register_basic_profile
from core.registry import Registry, UnknownOperationError


class StubTool:
    def __init__(self, name):
        self.name = name

    def execute(self, call):
        raise AssertionError("Profile configuration must not execute tools")


def test_basic_profile_uses_the_tool_contract_names_and_parameters():
    registry = Registry()
    files = StubTool("required_files")
    sections = StubTool("readme_sections")
    registry.register(files)
    registry.register(sections)

    register_basic_profile(registry)

    assert registry.get_tools_for_profile("basic") == [
        (files, {"required_paths": ["README.md", "CONTRIBUTING.md"]}),
        (
            sections,
            {
                "readme_path": "README.md",
                "required_sections": ["Описание проекта", "Запуск", "Тестирование"],
            },
        ),
    ]


def test_basic_profile_requires_both_registered_tools():
    registry = Registry()
    registry.register(StubTool("required_files"))

    with pytest.raises(UnknownOperationError) as caught:
        register_basic_profile(registry)

    assert caught.value.operation == "readme_sections"
    with pytest.raises(UnknownOperationError):
        registry.get_tools_for_profile("basic")
