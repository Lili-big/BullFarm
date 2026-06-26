from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.settings import get_settings
from backend.supabase_jobs import upsert_job_run, utc_now


RENDER_CONFIG = Path("config/render_daily_selection.json")
RUNNER_SCRIPT = Path("skills/stock-selection-agent/scripts/run_daily_selection.py")


def parse_compact_date(value: str) -> str:
    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    raise ValueError(f"Expected YYYYMMDD or YYYY-MM-DD, got {value!r}.")


def app_timezone():
    settings = get_settings()
    try:
        return ZoneInfo(settings.app_timezone)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=8))


def previous_weekday(day: datetime) -> datetime:
    current = day - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def default_target_date(now: datetime | None = None) -> str:
    tz = app_timezone()
    local_now = (now or datetime.now(tz)).astimezone(tz)
    return previous_weekday(local_now).strftime("%Y%m%d")


def tail(text: str, limit: int = 6000) -> str:
    return text if len(text) <= limit else text[-limit:]


def build_daily_selection_command(
    target_date: str,
    as_of_date: str | None = None,
    dry_run: bool = False,
    project_root: Path | None = None,
) -> list[str]:
    root = project_root or get_settings().project_root
    command = [
        sys.executable,
        str(root / RUNNER_SCRIPT),
        "--config",
        str(RENDER_CONFIG),
        "--project-root",
        str(root),
        "--run-date",
        parse_compact_date(target_date),
        "--as-of-date",
        parse_compact_date(as_of_date or target_date),
    ]
    if dry_run:
        command.append("--dry-run")
    return command


def read_manifest(project_root: Path, target_date: str) -> dict[str, Any]:
    manifest_path = project_root / "outputs" / "daily" / parse_compact_date(target_date) / "run_manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8-sig"))


def status_from_returncode(returncode: int) -> str:
    if returncode == 0:
        return "success"
    if returncode == 2:
        return "pending_supabase"
    return "failed"


def run_daily_selection_job(
    *,
    job_id: str | None = None,
    target_date: str | None = None,
    as_of_date: str | None = None,
    dry_run: bool = False,
    trigger_source: str = "manual",
    request_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    root = settings.project_root
    resolved_target = parse_compact_date(target_date or default_target_date())
    resolved_as_of = parse_compact_date(as_of_date or resolved_target)
    resolved_job_id = job_id or str(uuid4())
    command = build_daily_selection_command(
        resolved_target,
        as_of_date=resolved_as_of,
        dry_run=dry_run,
        project_root=root,
    )

    base_record = {
        "job_id": resolved_job_id,
        "trigger_source": trigger_source,
        "target_date": datetime.strptime(resolved_target, "%Y%m%d").date().isoformat(),
        "status": "running",
        "dry_run": dry_run,
        "request_payload": request_payload or {},
        "started_at": utc_now(),
    }
    upsert_job_run(base_record)

    if dry_run:
        result_payload = {"command": command, "target_date": resolved_target, "as_of_date": resolved_as_of}
        record = {
            **base_record,
            "status": "success",
            "result_payload": result_payload,
            "finished_at": utc_now(),
        }
        return upsert_job_run(record)

    result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    manifest = read_manifest(root, resolved_target)
    status = status_from_returncode(result.returncode)
    error_message = None
    if status == "failed":
        manifest_error = manifest.get("error") if isinstance(manifest, dict) else None
        error_message = (manifest_error or {}).get("message") or tail(result.stderr or result.stdout, 1000)

    record = {
        **base_record,
        "status": status,
        "run_id": manifest.get("run_id") if isinstance(manifest, dict) else None,
        "result_payload": {
            "command": command,
            "returncode": result.returncode,
            "stdout_tail": tail(result.stdout),
            "stderr_tail": tail(result.stderr),
            "manifest_status": manifest.get("status") if isinstance(manifest, dict) else None,
        },
        "error_message": error_message,
        "finished_at": utc_now(),
    }
    return upsert_job_run(record)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Render daily stock selection wrapper.")
    parser.add_argument("--run-date", help="Target archive date. Defaults to previous complete trading weekday.")
    parser.add_argument("--as-of-date", help="Market data date. Defaults to --run-date.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned command and avoid writes.")
    parser.add_argument("--trigger-source", default="cron", choices=["cron", "manual", "local"], help="Job trigger source.")
    parser.add_argument("--job-id", help="Optional existing job id.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target_date = parse_compact_date(args.run_date) if args.run_date else default_target_date()
    as_of_date = parse_compact_date(args.as_of_date) if args.as_of_date else target_date
    if args.dry_run:
        command = build_daily_selection_command(target_date, as_of_date=as_of_date, dry_run=True)
        print(
            json.dumps(
                {
                    "status": "planned",
                    "trigger_source": args.trigger_source,
                    "target_date": target_date,
                    "as_of_date": as_of_date,
                    "command": command,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    record = run_daily_selection_job(
        job_id=args.job_id,
        target_date=target_date,
        as_of_date=as_of_date,
        dry_run=False,
        trigger_source=args.trigger_source,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return 0 if record.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
