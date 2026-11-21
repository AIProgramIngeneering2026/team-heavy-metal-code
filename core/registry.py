"""Registration and lookup of tools without knowledge of their implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tool_contract import Tool


class UnknownOperationError(LookupError):
    """The requested tool or profile is not registered."""

    code = "unknown_operation"

    def __init__(self, operation: str) -> None:
        self.operation = operation
        self.details = {"operation": operation}
        super().__init__(f"Unknown operation: {operation}")


class DuplicateToolError(ValueError):
    """Registration must not silently replace an existing tool."""

    code = "duplicate_tool"

    def __init__(self, operation: str) -> None:
        self.operation = operation
        self.details = {"operation": operation}
        super().__init__(f"Tool is already registered: {operation}")


class Registry:
    """Store tool instances by their exact, case-sensitive names.

    Registration of tools and profiles belongs to application setup.
    Profiles select tool instances and their configured parameters in a defined
    order. Registry does not execute tools or validate tool-specific parameters.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._profiles: dict[str, tuple[tuple[str, dict[str, object]], ...]] = {}

    def register(self, tool: Tool) -> None:
        name = tool.name
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Tool name must be a non-empty string")
        if not callable(getattr(tool, "execute", None)):
            raise TypeError("Tool must provide a callable execute method")
        if name in self._tools:
            raise DuplicateToolError(name)
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownOperationError(name) from None

    def register_profile(
        self,
        name: str,
        entries: Sequence[tuple[str, Mapping[str, object]]],
    ) -> None:
        """Register ordered (tool name, parameters) pairs atomically."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Profile name must be a non-empty string")
        if name in self._profiles:
            raise ValueError(f"Profile is already registered: {name}")
        if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
            raise TypeError("Profile entries must be an ordered sequence")
        if not entries:
            raise ValueError("Profile must contain at least one tool")
        configured_tools = []
        seen = set()
        for entry in entries:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError("Profile entry must be a (tool name, parameters) tuple")
            tool_name, params = entry
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise ValueError("Tool name must be a non-empty string")
            if tool_name in seen:
                raise ValueError("Profile must not contain duplicate tool names")
            if not isinstance(params, Mapping) or any(
                not isinstance(key, str) for key in params
            ):
                raise TypeError("Tool parameters must be a mapping with string keys")
            self.get(tool_name)
            configured_tools.append((tool_name, deepcopy(dict(params))))
            seen.add(tool_name)
        self._profiles[name] = tuple(configured_tools)

    def get_tools_for_profile(
        self, profile_name: str
    ) -> list[tuple[Tool, dict[str, object]]]:
        """Return tool instances with independent copies of their parameters."""
        try:
            entries = self._profiles[profile_name]
        except KeyError:
            raise UnknownOperationError(profile_name) from None
        return [(self.get(name), deepcopy(params)) for name, params in entries]
