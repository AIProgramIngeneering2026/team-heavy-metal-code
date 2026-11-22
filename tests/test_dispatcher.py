"""Dispatcher behavior with the real Job and stub Tools."""

import pytest

from core.dispatcher import Dispatcher
from core.errors import InvalidStateTransition, OperationNotSupported
from core.job import Job, JobState
from core.registry import Registry, UnknownOperationError
from core.tool_contract import CheckResult, RepositorySnapshot, ToolError, ToolResult

SNAPSHOT = RepositorySnapshot(
    repository_url="https://github.com/o/r",
    commit_sha="abc123",
    paths=("README.md",),
    text_files={},
)


class StubTool:
    def __init__(self, name, outcome=None, raises=None):
        self.name = name
        self.outcome = outcome
        self.raises = raises
        self.calls = []

    def execute(self, call):
        self.calls.append(call)
        if self.raises:
            raise self.raises
        if self.outcome is not None:
            return self.outcome
        return ToolResult(self.name, [CheckResult(f"check:{self.name}", True, "ok")])


def make(*tools, profile="p"):
    registry = Registry()
    for tool in tools:
        registry.register(tool)
    registry.register_profile(profile, [(tool.name, {"k": tool.name}) for tool in tools])
    return Dispatcher(registry)


def new_job():
    return Job("p", {})


# --- обычный путь ---

def test_normal_path_created_running_done_with_report():
    first, second = StubTool("first"), StubTool("second")
    job = new_job()

    report = make(first, second).run(job, "p", SNAPSHOT)

    assert job.state is JobState.DONE
    assert job.commit_sha == "abc123"
    assert job.report == report
    assert [c["check_name"] for c in report["results"]] == ["check:first", "check:second"]
    assert report["compliant"] is True
    assert [step[1] for step in job.history] == [
        JobState.CREATED,
        JobState.RUNNING,
        JobState.DONE,
    ]
    assert first.calls[0].params == {"k": "first"}
    assert first.calls[0].snapshot is SNAPSHOT


def test_violations_do_not_fail_the_job():
    tool = StubTool("t", ToolResult("t", [CheckResult("file:X", False, "missing")]))
    job = new_job()

    report = make(tool).run(job, "p", SNAPSHOT)

    assert job.state is JobState.DONE
    assert report["compliant"] is False


def test_new_tool_works_without_changing_dispatcher():
    class BrandNewTool(StubTool):
        pass

    job = new_job()
    make(BrandNewTool("brand_new")).run(job, "p", SNAPSHOT)
    assert job.state is JobState.DONE


# --- падение Tool и ToolError ---

def test_tool_exception_fails_the_job_without_leaking_details():
    tool = StubTool("boom", raises=RuntimeError("secret internals"))
    job = new_job()

    assert make(tool).run(job, "p", SNAPSHOT) is None

    assert job.state is JobState.FAILED
    assert job.error["code"] == "tool_execution_failed"
    assert "secret" not in job.error["message"]
    assert job.report is None


def test_tool_error_fails_the_job_with_its_code_and_field():
    error = ToolError(
        "invalid_tool_parameters", "bad", {"field": "params.required_paths"}
    )
    job = new_job()

    assert make(StubTool("t", error)).run(job, "p", SNAPSHOT) is None

    assert job.state is JobState.FAILED
    assert job.error["code"] == "invalid_tool_parameters"
    assert job.error["details"] == {"field": "params.required_paths"}


def test_failure_of_one_tool_stops_the_rest_and_gives_no_report():
    later = StubTool("later")
    job = new_job()

    make(StubTool("bad", ToolError("x", "y")), later).run(job, "p", SNAPSHOT)

    assert job.state is JobState.FAILED
    assert later.calls == []
    assert job.report is None


def test_unexpected_tool_result_fails_the_job():
    job = new_job()
    make(StubTool("odd", outcome="not a result")).run(job, "p", SNAPSHOT)
    assert job.state is JobState.FAILED
    assert job.error["code"] == "tool_execution_failed"


# --- неизвестная операция ---

def test_unknown_profile_raises_unknown_operation_and_fails_created_job():
    job = new_job()

    with pytest.raises(UnknownOperationError) as caught:
        make(StubTool("t")).run(job, "missing", SNAPSHOT)

    assert caught.value.code == "unknown_operation"
    assert job.state is JobState.FAILED
    assert job.error["code"] == "unknown_operation"


# --- злодейства, применимые к Dispatcher ---

def test_z1_second_run_on_running_job_is_rejected_and_tool_not_started():
    tool = StubTool("t")
    dispatcher = make(tool)
    job = new_job()
    job.start("abc123")  # Tool уже работает

    with pytest.raises(InvalidStateTransition):
        dispatcher.run(job, "p", SNAPSHOT)

    assert tool.calls == []
    assert job.state is JobState.RUNNING


def test_z2_job_interrupted_by_restart_is_not_left_running_nor_resumed():
    tool = StubTool("t")
    dispatcher = make(tool)
    job = new_job()
    job.start("abc123")

    job.recover_after_restart()

    assert job.state is JobState.FAILED
    assert job.error["code"] == "interrupted"
    with pytest.raises(InvalidStateTransition):
        dispatcher.run(job, "p", SNAPSHOT)
    assert tool.calls == []


def test_z3_cancel_is_not_supported_so_cancelled_job_cannot_become_done():
    job = new_job()
    with pytest.raises(OperationNotSupported):
        job.cancel()
    assert job.state is JobState.CREATED


def test_z4_failed_job_does_not_become_done_by_rerun():
    tool = StubTool("t")
    dispatcher = make(tool)
    job = new_job()
    job.start("abc123")
    job.fail({"code": "x", "message": "y"})

    with pytest.raises(InvalidStateTransition):
        dispatcher.run(job, "p", SNAPSHOT)

    assert job.state is JobState.FAILED
    assert tool.calls == []


def test_z5_done_is_never_reached_without_running():
    job = new_job()
    with pytest.raises(InvalidStateTransition):
        job.finish({"results": []})
    assert job.state is JobState.CREATED

    make(StubTool("t")).run(job, "p", SNAPSHOT)
    assert [step[1] for step in job.history] == [
        JobState.CREATED,
        JobState.RUNNING,
        JobState.DONE,
    ]


def test_z6_done_job_is_not_run_again_and_report_is_kept():
    tool = StubTool("t")
    dispatcher = make(tool)
    job = new_job()
    report = dispatcher.run(job, "p", SNAPSHOT)

    with pytest.raises(InvalidStateTransition):
        dispatcher.run(job, "p", SNAPSHOT)

    assert len(tool.calls) == 1
    assert job.state is JobState.DONE
    assert job.report == report
