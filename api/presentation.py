"""Convert saved application snapshots to public HTTP representations."""

from urllib.parse import quote

from application.contracts import JobView
from core.job import JobState

from .models import JobDone, JobFailed, JobInProgress, JobReference

FAILURE_MESSAGES = {
    "repository_not_found": "Repository was not found or is not public.",
    "github_access_denied": "GitHub access was denied.",
    "github_rate_limited": "GitHub API rate limit exceeded.",
    "github_unavailable": "GitHub API is unavailable.",
    "interrupted": "Job was interrupted by a service restart.",
    "invalid_tool_parameters": "Tool parameters are invalid.",
    "snapshot_incomplete": "Repository snapshot is incomplete.",
    "tool_execution_failed": "Tool execution failed.",
}


def base_fields(job: JobView) -> dict:
    return {
        "id": job.id,
        "status": job.state.value,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def job_reference(job: JobView) -> JobReference:
    return JobReference(**base_fields(job), status_url="/jobs/" + quote(job.id, safe=""))


def job_status(job: JobView) -> JobInProgress | JobDone | JobFailed:
    fields = base_fields(job)
    if job.state in {JobState.CREATED, JobState.RUNNING}:
        return JobInProgress(**fields)
    if job.state is JobState.FAILED:
        if job.error is None:
            raise ValueError("Failed job has no saved failure")
        code = job.error["code"]
        return JobFailed(**fields, failure={"code": code, "message": FAILURE_MESSAGES[code]})
    if job.state is not JobState.DONE or job.report is None:
        raise ValueError("Done job has no saved report")
    saved = job.report
    recommendations = job.recommendations or {"status": "pending"}
    if recommendations.get("status") == "failed":
        recommendations = {
            "status": "failed",
            "error": {
                "code": "recommendation_generation_failed",
                "message": "Recommendations could not be generated.",
            },
        }
    return JobDone(
        **fields,
        report={
            "job_id": job.id,
            "repository_url": saved["repository_url"],
            "profile": saved["profile"],
            "commit_sha": saved["commit_sha"],
            "requirements_met": saved["compliant"],
            "checks": saved["results"],
        },
        recommendations=recommendations,
    )
