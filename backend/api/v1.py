"""`/api/v1beta` routes — state-machine implementation aligned with the VS Code extension contract."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.job_runtime import (
    InvalidJobStateError,
    JobLaunchRequest,
    JobNotFoundError,
    JobReview,
    JobRuntime,
)


router = APIRouter(prefix="/api/v1beta", tags=["api-v1beta"])
_runtime = JobRuntime()


def set_runtime(runtime: JobRuntime) -> None:
    """Test hook for swapping runtime implementation."""
    global _runtime
    _runtime = runtime


class CreateJobRequest(BaseModel):
    goal: str = Field(..., min_length=1)
    coder_count: int = Field(default=2, ge=1, le=32)
    gemini_key: str = ""
    moorcheh_key: str = Field(..., min_length=1)


class ReviewRequest(BaseModel):
    approved: bool
    feedback: str = ""


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentic-army-v1"}


@router.post("/jobs")
async def create_job(payload: CreateJobRequest) -> dict[str, str]:
    launch = JobLaunchRequest(
        goal=payload.goal,
        coder_count=payload.coder_count,
        gemini_key=payload.gemini_key,
        moorcheh_key=payload.moorcheh_key,
    )
    job_id = await _runtime.create_job(launch)
    _runtime.start_pipeline(job_id, launch)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}/plan")
async def get_plan(job_id: str) -> dict:
    try:
        return await _runtime.get_plan_payload(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/plan/review")
async def review_plan(job_id: str, payload: ReviewRequest) -> dict[str, bool]:
    try:
        await _runtime.submit_plan_review(job_id, JobReview(**payload.model_dump()))
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/jobs/{job_id}/status")
async def get_status(job_id: str) -> dict:
    try:
        return await _runtime.get_status_payload(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/result/review")
async def review_result(job_id: str, payload: ReviewRequest) -> dict[str, bool]:
    try:
        await _runtime.submit_result_review(job_id, JobReview(**payload.model_dump()))
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}

