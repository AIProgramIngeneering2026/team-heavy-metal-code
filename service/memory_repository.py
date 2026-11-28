"""In-memory Job repository for isolated tests."""

from datetime import datetime, timezone
from threading import Lock

from core.job import Job, JobState
from core.job_snapshot import JobSnapshot
from core.repository import CreateJobResult, RepositoryConflictError, StoredJob


def _record(snapshot: JobSnapshot, times: tuple[datetime, ...]) -> StoredJob:
    return StoredJob(snapshot.to_job(), times)


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, tuple[JobSnapshot, tuple[datetime, ...]]] = {}
        self._keys: dict[str, str] = {}
        self._lock = Lock()

    def get(self, job_id: str) -> StoredJob | None:
        with self._lock:
            entry = self._jobs.get(job_id)
            return _record(*entry) if entry is not None else None

    def create_if_absent(self, job: Job) -> CreateJobResult:
        snapshot = JobSnapshot.from_job(job)
        snapshot.to_job()
        if snapshot.state is not JobState.CREATED:
            raise ValueError("Only a created Job can be inserted")

        with self._lock:
            key = snapshot.idempotency_key
            if key is not None and key in self._keys:
                return CreateJobResult(_record(*self._jobs[self._keys[key]]), False)
            if snapshot.id in self._jobs:
                raise RepositoryConflictError("Job ID already exists")

            times = (datetime.now(timezone.utc),)
            result = CreateJobResult(_record(snapshot, times), True)
            self._jobs[snapshot.id] = (snapshot, times)
            if key is not None:
                self._keys[key] = snapshot.id
            return result

    def save(self, job: Job, *, expected_state: JobState) -> StoredJob:
        snapshot = JobSnapshot.from_job(job)
        snapshot.to_job()
        with self._lock:
            old, times = self._jobs[snapshot.id]
            if old.state is not expected_state:
                raise RepositoryConflictError("Stored Job state has changed")
            if (
                snapshot.history[:-1] != old.history
                or snapshot.operation != old.operation
                or snapshot.params != old.params
                or snapshot.idempotency_key != old.idempotency_key
                or (old.commit_sha is not None and snapshot.commit_sha != old.commit_sha)
            ):
                raise RepositoryConflictError("Stored Job data cannot be rewritten")

            times = (*times, max(times[-1], datetime.now(timezone.utc)))
            result = _record(snapshot, times)
            self._jobs[snapshot.id] = (snapshot, times)
            return result

    def list_by_state(self, state: JobState) -> list[StoredJob]:
        with self._lock:
            records = [
                _record(snapshot, times)
                for snapshot, times in self._jobs.values()
                if snapshot.state is state
            ]
            return sorted(records, key=lambda record: (record.created_at, record.job.id))
