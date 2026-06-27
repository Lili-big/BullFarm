from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import requests

from .settings import get_settings


JOB_TABLE = "stock_selection_job_runs"
LOCAL_JOB_STORE: dict[str, dict[str, Any]] = {}


class RestResult:
    def __init__(self, data: Any) -> None:
        self.data = data


class RestOperation:
    def __init__(self, callback) -> None:
        self.callback = callback

    def execute(self) -> RestResult:
        return self.callback()


class RestSelect:
    def __init__(self, client: "RestSupabaseClient", table_name: str, columns: str) -> None:
        self.client = client
        self.table_name = table_name
        self.params: dict[str, str] = {"select": columns}

    def eq(self, column: str, value: Any) -> "RestSelect":
        self.params[column] = f"eq.{value}"
        return self

    def order(self, column: str, desc: bool = False) -> "RestSelect":
        self.params["order"] = f"{column}.{'desc' if desc else 'asc'}"
        return self

    def limit(self, value: int) -> "RestSelect":
        self.params["limit"] = str(value)
        return self

    def execute(self) -> RestResult:
        response = requests.get(
            self.client.table_url(self.table_name),
            headers=self.client.headers(),
            params=self.params,
            timeout=60,
        )
        response.raise_for_status()
        return RestResult(response.json())


class RestTable:
    def __init__(self, client: "RestSupabaseClient", table_name: str) -> None:
        self.client = client
        self.table_name = table_name

    def select(self, columns: str) -> RestSelect:
        return RestSelect(self.client, self.table_name, columns)

    def upsert(self, rows: Any, on_conflict: str | None = None) -> RestOperation:
        def run() -> RestResult:
            params = {"on_conflict": on_conflict} if on_conflict else None
            response = requests.post(
                self.client.table_url(self.table_name),
                headers={
                    **self.client.headers(),
                    "Prefer": "resolution=merge-duplicates,return=representation",
                },
                params=params,
                json=rows,
                timeout=120,
            )
            response.raise_for_status()
            return RestResult(response.json())

        return RestOperation(run)


class RestSupabaseClient:
    def __init__(self, supabase_url: str, service_role_key: str) -> None:
        self.supabase_url = supabase_url.rstrip("/")
        self.service_role_key = service_role_key

    def table_url(self, table_name: str) -> str:
        return f"{self.supabase_url}/rest/v1/{table_name}"

    def headers(self) -> dict[str, str]:
        return {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def table(self, table_name: str) -> RestTable:
        return RestTable(self, table_name)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_supabase_client() -> Any | None:
    settings = get_settings()
    if not settings.has_supabase_credentials:
        return None
    try:
        from supabase import create_client
    except (ImportError, AttributeError):
        return RestSupabaseClient(settings.supabase_url, settings.supabase_service_role_key)

    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def clean_job_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(record)
    cleaned.setdefault("job_type", "daily_selection")
    cleaned.setdefault("attempt_no", 1)
    cleaned.setdefault("pipeline_version", "local_v1")
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


def list_job_runs(
    *,
    job_type: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    client = get_supabase_client()
    if client is None:
        jobs = list(LOCAL_JOB_STORE.values())
        if job_type:
            jobs = [job for job in jobs if job.get("job_type") == job_type]
        if status:
            jobs = [job for job in jobs if job.get("status") == status]
        jobs.sort(key=lambda job: str(job.get("created_at") or job.get("updated_at") or ""), reverse=True)
        return deepcopy(jobs[: max(1, min(limit, 100))])

    query = client.table(JOB_TABLE).select("*")
    if job_type:
        query = query.eq("job_type", job_type)
    if status:
        query = query.eq("status", status)
    response = query.order("created_at", desc=True).limit(max(1, min(limit, 100))).execute()
    return getattr(response, "data", None) or []
