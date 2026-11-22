
from dataclasses import dataclass
from typing import Mapping, Protocol
from types import MappingProxyType

@dataclass(frozen=True)
class RepositorySnapshot:
    repository_url: str
    commit_sha: str
    paths: tuple[str, ...]
    text_files: Mapping[str, str]

    def __post_init__(self):
        object.__setattr__(
            self,
            "text_files",
            MappingProxyType(dict(self.text_files)),
        )



@dataclass(frozen=True)
class ToolCall:
    snapshot: RepositorySnapshot
    params: dict[str, object]


@dataclass(frozen=True)
class CheckResult:
    check_name: str
    status: bool
    details: str


@dataclass(frozen=True)
class ToolResult:
    tool: str
    results: list[CheckResult]


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    details: dict[str, str] | None = None


class Tool(Protocol):
    name: str

    def execute(self, call: ToolCall) -> ToolResult | ToolError:
        ...
