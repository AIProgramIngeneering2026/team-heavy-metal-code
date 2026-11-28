"""Wire representations of the OpenAPI contract; domain rules stay in core."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

REPOSITORY_URL_PATTERN = (
    r"^https://github\.com/[A-Za-z0-9][A-Za-z0-9-]*/"
    r"[A-Za-z0-9_.-]*[A-Za-z0-9_-][A-Za-z0-9_.-]*/?$"
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateJobRequest(ApiModel):
    repository_url: str = Field(
        min_length=1, max_length=2048, pattern=REPOSITORY_URL_PATTERN,
        json_schema_extra={"format": "uri"},
    )
    profile: Literal["basic"] = Field(json_schema_extra={"maxLength": 64})


class ErrorDetail(ApiModel):
    field: str
    issue: str


class ErrorBody(ApiModel):
    code: str
    message: str
    details: list[ErrorDetail]


class ErrorResponse(ApiModel):
    error: ErrorBody


class JobBase(ApiModel):
    id: str = Field(min_length=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class JobReference(JobBase):
    status: Literal["created", "running", "done", "failed"]
    status_url: str


class JobInProgress(JobBase):
    status: Literal["created", "running"]


CheckName = Literal[
    "file:README.md", "file:CONTRIBUTING.md",
    "section:README.md:Описание проекта", "section:README.md:Запуск",
    "section:README.md:Тестирование",
]


class CheckResult(ApiModel):
    check_name: CheckName
    status: bool
    details: str = Field(min_length=1)


class FormalReport(ApiModel):
    job_id: str
    repository_url: str = Field(pattern=REPOSITORY_URL_PATTERN, json_schema_extra={"format": "uri"})
    profile: Literal["basic"]
    commit_sha: str = Field(min_length=1)
    requirements_met: bool
    checks: list[CheckResult] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def consistent_checks(self):
        if len({check.check_name for check in self.checks}) != 5:
            raise ValueError("Check names must be unique")
        if self.requirements_met != all(check.status for check in self.checks):
            raise ValueError("Report summary contradicts its checks")
        return self


class RecommendationsPending(ApiModel):
    status: Literal["pending"]


class RecommendationsReady(ApiModel):
    status: Literal["ready"]
    items: list[Annotated[str, Field(min_length=1)]]


class RecommendationError(ApiModel):
    code: str
    message: str = Field(min_length=1)


class RecommendationsFailed(ApiModel):
    status: Literal["failed"]
    error: RecommendationError


Recommendations = Annotated[
    RecommendationsPending | RecommendationsReady | RecommendationsFailed,
    Field(discriminator="status"),
]


class JobDone(JobBase):
    status: Literal["done"]
    report: FormalReport
    recommendations: Recommendations


FailureCode = Literal[
    "repository_not_found", "github_access_denied", "github_rate_limited",
    "github_unavailable", "interrupted", "invalid_tool_parameters",
    "snapshot_incomplete", "tool_execution_failed",
]


class JobFailure(ApiModel):
    code: FailureCode
    message: str = Field(min_length=1)


class JobFailed(JobBase):
    status: Literal["failed"]
    failure: JobFailure


JobStatusResponse = Annotated[JobInProgress | JobDone | JobFailed, Field(discriminator="status")]
