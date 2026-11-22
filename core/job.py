from __future__ import annotations

import copy
import threading
import uuid
from enum import Enum
from types import MappingProxyType

from .errors import InvalidStateTransition, OperationNotSupported


class JobState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


ALLOWED_TRANSITIONS = MappingProxyType({
    JobState.CREATED: frozenset({JobState.RUNNING, JobState.FAILED}),
    JobState.RUNNING: frozenset({JobState.DONE, JobState.FAILED}),
    JobState.DONE: frozenset(),
    JobState.FAILED: frozenset(),
})


class Job:
    def __init__(
        self,
        operation: str,
        params: dict,
        idempotency_key: str | None = None,
        job_id: str | None = None,
    ):
        self.id = job_id or uuid.uuid4().hex
        self.operation = operation
        self.idempotency_key = idempotency_key
        self._params = copy.deepcopy(params)

        self._state = JobState.CREATED
        self._commit_sha: str | None = None
        self._report: dict | None = None
        self._error: dict | None = None
        self._history: list[tuple[JobState | None, JobState]] = [
            (None, JobState.CREATED)
        ]
        self._lock = threading.Lock()

    @property
    def state(self) -> JobState:
        return self._state

    @property
    def params(self) -> dict:
        return copy.deepcopy(self._params)

    @property
    def commit_sha(self) -> str | None:
        return self._commit_sha

    @property
    def report(self) -> dict | None:
        return copy.deepcopy(self._report)

    @property
    def error(self) -> dict | None:
        return copy.deepcopy(self._error)

    @property
    def history(self) -> tuple[tuple[JobState | None, JobState], ...]:
        return tuple(self._history)

    def transition_to(
        self,
        target: JobState,
        *,
        commit_sha: str | None = None,
        report: dict | None = None,
        error: dict | None = None,
    ) -> None:
        target = JobState(target)

        with self._lock:
            current = self._state
            if target not in ALLOWED_TRANSITIONS[current]:
                raise InvalidStateTransition(
                    f"transition {current.value} -> {target.value} is not allowed"
                )

            # Проверить параметры до изменения Job, чтобы отказ не оставил
            # частично обновлённое состояние.
            if target is JobState.RUNNING:
                if not isinstance(commit_sha, str) or not commit_sha.strip():
                    raise ValueError("Для перехода в running нужен commit_sha")

            if target is JobState.DONE and report is None:
                raise ValueError("Для перехода в done нужен сохранённый отчёт")

            if target is JobState.FAILED and error is None:
                raise ValueError("Для перехода в failed нужна причина ошибки")

            if target is JobState.RUNNING:
                self._commit_sha = commit_sha
            elif target is JobState.DONE:
                self._report = copy.deepcopy(report)
            elif target is JobState.FAILED:
                self._error = copy.deepcopy(error)

            self._history.append((current, target))
            self._state = target

    def start(self, commit_sha: str) -> None:
        self.transition_to(JobState.RUNNING, commit_sha=commit_sha)

    def finish(self, report: dict) -> None:
        self.transition_to(JobState.DONE, report=report)

    def fail(self, error: dict) -> None:
        self.transition_to(JobState.FAILED, error=error)

    def recover_after_restart(self) -> None:
        """Оставить created в очереди; прерванный running пометить failed."""
        with self._lock:
            if self._state is JobState.CREATED:
                return

            if self._state is not JobState.RUNNING:
                return

            self._error = {
                "code": "interrupted",
                "message": "Job interrupted by service restart",
            }
            self._history.append((JobState.RUNNING, JobState.FAILED))
            self._state = JobState.FAILED

    def cancel(self) -> None:
        raise OperationNotSupported("job cancellation is not supported")

