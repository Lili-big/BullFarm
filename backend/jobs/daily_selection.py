from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.settings import get_settings
from backend.job_store import upsert_job_run, utc_now
from backend.jobs.trading_calendar import (
    is_current_trading_day,
    iso_date,
    local_datetime,
    parse_compact_date,
    previous_trading_day_key,
)


JOB_TYPE = "daily_selection"
PIPELINE_VERSION = "local_v1"
LOCAL_SELECTION_CONFIG = Path("config/local_selection_job.json")
RUNNER_SCRIPT = Path("skills/stock-selection-agent/scripts/run_daily_selection.py")
SCHEDULED_TRIGGER_SOURCES = {"codex_automation", "cron"}


def default_target_date(now: datetime | None = None, project_root: Path | None = None) -> str:
    return previous_trading_day_key(now, project_root=project_root)


def non_trading_day_skip_payload(
    *,
    trigger_source: str,
    explicit_date: bool,
    now: datetime | None = None,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    if explicit_date or trigger_source not in SCHEDULED_TRIGGER_SOURCES:
        return None
    local_now = local_datetime(now)
    if is_current_trading_day(local_now, project_root=project_root):
        return None
    return {
        "skipped": True,
        "reason": "non_trading_day",
        "local_date": local_now.date().isoformat(),
        "local_time": local_now.isoformat(timespec="seconds"),
    }


def tail(text: str, limit: int = 6000) -> str:
    return text if len(text) <= limit else text[-limit:]


def build_daily_selection_command(
    target_date: str,
    as_of_date: str | None = None,
    dry_run: bool = False,
    project_root: Path | None = None,
    config_path: Path | None = None,
) -> list[str]:
    root = project_root or get_settings().project_root
    config = config_path or LOCAL_SELECTION_CONFIG
    command = [
        sys.executable,
        str(root / RUNNER_SCRIPT),
        "--config",
        str(config),
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
    return "failed"


def run_daily_selection_job(
    *,
    job_id: str | None = None,
    target_date: str | None = None,
    as_of_date: str | None = None,
    dry_run: bool = False,
    trigger_source: str = "manual",
    triggered_by: str | None = None,
    attempt_no: int = 1,
    request_payload: dict[str, Any] | None = None,
    config_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    root = settings.project_root
    explicit_date = target_date is not None or as_of_date is not None
    resolved_target = parse_compact_date(target_date or default_target_date(now, project_root=root))
    resolved_as_of = parse_compact_date(as_of_date or resolved_target)
    resolved_job_id = job_id or str(uuid4())
    skip_payload = non_trading_day_skip_payload(
        trigger_source=trigger_source,
        explicit_date=explicit_date,
        now=now,
        project_root=root,
    )

    base_record = {
        "job_id": resolved_job_id,
        "job_type": JOB_TYPE,
        "trigger_source": trigger_source,
        "triggered_by": triggered_by or trigger_source,
        "attempt_no": attempt_no,
        "pipeline_version": PIPELINE_VERSION,
        "target_date": iso_date(resolved_target),
        "status": "running",
        "dry_run": dry_run,
        "request_payload": request_payload or {},
        "started_at": utc_now(),
    }
    upsert_job_run(base_record)

    if skip_payload:
        return upsert_job_run(
            {
                **base_record,
                "status": "success",
                "result_payload": {
                    **skip_payload,
                    "target_date": resolved_target,
                    "as_of_date": resolved_as_of,
                },
                "log_excerpt": "skipped scheduled daily selection on non-trading day",
                "finished_at": utc_now(),
            }
        )

    command = build_daily_selection_command(
        resolved_target,
        as_of_date=resolved_as_of,
        dry_run=dry_run,
        project_root=root,
        config_path=config_path,
    )

    if dry_run:
        result_payload = {"command": command, "target_date": resolved_target, "as_of_date": resolved_as_of}
        record = {
            **base_record,
            "status": "success",
            "result_payload": result_payload,
            "log_excerpt": "dry-run planned daily selection command",
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
        "log_excerpt": tail((result.stderr or "") + "\n" + (result.stdout or ""), 2000),
        "error_message": error_message,
        "finished_at": utc_now(),
    }
    return upsert_job_run(record)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local daily stock selection job wrapper.")
    parser.add_argument("--run-date", help="Target archive date. Defaults to previous trading day.")
    parser.add_argument("--as-of-date", help="Market data date. Defaults to --run-date.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned command and avoid writes.")
    parser.add_argument(
        "--trigger-source",
        default="codex_automation",
        choices=["codex_automation", "manual", "local", "api", "retry", "cron"],
        help="Job trigger source.",
    )
    parser.add_argument("--triggered-by", default="codex_automation", help="Human or system actor label.")
    parser.add_argument("--attempt-no", type=int, default=1, help="Attempt number for this job execution.")
    parser.add_argument("--job-id", help="Optional existing job id.")
    parser.add_argument("--config", type=Path, default=LOCAL_SELECTION_CONFIG, help="Daily selection config JSON path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    explicit_date = args.run_date is not None or args.as_of_date is not None
    target_date = parse_compact_date(args.run_date) if args.run_date else default_target_date()
    as_of_date = parse_compact_date(args.as_of_date) if args.as_of_date else target_date
    if args.dry_run:
        skip_payload = non_trading_day_skip_payload(
            trigger_source=args.trigger_source,
            explicit_date=explicit_date,
            project_root=get_settings().project_root,
        )
        if skip_payload:
            print(
                json.dumps(
                    {
                        "status": "skipped",
                        "trigger_source": args.trigger_source,
                        "target_date": target_date,
                        "as_of_date": as_of_date,
                        **skip_payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        command = build_daily_selection_command(target_date, as_of_date=as_of_date, dry_run=True, config_path=args.config)
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
        target_date=args.run_date,
        as_of_date=args.as_of_date,
        dry_run=False,
        trigger_source=args.trigger_source,
        triggered_by=args.triggered_by,
        attempt_no=args.attempt_no,
        config_path=args.config,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return 0 if record.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
