from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import get_settings


SCHEMA_VERSION = 1
LOCAL_JOB_STORE: dict[str, dict[str, Any]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_path() -> Path:
    return get_settings().job_store_path


def _read_payload(path: Path | None = None) -> dict[str, Any]:
    path = path or store_path()
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "jobs": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {"schema_version": SCHEMA_VERSION, "jobs": []}
    if isinstance(payload, list):
        return {"schema_version": SCHEMA_VERSION, "jobs": payload}
    if not isinstance(payload, dict):
        return {"schema_version": SCHEMA_VERSION, "jobs": []}
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        payload["jobs"] = []
    payload.setdefault("schema_version", SCHEMA_VERSION)
    return payload


def _write_payload(payload: dict[str, Any], path: Path | None = None) -> None:
    path = path or store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = utc_now()
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _load_jobs(path: Path | None = None) -> dict[str, dict[str, Any]]:
    payload = _read_payload(path)
    jobs: dict[str, dict[str, Any]] = {}
    for row in payload.get("jobs", []):
        if isinstance(row, dict) and row.get("job_id"):
            jobs[str(row["job_id"])] = row
    return jobs


def _persist_jobs(jobs: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    rows = sorted(
        jobs.values(),
        key=lambda job: str(job.get("created_at") or job.get("started_at") or job.get("updated_at") or ""),
        reverse=True,
    )
    _write_payload({"jobs": rows}, path)


def clean_job_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(record)
    cleaned.setdefault("job_type", "daily_selection")
    cleaned.setdefault("attempt_no", 1)
    cleaned.setdefault("pipeline_version", "local_v1")
    cleaned.setdefault("request_payload", {})
    cleaned.setdefault("result_payload", {})
    cleaned.setdefault("created_at", cleaned.get("started_at") or utc_now())
    cleaned["updated_at"] = utc_now()
    return {key: value for key, value in cleaned.items() if value is not None}


def upsert_job_run(record: dict[str, Any]) -> dict[str, Any]:
    payload = clean_job_record(record)
    jobs = _load_jobs()
    existing = jobs.get(str(payload["job_id"]), {})
    existing.update(payload)
    jobs[str(payload["job_id"])] = existing
    LOCAL_JOB_STORE.clear()
    LOCAL_JOB_STORE.update(deepcopy(jobs))
    _persist_jobs(jobs)
    return deepcopy(existing)


def get_job_run(job_id: str) -> dict[str, Any] | None:
    jobs = _load_jobs()
    LOCAL_JOB_STORE.clear()
    LOCAL_JOB_STORE.update(deepcopy(jobs))
    job = jobs.get(job_id)
    return deepcopy(job) if job else None


def list_job_runs(
    *,
    job_type: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    jobs = list(_load_jobs().values())
    if job_type:
        jobs = [job for job in jobs if job.get("job_type") == job_type]
    if status:
        jobs = [job for job in jobs if job.get("status") == status]
    jobs.sort(
        key=lambda job: str(job.get("created_at") or job.get("started_at") or job.get("updated_at") or ""),
        reverse=True,
    )
    return deepcopy(jobs[: max(1, min(limit, 100))])


def clear_job_runs(path: Path | None = None) -> None:
    LOCAL_JOB_STORE.clear()
    _write_payload({"jobs": []}, path)
