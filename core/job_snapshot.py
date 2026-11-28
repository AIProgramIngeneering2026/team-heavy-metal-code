
"""Detached representation of a Job for persistence and restoration."""

from __future__ import annotations

from dataclasses import dataclass

from .job import Job, JobState


@dataclass(frozen=True)
class JobSnapshot:
    id: str
    operation: str
    params: dict
    idempotency_key: str | None
    state: JobState
    commit_sha: str | None
    report: dict | None
    error: dict | None
    history: tuple[tuple[JobState | None, JobState], ...]

    @classmethod
    def from_job(cls, job: Job) -> JobSnapshot:
        """Capture a caller-owned Job that is not being changed concurrently."""
        return cls(
            id=job.id,
            operation=job.operation,
            params=job.params,
            idempotency_key=job.idempotency_key,
            state=job.state,
            commit_sha=job.commit_sha,
            report=job.report,
            error=job.error,
            history=job.history,
        )

    def to_job(self) -> Job:
        """Restore via domain transitions, rejecting inconsistent saved data."""
        job = Job(
            operation=self.operation,
            params=self.params,
            idempotency_key=self.idempotency_key,
            job_id=self.id,
        )

        for _, target in self.history[1:]:
            job.transition_to(
                target,
                commit_sha=self.commit_sha,
                report=self.report,
                error=self.error,
            )

        if JobSnapshot.from_job(job) != self:
            raise ValueError("Inconsistent saved Job snapshot")

        return job
