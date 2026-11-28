from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from threading import Barrier

import pytest

from core.job import Job, JobState
from core.repository import RepositoryConflictError
from service.memory_repository import InMemoryJobRepository


def make_job(key="key-1", job_id=None, profile="basic"):
    return Job("check_repository", {"profile": profile}, key, job_id)


def test_create_get_and_save():
    repo = InMemoryJobRepository()
    assert repo.get("missing") is None
    result = repo.create_if_absent(make_job())
    assert result.created
    record = result.record
    assert record.created_at.tzinfo is timezone.utc
    job = record.job
    job.start("a" * 40)
    assert repo.get(job.id).job.state is JobState.CREATED
    running = repo.save(job, expected_state=JobState.CREATED)
    job.finish({"compliant": False})
    done = repo.save(job, expected_state=JobState.RUNNING)
    stored = repo.get(job.id)
    assert stored.job.report == {"compliant": False}
    assert stored.job.state is JobState.DONE
    assert stored.history_timestamps == done.history_timestamps
    assert len(stored.history_timestamps) == len(job.history) == 3
    assert stored.created_at == record.created_at
    assert record.created_at <= running.updated_at <= done.updated_at
    assert repo.list_by_state(JobState.RUNNING) == []
    assert [r.job.id for r in repo.list_by_state(JobState.DONE)] == [job.id]


def test_duplicate_key_preserves_original_parameters():
    repo = InMemoryJobRepository()
    first = repo.create_if_absent(make_job())
    repeat = repo.create_if_absent(make_job(profile="other"))
    assert not repeat.created
    assert repeat.record.job.id == first.record.job.id
    assert repeat.record.job.params == {"profile": "basic"}
    assert len(repo.list_by_state(JobState.CREATED)) == 1


def test_concurrent_creation_has_single_winner():
    repo = InMemoryJobRepository()
    barrier = Barrier(8)

    def create(_):
        job = make_job()
        barrier.wait(timeout=5)
        return repo.create_if_absent(job)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, range(8)))
    assert sum(result.created for result in results) == 1
    assert len({result.record.job.id for result in results}) == 1
    assert len(repo.list_by_state(JobState.CREATED)) == 1


def test_stale_save_does_not_overwrite_newer_state():
    repo = InMemoryJobRepository()
    job_id = repo.create_if_absent(make_job()).record.job.id
    first = repo.get(job_id).job
    stale = repo.get(job_id).job
    first.start("a" * 40)
    stale.fail({"code": "technical_error"})
    repo.save(first, expected_state=JobState.CREATED)
    with pytest.raises(RepositoryConflictError):
        repo.save(stale, expected_state=JobState.CREATED)
    assert repo.get(job_id).job.commit_sha == "a" * 40
    assert repo.get(job_id).job.state is JobState.RUNNING


def test_save_rejects_skipped_transition_and_rewritten_parameters():
    repo = InMemoryJobRepository()
    job = repo.create_if_absent(make_job()).record.job
    job.start("a" * 40)
    job.finish({"compliant": True})
    with pytest.raises(RepositoryConflictError):
        repo.save(job, expected_state=JobState.CREATED)
    changed = make_job(job_id=job.id, profile="other")
    changed.start("a" * 40)
    with pytest.raises(RepositoryConflictError):
        repo.save(changed, expected_state=JobState.CREATED)
    assert repo.get(job.id).job.state is JobState.CREATED


def test_missing_and_duplicate_id_and_no_key():
    repo = InMemoryJobRepository()
    a = make_job(key=None)
    b = make_job(key=None)
    assert repo.create_if_absent(a).created
    assert repo.create_if_absent(b).created
    with pytest.raises(RepositoryConflictError):
        repo.create_if_absent(make_job(key=None, job_id=a.id))
    missing = make_job()
    missing.start("a" * 40)
    with pytest.raises(KeyError):
        repo.save(missing, expected_state=JobState.CREATED)


def test_recovery_transition_is_persisted():
    repo = InMemoryJobRepository()
    job = repo.create_if_absent(make_job()).record.job
    job.start("a" * 40)
    repo.save(job, expected_state=JobState.CREATED)
    recovered = repo.get(job.id).job
    recovered.recover_after_restart()
    repo.save(recovered, expected_state=JobState.RUNNING)
    assert repo.get(job.id).job.error["code"] == "interrupted"


def test_concurrent_transition_has_single_winner():
    repo = InMemoryJobRepository()
    job_id = repo.create_if_absent(make_job()).record.job.id
    barrier = Barrier(2)

    def start(sha):
        job = repo.get(job_id).job
        job.start(sha)
        barrier.wait(timeout=5)
        try:
            repo.save(job, expected_state=JobState.CREATED)
        except RepositoryConflictError:
            return None
        return sha

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, ["a" * 40, "b" * 40]))
    winners = [sha for sha in results if sha is not None]
    assert len(winners) == 1
    stored = repo.get(job_id)
    assert stored.job.commit_sha == winners[0]
    assert len(stored.job.history) == len(stored.history_timestamps) == 2


def test_running_sha_and_terminal_result_cannot_be_rewritten():
    repo = InMemoryJobRepository()
    job = repo.create_if_absent(make_job()).record.job
    job.start("a" * 40)
    repo.save(job, expected_state=JobState.CREATED)
    replacement = make_job(job_id=job.id)
    replacement.start("b" * 40)
    replacement.finish({"compliant": True})
    with pytest.raises(RepositoryConflictError):
        repo.save(replacement, expected_state=JobState.RUNNING)
    job.finish({"compliant": False})
    repo.save(job, expected_state=JobState.RUNNING)
    with pytest.raises(RepositoryConflictError):
        repo.save(job, expected_state=JobState.DONE)
    stored = repo.get(job.id)
    assert stored.job.commit_sha == "a" * 40
    assert stored.job.report == {"compliant": False}


def test_get_returns_independent_job_and_non_created_insert_rejected():
    repo = InMemoryJobRepository()
    job = make_job()
    job.start("a" * 40)
    with pytest.raises(ValueError):
        repo.create_if_absent(job)
    assert repo.get(job.id) is None
    created = repo.create_if_absent(make_job()).record.job
    read = repo.get(created.id).job
    read.operation = "different"
    read.idempotency_key = "changed"
    assert repo.get(created.id).job.operation == "check_repository"
    assert repo.get(created.id).job.idempotency_key == "key-1"
