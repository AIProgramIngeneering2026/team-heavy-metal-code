import threading

import pytest

from core import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransition,
    Job,
    JobState,
    OperationNotSupported,
)


def make_job() -> Job:
    return Job(operation="check_repository", params={})


def test_normal_successful_lifecycle():
    """Обычный путь: created → running → done."""
    job = make_job()
    report = {"compliant": False, "checks": [{"name": "README.md", "passed": False}]}

    job.start("commit-123")
    assert job.state is JobState.RUNNING
    assert job.commit_sha == "commit-123"
    assert job.report is None
    assert job.error is None

    job.finish(report)
    assert job.state is JobState.DONE
    assert job.report == report
    assert job.error is None


@pytest.mark.parametrize(
    "initial_state",
    [JobState.CREATED, JobState.RUNNING],
)
def test_technical_failure_is_allowed_from_created_or_running(initial_state):
    """Технический отказ возможен до получения SHA и во время проверок."""
    job = make_job()
    if initial_state is JobState.RUNNING:
        job.start("commit-123")

    error = {"code": "github_timeout", "message": "GitHub API timed out"}
    job.fail(error)

    assert job.state is JobState.FAILED
    assert job.error == error
    assert job.report is None


@pytest.mark.parametrize("terminal_state", [JobState.DONE, JobState.FAILED])
def test_terminal_job_cannot_change_state(terminal_state):
    """Завершённые задания нельзя запустить или завершить повторно."""
    job = make_job()
    job.start("commit-123")

    if terminal_state is JobState.DONE:
        job.finish({"checks": []})
    else:
        job.fail({"code": "timeout", "message": "Timed out"})

    state_before = job.state
    history_before = job.history

    with pytest.raises(InvalidStateTransition):
        job.start("another-commit")

    assert job.state is state_before
    assert job.history == history_before


def test_created_job_cannot_finish_without_running():
    """Злодейство З5: нельзя получить успешный результат, не начав обработку."""
    job = make_job()
    history_before = job.history

    with pytest.raises(InvalidStateTransition):
        job.finish({"checks": []})

    assert job.state is JobState.CREATED
    assert job.report is None
    assert job.history == history_before


def test_failed_job_cannot_become_done():
    """Злодейство З4: failed нельзя превратить в done."""
    job = make_job()
    job.fail({"code": "github_error", "message": "Request failed"})
    history_before = job.history

    with pytest.raises(InvalidStateTransition):
        job.finish({"checks": []})

    assert job.state is JobState.FAILED
    assert job.report is None
    assert job.history == history_before


def test_done_job_cannot_become_failed():
    """Злодейство З4: done нельзя превратить в failed."""
    job = make_job()
    job.start("commit-123")
    job.finish({"checks": []})
    history_before = job.history

    with pytest.raises(InvalidStateTransition):
        job.fail({"code": "late_error", "message": "Late failure"})

    assert job.state is JobState.DONE
    assert job.error is None
    assert job.history == history_before


def test_running_job_cannot_be_started_twice():
    """Злодейство З1: один Job нельзя запустить повторно, пока он running."""
    job = make_job()
    job.start("commit-123")
    history_before = job.history

    with pytest.raises(InvalidStateTransition):
        job.start("another-commit")

    assert job.state is JobState.RUNNING
    assert job.commit_sha == "commit-123"
    assert job.history == history_before


def test_done_job_cannot_be_started_again():
    """Злодейство З6: завершённый Job не запускается повторно."""
    job = make_job()
    job.start("commit-123")
    job.finish({"checks": []})
    history_before = job.history

    with pytest.raises(InvalidStateTransition):
        job.start("commit-456")

    assert job.state is JobState.DONE
    assert job.commit_sha == "commit-123"
    assert job.history == history_before


def test_cancel_is_not_supported():
    """Злодейство З3 неприменимо как отмена: команда явно не поддерживается."""
    job = make_job()
    history_before = job.history

    with pytest.raises(OperationNotSupported):
        job.cancel()

    assert job.state is JobState.CREATED
    assert job.history == history_before


def test_restart_fails_running_job_as_interrupted():
    """Злодейство З2: работающий Job после перезапуска становится failed."""
    job = make_job()
    job.start("commit-123")

    job.recover_after_restart()

    assert job.state is JobState.FAILED
    assert job.error["code"] == "interrupted"
    assert job.report is None


def test_restart_leaves_created_job_unchanged():
    """Созданное задание можно подобрать после перезапуска."""
    job = make_job()

    job.recover_after_restart()

    assert job.state is JobState.CREATED
    assert job.error is None


def test_restart_does_not_change_terminal_job():
    """Перезапуск не должен менять уже завершённое задание."""
    job = make_job()
    job.start("commit-123")
    job.finish({"checks": []})
    history_before = job.history

    job.recover_after_restart()

    assert job.state is JobState.DONE
    assert job.history == history_before


def test_invalid_commit_sha_does_not_change_job():
    """Неверные параметры не должны частично менять состояние."""
    job = make_job()

    with pytest.raises(ValueError):
        job.start(" ")

    assert job.state is JobState.CREATED
    assert job.commit_sha is None


def test_done_requires_report():
    """Нельзя перевести running в done без отчёта."""
    job = make_job()
    job.start("commit-123")
    history_before = job.history

    with pytest.raises(ValueError):
        job.finish(None)

    assert job.state is JobState.RUNNING
    assert job.report is None
    assert job.history == history_before


def test_all_forbidden_transitions_are_rejected():
    """Перебирает пары состояний, запрещённые диаграммой."""
    for source, targets in ALLOWED_TRANSITIONS.items():
        for target in JobState:
            if target in targets:
                continue

            job = make_job()

            # Подготавливаем Job в исходном состоянии.
            if source is JobState.RUNNING:
                job.start("commit-123")
            elif source is JobState.DONE:
                job.start("commit-123")
                job.finish({"checks": []})
            elif source is JobState.FAILED:
                job.fail({"code": "error", "message": "Failed"})

            state_before = job.state
            history_before = job.history

            with pytest.raises(
                InvalidStateTransition,
                match=f"{source.value} -> {target.value}",
            ):
                job.transition_to(
                    target,
                    commit_sha="commit-456",
                    report={"checks": []},
                    error={"code": "error", "message": "Failed"},
                )

            assert job.state is state_before
            assert job.history == history_before


def test_state_cannot_be_assigned_directly():
    """Состояние изменяется только через методы перехода."""
    job = make_job()

    with pytest.raises(AttributeError):
        job.state = JobState.DONE


def test_concurrent_start_is_accepted_only_once():
    """Злодейство З1: параллельные start не должны дважды принять Job."""
    job = make_job()
    barrier = threading.Barrier(8)
    outcomes = []
    outcomes_lock = threading.Lock()

    def attempt_start(index: int) -> None:
        barrier.wait()
        try:
            job.start(f"commit-{index}")
            outcome = "accepted"
        except InvalidStateTransition:
            outcome = "rejected"

        with outcomes_lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(target=attempt_start, args=(index,))
        for index in range(8)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("accepted") == 1
    assert outcomes.count("rejected") == 7
    assert job.state is JobState.RUNNING

