"""The composition root can bind its service and await worker shutdown."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


@pytest.mark.parametrize("request_fails", [False, True])
def test_lifespan_binds_service_and_awaits_worker_before_resources_close(service, request_fails):
    events = []
    if request_fails:
        service.get_error = RuntimeError("private resource failure")

    @asynccontextmanager
    async def lifespan(app):
        events.append("resources_open")
        started = asyncio.Event()
        stop = asyncio.Event()

        async def worker():
            events.append("worker_started")
            started.set()
            await stop.wait()
            # Shutdown must await asynchronous cleanup, not just signal stop.
            await asyncio.sleep(0)
            events.append("worker_stopped")

        task = asyncio.create_task(worker())
        try:
            await started.wait()
            app.state.job_service = service
            yield
        finally:
            events.append("shutdown_requested")
            stop.set()
            await task
            app.state.job_service = None
            events.append("resources_closed")

    app = create_app(lifespan=lifespan)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert events == ["resources_open", "worker_started"]
        response = client.get("/jobs/job-123")
        assert response.status_code == (500 if request_fails else 200)
        assert service.get_calls == ["job-123"]
        if request_fails:
            assert response.json()["error"]["code"] == "internal_error"
            assert "private resource failure" not in response.text
        else:
            assert response.json()["id"] == "job-123"
        assert "worker_stopped" not in events

    assert events == [
        "resources_open", "worker_started", "shutdown_requested",
        "worker_stopped", "resources_closed",
    ]
    assert app.state.job_service is None


def test_startup_failure_runs_composition_cleanup_and_does_not_serve_requests(service):
    events = []

    @asynccontextmanager
    async def lifespan(app):
        events.append("resources_open")
        try:
            raise RuntimeError("worker startup failed")
            yield  # pragma: no cover -- makes this a lifespan async generator
        finally:
            events.append("resources_closed")

    app = create_app(service, lifespan=lifespan)
    with pytest.raises(RuntimeError, match="worker startup failed"):
        with TestClient(app):
            pytest.fail("Requests must not be accepted after startup failure")

    assert events == ["resources_open", "resources_closed"]
    assert service.get_calls == []
    assert service.create_calls == []
