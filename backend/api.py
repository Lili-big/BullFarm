from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from backend.jobs.daily_selection import default_target_date, run_daily_selection_job
from backend.settings import get_settings
from backend.supabase_jobs import get_job_run, upsert_job_run, utc_now


app = FastAPI(title="Stock Selection Backend", version="1.0.0")


class DailySelectionRequest(BaseModel):
    run_date: str | None = None
    as_of_date: str | None = None
    dry_run: bool = False


def model_payload(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def iso_date(value: str) -> str:
    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def extract_bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def require_admin_token(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> None:
    expected = get_settings().admin_trigger_token
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_TRIGGER_TOKEN is not configured.")
    supplied = x_admin_token or extract_bearer_token(request)
    if supplied != expected:
        raise HTTPException(status_code=401, detail="Invalid admin token.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "stock-selection-backend"}


@app.post("/jobs/daily-selection")
def create_daily_selection_job(
    background_tasks: BackgroundTasks,
    request_body: DailySelectionRequest | None = None,
    _: None = Depends(require_admin_token),
) -> dict[str, Any]:
    body = request_body or DailySelectionRequest()
    job_id = str(uuid4())
    target_date = body.run_date or default_target_date()
    payload = model_payload(body)
    queued = upsert_job_run(
        {
            "job_id": job_id,
            "trigger_source": "manual",
            "target_date": iso_date(target_date),
            "status": "queued",
            "dry_run": body.dry_run,
            "request_payload": payload,
            "result_payload": {},
            "created_at": utc_now(),
        }
    )
    background_tasks.add_task(
        run_daily_selection_job,
        job_id=job_id,
        target_date=body.run_date,
        as_of_date=body.as_of_date,
        dry_run=body.dry_run,
        trigger_source="manual",
        request_payload=payload,
    )
    return {
        "job_id": queued["job_id"],
        "status": "queued",
        "target_date": target_date,
        "dry_run": body.dry_run,
    }


@app.get("/jobs/{job_id}")
def read_job(job_id: str, _: None = Depends(require_admin_token)) -> dict[str, Any]:
    job = get_job_run(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job
