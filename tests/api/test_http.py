import asyncio
from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException

from api.app import create_app
from application.contracts import CreationResult
from application.errors import IdempotencyConflictError, InvalidJobParametersError
from core.errors import InvalidStateTransition, OperationNotSupported
from core.job import JobState
from core.registry import UnknownOperationError

PAYLOAD = {"repository_url": "https://github.com/example/project", "profile": "basic"}
HEADERS = {"Idempotency-Key": "request-1"}
SECRET = "Traceback /srv/private/db.sqlite SELECT password FROM secrets token=private-token"


def assert_error(response, status, code, field=None):
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert error["message"]
    assert isinstance(error["details"], list)
    if field:
        assert any(item["field"] == field for item in error["details"])
    assert SECRET not in response.text


def test_new_job_is_accepted_and_passes_only_public_arguments(client, service):
    response = client.post("/jobs", json=PAYLOAD, headers=HEADERS)
    assert response.status_code == 202
    assert response.json() == {
        "id": "job-123", "status": "created", "status_url": "/jobs/job-123",
        "created_at": "2026-11-23T09:00:00Z", "updated_at": "2026-11-23T09:01:00Z",
    }
    assert service.create_calls == [{**PAYLOAD, "idempotency_key": "request-1"}]


@pytest.mark.parametrize("state", list(JobState))
def test_service_replay_flag_returns_200_with_current_state(client, service, view_factory, state):
    service.result = CreationResult(view_factory(state), False)
    response = client.post("/jobs", json=PAYLOAD, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == state.value
    assert response.json()["id"] == "job-123"
    assert len(service.create_calls) == 1


@pytest.mark.parametrize("state", [JobState.CREATED, JobState.RUNNING])
def test_in_progress_response_contains_no_report_or_internal_fields(client, service, view_factory, state):
    service.views["job-123"] = view_factory(state, report={"secret": SECRET}, error={"secret": SECRET})
    response = client.get("/jobs/job-123")
    assert response.status_code == 200
    assert set(response.json()) == {"id", "status", "created_at", "updated_at"}
    assert response.json()["status"] == state.value
    assert SECRET not in response.text
    assert service.create_calls == []


def test_get_done_serializes_a_real_dispatcher_report(client, service, view_factory, done_report):
    service.views["job-123"] = view_factory(JobState.DONE, report=done_report)
    first = client.get("/jobs/job-123")
    second = client.get("/jobs/job-123")
    assert first.status_code == 200
    assert first.json() == second.json()
    report = first.json()["report"]
    assert report["job_id"] == "job-123"
    assert report["commit_sha"] == "a" * 40
    assert report["requirements_met"] is True
    assert len(report["checks"]) == 5
    assert "compliant" not in report and "results" not in report
    assert first.json()["recommendations"] == {"status": "pending"}
    assert service.create_calls == []
    assert service.get_calls == ["job-123", "job-123"]


def test_violations_remain_done_and_are_not_http_errors(client, service, view_factory, done_report):
    done_report["results"][0]["status"] = False
    done_report["compliant"] = False
    service.views["job-123"] = view_factory(JobState.DONE, report=done_report)
    response = client.get("/jobs/job-123")
    assert response.status_code == 200
    assert response.json()["status"] == "done"
    assert response.json()["report"]["requirements_met"] is False


@pytest.mark.parametrize("recommendations", [
    {"status": "pending"}, {"status": "ready", "items": ["Add examples"]},
    {"status": "failed", "error": {"code": SECRET, "message": SECRET}},
])
def test_recommendations_do_not_replace_the_formal_report(client, service, view_factory, done_report, recommendations):
    service.views["job-123"] = view_factory(JobState.DONE, report=done_report, recommendations=recommendations)
    response = client.get("/jobs/job-123")
    assert response.status_code == 200
    assert response.json()["status"] == "done"
    assert len(response.json()["report"]["checks"]) == 5
    assert response.json()["recommendations"]["status"] == recommendations["status"]
    assert SECRET not in response.text


@pytest.mark.parametrize("code", [
    "repository_not_found", "github_access_denied", "github_rate_limited", "github_unavailable",
    "interrupted", "invalid_tool_parameters", "snapshot_incomplete", "tool_execution_failed",
])
def test_saved_failure_is_a_200_state_response_with_safe_message(client, service, view_factory, code):
    service.views["job-123"] = view_factory(JobState.FAILED, error={"code": code, "message": SECRET, "details": SECRET})
    response = client.get("/jobs/job-123")
    assert response.status_code == 200
    assert response.json()["failure"]["code"] == code
    assert "report" not in response.json()
    assert SECRET not in response.text


def test_unknown_or_malformed_id_returns_404_without_creating_job(client, service):
    assert_error(client.get("/jobs/not-a-uuid"), 404, "job_not_found", "job_id")
    assert service.create_calls == []


@pytest.mark.parametrize("payload,code,field", [
    ({}, "validation_error", "repository_url"),
    ({"repository_url": PAYLOAD["repository_url"]}, "validation_error", "profile"),
    ({**PAYLOAD, "repository_url": 123}, "validation_error", "repository_url"),
    ({**PAYLOAD, "repository_url": None}, "validation_error", "repository_url"),
    ({**PAYLOAD, "repository_url": "https://example.com/a/b"}, "validation_error", "repository_url"),
    ({**PAYLOAD, "repository_url": "https://github.com/a/b?token=x"}, "validation_error", "repository_url"),
    ({**PAYLOAD, "repository_url": "https://github.com@evil.example/a/b"}, "validation_error", "repository_url"),
    ({**PAYLOAD, "repository_url": "https://github.com/a/b/tree/main"}, "validation_error", "repository_url"),
    ({**PAYLOAD, "repository_url": "https://github.com/a/.."}, "validation_error", "repository_url"),
    ({**PAYLOAD, "repository_url": "x" * 2049}, "field_too_long", "repository_url"),
    ({**PAYLOAD, "profile": "other"}, "validation_error", "profile"),
    ({**PAYLOAD, "profile": "x" * 65}, "field_too_long", "profile"),
    ({**PAYLOAD, "status": "done"}, "validation_error", "status"),
    ({**PAYLOAD, "report": {"requirements_met": True}}, "validation_error", "report"),
    ({**PAYLOAD, "id": "chosen-id"}, "validation_error", "id"),
    ([], "validation_error", "request_body"),
    (123, "validation_error", "request_body"),
    (None, "validation_error", "request_body"),
])
def test_invalid_request_never_calls_the_service(client, service, payload, code, field):
    # content= keeps JSON null distinct from an absent body in httpx.
    response = client.post("/jobs", content=json.dumps(payload), headers={**HEADERS, "Content-Type": "application/json"})
    assert_error(response, 422, code, field)
    assert service.create_calls == []


@pytest.mark.parametrize("key,code", [(None, "validation_error"), ("", "validation_error"), ("   ", "validation_error"), ("x" * 129, "field_too_long")])
def test_invalid_idempotency_header_does_not_call_service(client, service, key, code):
    headers = {} if key is None else {"Idempotency-Key": key}
    assert_error(client.post("/jobs", json=PAYLOAD, headers=headers), 422, code, "Idempotency-Key")
    assert service.create_calls == []


@pytest.mark.parametrize("body", [b"{", b"", b"\xff", b'{"profile": NaN}', b'{"profile": Infinity}', b"[" * 2000])
def test_invalid_json_is_400_without_parser_details(client, service, body):
    response = client.post("/jobs", content=body, headers={**HEADERS, "Content-Type": "application/json"})
    assert_error(response, 400, "invalid_json")
    assert service.create_calls == []


@pytest.mark.parametrize("media_type", [None, "text/plain", "application/x-www-form-urlencoded"])
def test_unsupported_content_type_is_415(client, service, media_type):
    headers = dict(HEADERS)
    if media_type:
        headers["Content-Type"] = media_type
    response = client.post("/jobs", content=json.dumps(PAYLOAD), headers=headers)
    assert_error(response, 415, "unsupported_media_type", "Content-Type")
    assert service.create_calls == []


def test_json_content_type_parameters_are_supported(client):
    response = client.post("/jobs", content=json.dumps(PAYLOAD), headers={**HEADERS, "Content-Type": "Application/JSON; charset=utf-8"})
    assert response.status_code == 202


def test_actual_body_size_limit_including_boundary_and_false_content_length(client, service):
    raw = json.dumps(PAYLOAD).encode()
    boundary = raw + b" " * (65536 - len(raw))
    assert client.post("/jobs", content=boundary, headers={**HEADERS, "Content-Type": "application/json"}).status_code == 202
    service.create_calls.clear()
    response = client.post("/jobs", content=boundary + b" ", headers={**HEADERS, "Content-Type": "application/json", "Content-Length": "1"})
    assert_error(response, 413, "payload_too_large", "request_body")
    assert service.create_calls == []


def test_streamed_body_without_content_length_cannot_bypass_limit(app, service):
    async def run():
        async def content():
            for _ in range(5):
                yield b" " * 16384
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/jobs", content=content(), headers={**HEADERS, "Content-Type": "application/json"})
    response = asyncio.run(run())
    assert_error(response, 413, "payload_too_large")
    assert service.create_calls == []


@pytest.mark.parametrize("error,status,code,field", [
    (IdempotencyConflictError(("repository_url",)), 409, "idempotency_key_conflict", "repository_url"),
    (UnknownOperationError("missing"), 422, "unknown_operation", "profile"),
    (InvalidJobParametersError(("params.required_paths",)), 422, "invalid_tool_parameters", "params.required_paths"),
    (InvalidStateTransition(SECRET), 409, "invalid_state_transition", None),
    (OperationNotSupported(SECRET), 409, "operation_not_supported", None),
    (RuntimeError(SECRET), 500, "internal_error", None),
    (HTTPException(500, detail=SECRET), 500, "internal_error", None),
])
def test_service_errors_have_distinct_safe_http_responses(client, service, error, status, code, field):
    service.create_error = error
    assert_error(client.post("/jobs", json=PAYLOAD, headers=HEADERS), status, code, field)


def test_unexpected_read_failure_is_sanitized(client, service):
    service.get_error = RuntimeError(SECRET)
    assert_error(client.get("/jobs/job-123"), 500, "internal_error")


@pytest.mark.parametrize("corruption", ["missing_report", "duplicate_checks", "wrong_summary", "unknown_failure"])
def test_invalid_saved_representation_is_not_published(client, service, view_factory, done_report, corruption):
    view = view_factory(JobState.DONE, report=done_report)
    if corruption == "missing_report":
        view = replace(view, report=None)
    elif corruption == "duplicate_checks":
        done_report["results"][1] = dict(done_report["results"][0])
    elif corruption == "wrong_summary":
        done_report["compliant"] = False
    else:
        view = view_factory(JobState.FAILED, error={"code": SECRET, "message": SECRET})
    service.views["job-123"] = view
    assert_error(client.get("/jobs/job-123"), 500, "internal_error")


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_state_mutation_routes_are_not_exposed(client, service, method):
    response = client.request(method, "/jobs/job-123", json={"status": "done"})
    assert_error(response, 405, "method_not_allowed")
    assert service.create_calls == service.get_calls == []


def test_unconfigured_app_exposes_docs_and_validates_before_reporting_configuration_error():
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        assert client.get("/docs").status_code == 200
        assert_error(client.post("/jobs", json={}, headers=HEADERS), 422, "validation_error")
        response = client.post("/jobs", json=PAYLOAD, headers=HEADERS)
        assert_error(response, 500, "internal_error")
        assert "configured" not in response.text
