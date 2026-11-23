"""Safe, uniform errors at the HTTP boundary."""

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from application.errors import IdempotencyConflictError, InvalidJobParametersError, JobNotFoundError
from core.errors import InvalidStateTransition, OperationNotSupported
from core.registry import UnknownOperationError

logger = logging.getLogger(__name__)
FIELD_LIMITS = {"repository_url": 2048, "profile": 64, "Idempotency-Key": 128}
PUBLIC_FIELDS = {*FIELD_LIMITS, "job_id", "params.required_paths", "params.readme_path", "params.required_sections"}


def error_response(status: int, code: str, message: str, details=(), headers=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": list(details)}},
        headers=headers,
    )


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Request failed", exc_info=exc)
    return error_response(500, "internal_error", "Internal server error.")


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    if any(error["type"] == "json_invalid" for error in errors):
        return error_response(400, "invalid_json", "Request body is not valid JSON.")
    details = []
    too_long = False
    for error in errors:
        location = error["loc"]
        field = ".".join(str(part) for part in location[1:]) or "request_body"
        value = error.get("input")
        limit = FIELD_LIMITS.get(field)
        if limit is not None and isinstance(value, str) and len(value) > limit:
            too_long = True
            issue = f"Must not exceed {limit} characters."
        else:
            issue = {
                "missing": "Field is required.",
                "string_type": "Must be a string.",
                "string_too_short": "Must not be empty.",
                "string_pattern_mismatch": "Must not be blank.",
                "literal_error": "Only the basic profile is supported.",
                "extra_forbidden": "Field is not allowed.",
                "model_attributes_type": "Must be a JSON object.",
                "value_error": "Must be a public GitHub repository URL.",
            }.get(error["type"], "Invalid value.")
            if field == "repository_url" and error["type"] == "string_pattern_mismatch":
                issue = "Must be a public GitHub repository URL."
        details.append({"field": field, "issue": issue})
    return error_response(
        422, "field_too_long" if too_long else "validation_error",
        "Request validation failed.", details,
    )


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code >= 500:
        return await unexpected_error(request, exc)
    code, message = {
        404: ("route_not_found", "Route was not found."),
        405: ("method_not_allowed", "Method is not allowed."),
    }.get(exc.status_code, ("http_error", "Request could not be processed."))
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def service_error(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, JobNotFoundError) and request.method == "GET":
        return error_response(404, "job_not_found", "Job was not found.", [
            {"field": "job_id", "issue": "No job exists with this ID."}
        ])
    if request.method != "POST":
        return await unexpected_error(request, exc)
    if isinstance(exc, IdempotencyConflictError):
        details = [
            {"field": field if field in PUBLIC_FIELDS else "request_body", "issue": "Value differs from the request previously used with this key."}
            for field in exc.fields
        ]
        return error_response(409, "idempotency_key_conflict", "Idempotency-Key was already used with different parameters.", details)
    if isinstance(exc, UnknownOperationError):
        return error_response(422, "unknown_operation", "Operation is not supported.", [
            {"field": "profile", "issue": "No such operation is registered."}
        ])
    if isinstance(exc, InvalidJobParametersError):
        return error_response(422, "invalid_tool_parameters", "Job parameters are invalid.", [
            {"field": field if field in PUBLIC_FIELDS else "request_body", "issue": "Invalid value."}
            for field in exc.fields
        ])
    if isinstance(exc, InvalidStateTransition):
        return error_response(409, "invalid_state_transition", "Job state transition is not allowed.")
    if isinstance(exc, OperationNotSupported):
        return error_response(409, "operation_not_supported", "Operation is not supported.")
    return await unexpected_error(request, exc)
