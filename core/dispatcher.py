"""Dispatcher: runs the tools of a profile and turns their outcome into Job transitions.

Dispatcher knows no concrete Tool: tools come from the Registry and are called
only through the common Tool contract. The rules of allowed transitions live in
Job; Dispatcher only asks Job to move and never swallows its errors.
The core imports no web framework and no database driver.
"""

from __future__ import annotations

from .job import Job
from .registry import Registry, UnknownOperationError
from .tool_contract import RepositorySnapshot, ToolCall, ToolError, ToolResult

TOOL_EXECUTION_FAILED = "tool_execution_failed"


class Dispatcher:
    """Drive one Job through the tools of a profile."""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def run(
        self,
        job: Job,
        profile_name: str,
        snapshot: RepositorySnapshot,
    ) -> dict[str, object] | None:
        """Run all tools of the profile on one snapshot.

        Returns the report if the Job became done, None if it became failed.
        Invalid Job transitions raise InvalidStateTransition from Job itself.
        An unknown profile fails the Job and re-raises UnknownOperationError.
        """
        try:
            configured_tools = self._registry.get_tools_for_profile(profile_name)
        except UnknownOperationError as unknown:
            job.fail(
                {
                    "code": unknown.code,
                    "message": str(unknown),
                    "details": dict(unknown.details),
                }
            )
            raise

        # Job rejects this if it is not in `created`: no tool is run in that case.
        job.start(snapshot.commit_sha)

        checks: list[dict[str, object]] = []
        for tool, params in configured_tools:
            try:
                outcome = tool.execute(ToolCall(snapshot=snapshot, params=params))
            except Exception:
                job.fail(
                    {
                        "code": TOOL_EXECUTION_FAILED,
                        "message": "Tool execution failed",
                        "details": {"tool": tool.name},
                    }
                )
                return None

            if isinstance(outcome, ToolError):
                error: dict[str, object] = {
                    "code": outcome.code,
                    "message": outcome.message,
                }
                if outcome.details:
                    error["details"] = dict(outcome.details)
                job.fail(error)
                return None

            if not isinstance(outcome, ToolResult):
                job.fail(
                    {
                        "code": TOOL_EXECUTION_FAILED,
                        "message": "Tool returned an unexpected result",
                        "details": {"tool": tool.name},
                    }
                )
                return None

            for check in outcome.results:
                checks.append(
                    {
                        "check_name": check.check_name,
                        "status": check.status,
                        "details": check.details,
                    }
                )

        report: dict[str, object] = {
            "commit_sha": snapshot.commit_sha,
            "repository_url": snapshot.repository_url,
            "profile": profile_name,
            "compliant": all(check["status"] for check in checks),
            "results": checks,
        }
        job.finish(report)
        return report
