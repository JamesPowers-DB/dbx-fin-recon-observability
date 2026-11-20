"""Pydantic response models. Mirror 1:1 in frontend/src/types.ts."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class MeResponse(BaseModel):
    email: str
    display_name: str
    initials: str


class AppConfigResponse(BaseModel):
    catalog: str
    schema: str
    workspace_url: str
    run_controls_job_id: str
    simulate_job_id: str
    pipeline_id: str


class RunTriggerRequest(BaseModel):
    kind: str                 # run_controls | simulate
    reason: str = ""
    scenario: str = "auto"


class RunTriggerResponse(BaseModel):
    job_id: str
    run_id: int
    run_page_url: str


class RunTask(BaseModel):
    task_key: str
    state: str
    result_state: str | None = None
    start_time: int | None = None
    end_time: int | None = None


class RunStatusResponse(BaseModel):
    run_id: int
    life_cycle_state: str
    result_state: str | None = None
    state_message: str | None = None
    start_time: int | None = None
    end_time: int | None = None
    run_page_url: str
    tasks: list[RunTask]
