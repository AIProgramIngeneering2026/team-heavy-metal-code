"""Recording service fake: persistence and scheduling belong to other p4 blocks."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from application.contracts import CreationResult, JobView
from application.errors import JobNotFoundError
from core.dispatcher import Dispatcher
from core.job import Job, JobState
from core.profiles import register_basic_profile
from core.readme_sections import ReadmeSectionsTool
from core.registry import Registry
from core.required_files import RequiredFilesTool
from core.tool_contract import RepositorySnapshot


@pytest.fixture
def view_factory():
    def make(state=JobState.CREATED, **kwargs):
        values = {
            "id": "job-123", "state": state,
            "created_at": datetime(2026, 11, 23, 9, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 11, 23, 9, 1, tzinfo=timezone.utc),
        }
        values.update(kwargs)
        return JobView(**values)
    return make


class RecordingService:
    def __init__(self, initial_view):
        self.result = CreationResult(initial_view, True)
        self.views = {initial_view.id: initial_view}
        self.create_calls = []
        self.get_calls = []
        self.create_error = None
        self.get_error = None

    def create_job(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.create_error:
            raise self.create_error
        return self.result

    def get_job(self, job_id):
        self.get_calls.append(job_id)
        if self.get_error:
            raise self.get_error
        if job_id not in self.views:
            raise JobNotFoundError(job_id)
        return self.views[job_id]


@pytest.fixture
def service(view_factory):
    return RecordingService(view_factory())


@pytest.fixture
def app(service):
    return create_app(service)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def done_report():
    registry = Registry()
    registry.register(RequiredFilesTool())
    registry.register(ReadmeSectionsTool())
    register_basic_profile(registry)
    snapshot = RepositorySnapshot(
        "https://github.com/example/project", "a" * 40,
        ("README.md", "CONTRIBUTING.md"),
        {"README.md": "# Описание проекта\n## Запуск\n## Тестирование\n"},
    )
    job = Job("check_repository", {"profile": "basic"})
    return Dispatcher(registry).run(job, "basic", snapshot)
