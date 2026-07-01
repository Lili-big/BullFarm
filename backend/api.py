from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from backend.jobs.daily_selection import default_target_date, run_daily_selection_job
from backend.jobs.price_refresh import default_price_date, run_price_refresh_job
from backend.settings import get_settings
from backend.job_store import get_job_run, list_job_runs, upsert_job_run, utc_now


app = FastAPI(title="Stock Selection Local Backend", version="2.0.0")


class DailySelectionRequest(BaseModel):
    run_date: str | None = None
    as_of_date: str | None = None
    dry_run: bool = False


class PriceRefreshRequest(BaseModel):
    as_of_date: str | None = None
    dry_run: bool = False


class RetryJobRequest(BaseModel):
    dry_run: bool | None = None


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
    return {"status": "ok", "service": "stock-selection-local-backend"}


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
            "job_type": "daily_selection",
            "trigger_source": "api",
            "triggered_by": "api",
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
        trigger_source="api",
        triggered_by="api",
        request_payload=payload,
    )
    return {
        "job_id": queued["job_id"],
        "job_type": queued["job_type"],
        "status": "queued",
        "target_date": target_date,
        "dry_run": body.dry_run,
    }


@app.post("/jobs/price-refresh")
def create_price_refresh_job(
    background_tasks: BackgroundTasks,
    request_body: PriceRefreshRequest | None = None,
    _: None = Depends(require_admin_token),
) -> dict[str, Any]:
    body = request_body or PriceRefreshRequest()
    job_id = str(uuid4())
    target_date = body.as_of_date or default_price_date()
    payload = model_payload(body)
    queued = upsert_job_run(
        {
            "job_id": job_id,
            "job_type": "price_refresh",
            "trigger_source": "api",
            "triggered_by": "api",
            "target_date": iso_date(target_date),
            "status": "queued",
            "dry_run": body.dry_run,
            "request_payload": payload,
            "result_payload": {},
            "created_at": utc_now(),
        }
    )
    background_tasks.add_task(
        run_price_refresh_job,
        job_id=job_id,
        as_of_date=body.as_of_date,
        dry_run=body.dry_run,
        trigger_source="api",
        triggered_by="api",
        request_payload=payload,
    )
    return {
        "job_id": queued["job_id"],
        "job_type": queued["job_type"],
        "status": "queued",
        "target_date": target_date,
        "dry_run": body.dry_run,
    }


@app.get("/jobs")
def list_jobs(
    job_type: str | None = None,
    status: str | None = None,
    limit: int = 20,
    _: None = Depends(require_admin_token),
) -> dict[str, Any]:
    return {"jobs": list_job_runs(job_type=job_type, status=status, limit=limit)}


@app.get("/jobs/{job_id}")
def read_job(job_id: str, _: None = Depends(require_admin_token)) -> dict[str, Any]:
    job = get_job_run(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.get("/jobs/{job_id}/logs")
def read_job_logs(job_id: str, _: None = Depends(require_admin_token)) -> dict[str, Any]:
    job = get_job_run(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    result_payload = job.get("result_payload") or {}
    return {
        "job_id": job_id,
        "job_type": job.get("job_type"),
        "status": job.get("status"),
        "error_message": job.get("error_message"),
        "log_excerpt": job.get("log_excerpt"),
        "stdout_tail": result_payload.get("stdout_tail"),
        "stderr_tail": result_payload.get("stderr_tail"),
        "command_results": result_payload.get("command_results"),
    }


@app.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    request_body: RetryJobRequest | None = None,
    _: None = Depends(require_admin_token),
) -> dict[str, Any]:
    original = get_job_run(job_id)
    if not original:
        raise HTTPException(status_code=404, detail="Job not found.")
    job_type = original.get("job_type") or "daily_selection"
    request_payload = dict(original.get("request_payload") or {})
    body = request_body or RetryJobRequest()
    dry_run = original.get("dry_run", False) if body.dry_run is None else body.dry_run
    request_payload["retry_of"] = job_id
    request_payload["dry_run"] = dry_run
    retry_job_id = str(uuid4())
    attempt_no = int(original.get("attempt_no") or 1) + 1
    target_date = original.get("target_date")
    queued = upsert_job_run(
        {
            "job_id": retry_job_id,
            "job_type": job_type,
            "trigger_source": "retry",
            "triggered_by": "api",
            "attempt_no": attempt_no,
            "target_date": target_date,
            "status": "queued",
            "dry_run": dry_run,
            "request_payload": request_payload,
            "result_payload": {},
            "created_at": utc_now(),
        }
    )
    if job_type == "price_refresh":
        background_tasks.add_task(
            run_price_refresh_job,
            job_id=retry_job_id,
            as_of_date=target_date,
            dry_run=dry_run,
            trigger_source="retry",
            triggered_by="api",
            attempt_no=attempt_no,
            request_payload=request_payload,
        )
    else:
        background_tasks.add_task(
            run_daily_selection_job,
            job_id=retry_job_id,
            target_date=target_date,
            as_of_date=target_date,
            dry_run=dry_run,
            trigger_source="retry",
            triggered_by="api",
            attempt_no=attempt_no,
            request_payload=request_payload,
        )
    return {
        "job_id": queued["job_id"],
        "retry_of": job_id,
        "job_type": job_type,
        "attempt_no": attempt_no,
        "status": "queued",
        "dry_run": dry_run,
    }
