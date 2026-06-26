from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .settings import get_settings


JOB_TABLE = "stock_selection_job_runs"
LOCAL_JOB_STORE: dict[str, dict[str, Any]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_supabase_client() -> Any | None:
    settings = get_settings()
    if not settings.has_supabase_credentials:
        return None
    try:
        from supabase import create_client
    except ImportError:
        return None

    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def clean_job_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(record)
    cleaned.setdefault("request_payload", {})
    cleaned.setdefault("result_payload", {})
    cleaned["updated_at"] = utc_now()
    return {key: value for key, value in cleaned.items() if value is not None}


def upsert_job_run(record: dict[str, Any]) -> dict[str, Any]:
    payload = clean_job_record(record)
    client = get_supabase_client()
    if client is None:
        existing = LOCAL_JOB_STORE.get(str(payload["job_id"]), {})
        existing.update(payload)
        LOCAL_JOB_STORE[str(payload["job_id"])] = existing
        return deepcopy(existing)

    response = client.table(JOB_TABLE).upsert(payload, on_conflict="job_id").execute()
    if getattr(response, "data", None):
        return response.data[0]
    return payload


def get_job_run(job_id: str) -> dict[str, Any] | None:
    client = get_supabase_client()
    if client is None:
        job = LOCAL_JOB_STORE.get(job_id)
        return deepcopy(job) if job else None

    response = client.table(JOB_TABLE).select("*").eq("job_id", job_id).limit(1).execute()
    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None
