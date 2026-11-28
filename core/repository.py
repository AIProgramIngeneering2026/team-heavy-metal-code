"""Storage port for Jobs; independent of SQL and HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .job import Job, JobState


class RepositoryConflictError(ValueError):
    """The stored Job no longer matches the requested write."""


@dataclass(frozen=True)
class StoredJob:
    """Detached Job with UTC persistence time for each history entry."""

    job: Job
    history_timestamps: tuple[datetime, ...]

    @property
    def created_at(self) -> datetime:
        return self.history_timestamps[0]

    @property
    def updated_at(self) -> datetime:
        return self.history_timestamps[-1]


@dataclass(frozen=True)
class CreateJobResult:
    record: StoredJob
    created: bool


class JobRepository(Protocol):
    def get(self, job_id: str) -> StoredJob | None:
        """Return detached data, or None if the Job is absent."""
        ...

    def create_if_absent(self, job: Job) -> CreateJobResult:
        """Atomically insert a created Job or return the owner of its key.

        None means no idempotency key. A duplicate ID without a matching
        key raises RepositoryConflictError. Request comparison is done by
        the caller; this operation never modifies an existing Job.
        Reject non-created input with ValueError.
        """
        ...

    def save(self, job: Job, *, expected_state: JobState) -> StoredJob:
        """Persist exactly one transition and its history atomically.

        Raise KeyError if absent, RepositoryConflictError for stale state
        or changed stored identity, parameters, SHA or history prefix.
        Invalid transitions are rejected. No same-state writes.
        The caller must own the Job and not mutate it during the call.
        """
        ...

    def list_by_state(self, state: JobState) -> list[StoredJob]:
        """Return detached Jobs ordered by creation time, then ID."""
        ...
