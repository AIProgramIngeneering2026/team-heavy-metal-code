"""Proposed boundary between the HTTP adapter and the job service (p4 block 3)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from core.job import JobState


@dataclass(frozen=True)
class JobView:
    """A saved snapshot; timestamps must include a timezone.

    report is the existing Dispatcher report (compliant/results), not HTTP JSON.
    The service supplies copied data and owns persistence and execution.
    """

    id: str
    state: JobState
    created_at: datetime
    updated_at: datetime
    report: dict | None = None
    error: dict | None = None
    recommendations: dict | None = None


@dataclass(frozen=True)
class CreationResult:
    job: JobView
    created: bool


class JobService(Protocol):
    def create_job(
        self, *, repository_url: str, profile: str, idempotency_key: str
    ) -> CreationResult:
        """Save a new job, return an existing one, or raise a conflict.

        The service owns durable idempotency and scheduling. HTTP never starts
        tools and must not treat an in-memory adapter as persistent storage.
        """
        ...

    def get_job(self, job_id: str) -> JobView:
        """Read saved data without running a job; raise JobNotFoundError if absent."""
        ...
