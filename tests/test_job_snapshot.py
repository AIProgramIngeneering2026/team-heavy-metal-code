
from dataclasses import replace

import pytest

from core.job import Job, JobState
from core.job_snapshot import JobSnapshot


def make_job() -> Job:
    return Job(
        operation="check_repository",
        params={"profile": "basic", "nested": {"value": 1}},
        idempotency_key="request-1",
        job_id="job-1",
    )


@pytest.mark.parametrize(
    "path",
    [
        "created",
        "running",
        "done",
        "failed_before_sha",
        "failed_after_sha",
        "interrupted",
    ],
)
def test_snapshot_round_trip_preserves_job(path):
    job = make_job()

    if path in {"running", "done", "failed_after_sha", "interrupted"}:
        job.start("a" * 40)

    if path == "done":
        job.finish({"compliant": False, "results": []})
    elif path in {"failed_before_sha", "failed_after_sha"}:
        job.fail({"code": "technical_error"})
    elif path == "interrupted":
        job.recover_after_restart()

    snapshot = JobSnapshot.from_job(job)
    restored = snapshot.to_job()

    assert restored is not job
    assert JobSnapshot.from_job(restored) == snapshot


@pytest.mark.parametrize(
    "changes",
    [
        {"report": None},
        {"commit_sha": None},
        {"error": {"code": "unexpected"}},
        {"state": JobState.RUNNING},
        {"history": ()},
        {
            "history": (
                (None, JobState.CREATED),
                (JobState.CREATED, JobState.DONE),
            )
        },
        {
            "history": (
                (None, JobState.CREATED),
                (JobState.FAILED, JobState.RUNNING),
                (JobState.RUNNING, JobState.DONE),
            )
        },
    ],
)
def test_snapshot_with_inconsistent_data_is_rejected(changes):
    job = make_job()
    job.start("a" * 40)
    job.finish({"compliant": False})

    snapshot = replace(JobSnapshot.from_job(job), **changes)

    with pytest.raises(ValueError):
        snapshot.to_job()


def test_snapshot_and_restored_job_do_not_share_mutable_data():
    job = make_job()
    job.start("a" * 40)

    snapshot = JobSnapshot.from_job(job)
    restored = snapshot.to_job()

    snapshot.params["nested"]["value"] = 2
    restored.finish({"compliant": True})

    assert job.params["nested"]["value"] == 1
    assert restored.params["nested"]["value"] == 1
    assert job.state is JobState.RUNNING
    assert snapshot.state is JobState.RUNNING
