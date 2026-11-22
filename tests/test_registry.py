"""Registry behavior independent of particular Tool implementations."""

import pytest

from core.registry import DuplicateToolError, Registry, UnknownOperationError


class StubTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = []

    def execute(self, call):
        self.calls.append(call)
        return call


def test_returns_registered_instance_without_executing_it():
    registry = Registry()
    tool = StubTool("sample")

    registry.register(tool)

    assert registry.get("sample") is tool
    assert registry.get("sample") is tool
    assert tool.calls == []


def test_new_tool_can_be_used_through_the_same_lookup_interface():
    registry = Registry()
    tools = [StubTool("first"), StubTool("new_plugin")]
    for tool in tools:
        registry.register(tool)
    call = object()

    for tool in tools:
        assert registry.get(tool.name).execute(call) is call
        assert tool.calls == [call]


def test_unknown_operation_has_a_machine_readable_code_and_name():
    registry = Registry()

    with pytest.raises(UnknownOperationError) as caught:
        registry.get("missing")

    assert caught.value.code == "unknown_operation"
    assert caught.value.operation == "missing"
    assert caught.value.details == {"operation": "missing"}


def test_failed_lookup_does_not_change_registered_tools():
    registry = Registry()
    tool = StubTool("existing")
    registry.register(tool)

    with pytest.raises(UnknownOperationError):
        registry.get("missing")

    assert registry.get("existing") is tool
    with pytest.raises(UnknownOperationError):
        registry.get("missing")


def test_duplicate_name_does_not_replace_original_tool():
    registry = Registry()
    original = StubTool("same")
    replacement = StubTool("same")
    registry.register(original)

    with pytest.raises(DuplicateToolError) as caught:
        registry.register(replacement)

    assert caught.value.code == "duplicate_tool"
    assert registry.get("same") is original


def test_separate_registries_do_not_share_tools():
    first = Registry()
    second = Registry()
    first.register(StubTool("local"))

    with pytest.raises(UnknownOperationError):
        second.get("local")


def test_lookup_preserves_case_of_operation_names():
    registry = Registry()
    registry.register(StubTool("case_sensitive"))

    with pytest.raises(UnknownOperationError):
        registry.get("CASE_SENSITIVE")


@pytest.mark.parametrize("name", ["", " ", "\t", None, 42])
def test_invalid_name_is_rejected_without_registering_a_tool(name):
    registry = Registry()

    with pytest.raises(ValueError, match="non-empty string"):
        registry.register(StubTool(name))


def test_tool_without_callable_execute_is_rejected():
    class InvalidTool:
        name = "invalid"
        execute = None

    registry = Registry()

    with pytest.raises(TypeError, match="execute"):
        registry.register(InvalidTool())
    with pytest.raises(UnknownOperationError):
        registry.get("invalid")


def test_profile_returns_instances_in_configured_order_without_executing_them():
    registry = Registry()
    files = StubTool("required_files")
    sections = StubTool("readme_sections")
    registry.register(sections)
    registry.register(files)
    registry.register_profile(
        "basic",
        [(files.name, {"files": ["README.md"]}), (sections.name, {"sections": ["Title"]})],
    )

    tools = registry.get_tools_for_profile("basic")

    assert len(tools) == 2
    assert tools[0][0] is files
    assert tools[1][0] is sections
    assert tools[0][1] == {"files": ["README.md"]}
    assert tools[1][1] == {"sections": ["Title"]}
    assert files.calls == sections.calls == []


def test_unknown_profile_raises_unknown_operation_even_when_a_tool_has_that_name():
    registry = Registry()
    registry.register(StubTool("basic"))

    with pytest.raises(UnknownOperationError) as caught:
        registry.get_tools_for_profile("basic")

    assert caught.value.code == "unknown_operation"
    assert caught.value.operation == "basic"


def test_get_does_not_treat_a_profile_name_as_a_tool_name():
    registry = Registry()
    registry.register(StubTool("sample"))
    registry.register_profile("profile", [("sample", {})])

    with pytest.raises(UnknownOperationError):
        registry.get("profile")


def test_profile_configuration_and_returned_list_cannot_change_registry():
    registry = Registry()
    tool = StubTool("sample")
    registry.register(tool)
    params = {"options": {"paths": ["README.md"]}}
    entries = [(tool.name, params)]
    registry.register_profile("profile", entries)

    params["options"]["paths"].append("from-input.md")
    entries.clear()
    returned = registry.get_tools_for_profile("profile")
    returned[0][1]["options"]["paths"].append("from-output.md")
    returned.clear()

    assert registry.get_tools_for_profile("profile") == [
        (tool, {"options": {"paths": ["README.md"]}})
    ]


def test_unknown_tool_prevents_partial_profile_registration():
    registry = Registry()
    tool = StubTool("sample")
    registry.register(tool)

    with pytest.raises(UnknownOperationError) as caught:
        registry.register_profile("profile", [("sample", {}), ("missing", {})])

    assert caught.value.operation == "missing"
    with pytest.raises(UnknownOperationError):
        registry.get_tools_for_profile("profile")
    registry.register_profile("profile", [("sample", {})])
    assert registry.get_tools_for_profile("profile") == [(tool, {})]


def test_copy_failure_on_second_entry_does_not_register_a_partial_profile():
    copied_values = []

    class CopyProbe:
        def __init__(self, name, fail=False):
            self.name = name
            self.fail = fail

        def __deepcopy__(self, memo):
            copied_values.append(self.name)
            if self.fail:
                raise RuntimeError("Cannot copy second entry")
            return self.name

    registry = Registry()
    first = StubTool("first")
    second = StubTool("second")
    registry.register(first)
    registry.register(second)

    with pytest.raises(RuntimeError, match="Cannot copy second entry"):
        registry.register_profile(
            "profile",
            [
                (first.name, {"value": CopyProbe("first")}),
                (second.name, {"value": CopyProbe("second", fail=True)}),
            ],
        )

    assert copied_values == ["first", "second"]
    with pytest.raises(UnknownOperationError):
        registry.get_tools_for_profile("profile")
    assert registry.get(first.name) is first
    assert registry.get(second.name) is second

    registry.register_profile(
        "profile", [(first.name, {"value": 1}), (second.name, {"value": 2})]
    )
    assert registry.get_tools_for_profile("profile") == [
        (first, {"value": 1}), (second, {"value": 2})
    ]


def test_duplicate_profile_does_not_replace_its_tools():
    registry = Registry()
    first = StubTool("first")
    second = StubTool("second")
    registry.register(first)
    registry.register(second)
    registry.register_profile("profile", [(first.name, {"value": 1})])

    with pytest.raises(ValueError, match="already registered"):
        registry.register_profile("profile", [(second.name, {"value": 2})])

    assert registry.get_tools_for_profile("profile") == [(first, {"value": 1})]


@pytest.mark.parametrize(
    "entries",
    [[], [("sample", {}), ("sample", {})], [("", {})], [(None, {})]],
)
def test_invalid_profile_selection_is_rejected(entries):
    registry = Registry()
    registry.register(StubTool("sample"))

    with pytest.raises(ValueError):
        registry.register_profile("profile", entries)
    with pytest.raises(UnknownOperationError):
        registry.get_tools_for_profile("profile")


@pytest.mark.parametrize(
    "entries",
    ["sample", None, {"sample"}, ["sample"], [("sample",)], [("sample", [])], [("sample", {1: "value"})]],
)
def test_malformed_profile_configuration_is_rejected(entries):
    registry = Registry()

    with pytest.raises(TypeError):
        registry.register_profile("profile", entries)


@pytest.mark.parametrize("name", ["", " ", None])
def test_profile_name_must_be_a_non_empty_string(name):
    registry = Registry()
    registry.register(StubTool("sample"))

    with pytest.raises(ValueError, match="Profile name"):
        registry.register_profile(name, [("sample", {})])


def test_profile_configuration_is_specific_to_each_registry():
    first = Registry()
    second = Registry()
    first.register(StubTool("sample"))
    first.register_profile("basic", [("sample", {})])

    with pytest.raises(UnknownOperationError):
        second.get_tools_for_profile("basic")


def test_different_profiles_can_configure_the_same_tool_independently():
    registry = Registry()
    tool = StubTool("sample")
    registry.register(tool)
    registry.register_profile("first", [(tool.name, {"paths": ["A"]})])
    registry.register_profile("second", [(tool.name, {"paths": ["B"]})])

    first_tool, first_params = registry.get_tools_for_profile("first")[0]
    second_tool, second_params = registry.get_tools_for_profile("second")[0]
    first_params["paths"].clear()

    assert first_tool is second_tool is tool
    assert second_params == {"paths": ["B"]}
    assert registry.get_tools_for_profile("first")[0][1] == {"paths": ["A"]}


def test_invalid_tool_parameters_are_left_for_the_tool_to_validate():
    registry = Registry()
    tool = StubTool("sample")
    registry.register(tool)
    registry.register_profile("profile", [(tool.name, {"required_paths": []})])

    assert registry.get_tools_for_profile("profile") == [
        (tool, {"required_paths": []})
    ]
