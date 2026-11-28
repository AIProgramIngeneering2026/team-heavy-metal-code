"""FastAPI factory; production persistence/execution are injected by composition."""

from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import Lifespan

from application.contracts import JobService
from application.errors import IdempotencyConflictError, InvalidJobParametersError, JobNotFoundError
from core.errors import InvalidStateTransition, OperationNotSupported
from core.registry import UnknownOperationError

from .errors import http_error, service_error, unexpected_error, validation_error
from .middleware import RequestBodyMiddleware
from .models import CreateJobRequest, ErrorResponse, JobReference, JobStatusResponse
from .presentation import job_reference, job_status


def get_job_service(request: Request) -> JobService | None:
    return request.app.state.job_service


Service = Annotated[JobService | None, Depends(get_job_service)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"\S")]


def create_app(
    service: JobService | None = None, *, lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    """Build HTTP routes; the composition lifespan owns workers and resources."""
    app = FastAPI(
        title="Учебный сервис проверки репозиториев", version="1.0.0",
        redirect_slashes=False, debug=False, lifespan=lifespan,
    )
    app.state.job_service = service
    app.add_middleware(RequestBodyMiddleware)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(Exception, unexpected_error)
    for error_type in (
        IdempotencyConflictError, InvalidJobParametersError, JobNotFoundError,
        InvalidStateTransition, OperationNotSupported, UnknownOperationError,
    ):
        app.add_exception_handler(error_type, service_error)

    @app.post(
        "/jobs", status_code=202, response_model=JobReference, operation_id="createJob",
        responses={200: {"model": JobReference}, **{
            code: {"model": ErrorResponse} for code in (400, 409, 413, 415, 422, 500)
        }},
    )
    def create_job(payload: CreateJobRequest, idempotency_key: IdempotencyKey, service: Service):
        if service is None:
            raise RuntimeError("Job service has not been configured")
        result = service.create_job(
            repository_url=payload.repository_url,
            profile=payload.profile,
            idempotency_key=idempotency_key,
        )
        reference = job_reference(result.job)
        return JSONResponse(status_code=202 if result.created else 200, content=reference.model_dump(mode="json"))

    @app.get(
        "/jobs/{job_id}", response_model=JobStatusResponse, operation_id="getJob",
        responses={code: {"model": ErrorResponse} for code in (404, 500)},
    )
    def get_job(job_id: str, service: Service):
        if service is None:
            raise RuntimeError("Job service has not been configured")
        return job_status(service.get_job(job_id))

    generated_openapi = app.openapi

    def openapi():
        schema = generated_openapi()
        # A string path parameter cannot produce the default framework 422.
        schema["paths"]["/jobs/{job_id}"]["get"]["responses"].pop("422", None)
        return schema

    app.openapi = openapi
    return app


app = create_app()
