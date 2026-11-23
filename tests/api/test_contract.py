"""Check actual HTTP responses against the checked-in p2/p4 OpenAPI contract."""

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft4Validator, FormatChecker

from application.contracts import CreationResult
from application.errors import IdempotencyConflictError
from core.job import JobState

PAYLOAD = {"repository_url": "https://github.com/example/project", "profile": "basic"}
HEADERS = {"Idempotency-Key": "contract-test"}


@pytest.fixture(scope="module")
def contract():
    path = Path(__file__).resolve().parents[2] / "docs/api/openapi.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def resolve(contract, value):
    while "$ref" in value:
        pointer = value["$ref"]
        assert pointer.startswith("#/")
        value = contract
        for part in pointer[2:].split("/"):
            value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def validate(contract, schema, value):
    # OpenAPI 3.0 schemas use the Draft 4 keywords relevant to this contract.
    # Keep components at the document root so its local $refs resolve normally.
    root = {**schema, "components": contract["components"]}
    Draft4Validator(root, format_checker=FormatChecker()).validate(value)


def validate_response(contract, method, path, response, status):
    assert response.status_code == status, response.text
    declared = contract["paths"][path][method]["responses"][str(status)]
    media = resolve(contract, declared)["content"]["application/json"]
    validate(contract, media["schema"], response.json())


def test_generated_operations_and_input_constraints_match_file(client, contract):
    generated = client.get("/openapi.json").json()
    assert set(generated["paths"]) == set(contract["paths"])
    for path, methods in contract["paths"].items():
        for method, declared in methods.items():
            actual = generated["paths"][path][method]
            assert actual["operationId"] == declared["operationId"]
            assert set(actual["responses"]) == set(declared["responses"])

    declared = contract["paths"]["/jobs"]["post"]
    actual = generated["paths"]["/jobs"]["post"]
    header = actual["parameters"][0]
    assert (header["in"], header["name"], header["required"]) == ("header", "Idempotency-Key", True)
    for keyword in ("type", "minLength", "maxLength", "pattern"):
        assert header["schema"][keyword] == declared["parameters"][0]["schema"][keyword]
    assert actual["requestBody"]["required"] is True

    source = contract["components"]["schemas"]
    models = generated["components"]["schemas"]
    request = models["CreateJobRequest"]
    assert set(request["required"]) == set(source["CreateJobRequest"]["required"])
    assert request["additionalProperties"] is False
    for keyword in ("type", "minLength", "maxLength", "pattern"):
        assert request["properties"]["repository_url"][keyword] == source["CreateJobRequest"]["properties"]["repository_url"][keyword]
    assert request["properties"]["profile"]["const"] == source["CreateJobRequest"]["properties"]["profile"]["enum"][0]
    assert request["properties"]["profile"]["maxLength"] == 64
    assert models["JobFailure"]["properties"]["code"]["enum"] == source["JobFailureCode"]["enum"]
    assert models["CheckResult"]["properties"]["check_name"]["enum"] == source["CheckResult"]["properties"]["check_name"]["enum"]


@pytest.mark.parametrize("status", [200, 202, 400, 409, 413, 415, 422, 500])
def test_every_create_status_matches_the_file(client, service, contract, status):
    if status == 200:
        service.result = CreationResult(service.result.job, False)
    if status == 409:
        service.create_error = IdempotencyConflictError()
    if status == 500:
        service.create_error = RuntimeError("private database error")
    arguments = {"json": PAYLOAD, "headers": HEADERS}
    if status in {400, 413, 415}:
        body = {400: "{", 413: " " * 65537, 415: "{}"}[status]
        arguments = {"content": body, "headers": {**HEADERS, "Content-Type": "text/plain" if status == 415 else "application/json"}}
    if status == 422:
        arguments["json"] = {}
    response = client.post("/jobs", **arguments)
    validate_response(contract, "post", "/jobs", response, status)


@pytest.mark.parametrize("state", list(JobState))
def test_each_saved_state_matches_the_file(client, service, view_factory, done_report, contract, state):
    service.views["job-123"] = view_factory(
        state, report=done_report if state is JobState.DONE else None,
        error={"code": "github_unavailable"} if state is JobState.FAILED else None,
    )
    validate_response(contract, "get", "/jobs/{job_id}", client.get("/jobs/job-123"), 200)


@pytest.mark.parametrize("status", [404, 500])
def test_read_errors_match_the_file(client, service, contract, status):
    if status == 500:
        service.get_error = RuntimeError("private database error")
    validate_response(contract, "get", "/jobs/{job_id}", client.get("/jobs/missing"), status)


def test_documented_examples_are_valid(contract):
    for methods in contract["paths"].values():
        for operation in methods.values():
            bodies = list(operation["responses"].values())
            if "requestBody" in operation:
                bodies.append(operation["requestBody"])
            for body in bodies:
                for media in resolve(contract, body).get("content", {}).values():
                    if "example" in media:
                        validate(contract, media["schema"], media["example"])
                    for example in media.get("examples", {}).values():
                        validate(contract, media["schema"], example["value"])
