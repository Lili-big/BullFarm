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
from backend.supabase_jobs import upsert_job_run, utc_now
from backend.jobs.trading_calendar import (
    is_current_trading_day,
    iso_date,
    local_datetime,
    parse_compact_date,
    previous_trading_day_key,
)


JOB_TYPE = "price_refresh"
PIPELINE_VERSION = "local_v1"
VALIDATION_SCRIPT = Path("skills/stock-selection-agent/scripts/validate_selection_results.py")
SYNC_SCRIPT = Path("skills/stock-selection-agent/scripts/sync_supabase.py")
SCHEDULED_TRIGGER_SOURCES = {"codex_automation", "cron"}


def default_price_date(now: datetime | None = None, project_root: Path | None = None) -> str:
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


def parse_command_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def build_price_refresh_commands(
    as_of_date: str,
    *,
    project_root: Path | None = None,
    dry_run: bool = False,
) -> list[list[str]]:
    root = project_root or get_settings().project_root
    compact_date = parse_compact_date(as_of_date)
    commands = [
        [
            sys.executable,
            str(root / VALIDATION_SCRIPT),
            "update-prices",
            "--all",
            "--latest",
            "--price-provider",
            "tencent",
            "--end-date",
            compact_date,
        ],
        [
            sys.executable,
            str(root / VALIDATION_SCRIPT),
            "analyze",
            "--all",
        ],
        [
            sys.executable,
            str(root / SYNC_SCRIPT),
            "--include-workbook-runs",
            "--operator",
            "local_automation",
            "--notes",
            f"price_refresh:{compact_date}",
            "--fail-on-skip",
        ],
    ]
    if dry_run:
        return commands
    return commands


def run_price_refresh_job(
    *,
    job_id: str | None = None,
    as_of_date: str | None = None,
    dry_run: bool = False,
    trigger_source: str = "manual",
    triggered_by: str | None = None,
    attempt_no: int = 1,
    request_payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    root = settings.project_root
    explicit_date = as_of_date is not None
    resolved_as_of = parse_compact_date(as_of_date or default_price_date(now, project_root=root))
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
        "target_date": iso_date(resolved_as_of),
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
                    "as_of_date": resolved_as_of,
                },
                "log_excerpt": "skipped scheduled price refresh on non-trading day",
                "finished_at": utc_now(),
            }
        )

    commands = build_price_refresh_commands(resolved_as_of, project_root=root, dry_run=dry_run)

    if dry_run:
        return upsert_job_run(
            {
                **base_record,
                "status": "success",
                "result_payload": {"commands": commands, "as_of_date": resolved_as_of},
                "log_excerpt": "dry-run planned price refresh commands",
                "finished_at": utc_now(),
            }
        )

    command_results: list[dict[str, Any]] = []
    status = "success"
    error_message = None
    for command in commands:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        command_result = {
            "command": command,
            "returncode": result.returncode,
            "stdout_tail": tail(result.stdout),
            "stderr_tail": tail(result.stderr),
            "summary": parse_command_json(result.stdout),
        }
        command_results.append(command_result)
        if result.returncode != 0:
            status = "failed"
            error_message = tail(result.stderr or result.stdout, 1000)
            break

    log_text = "\n".join(
        f"{item['command'][1] if len(item['command']) > 1 else item['command'][0]}\n"
        f"stdout:\n{item['stdout_tail']}\nstderr:\n{item['stderr_tail']}"
        for item in command_results
    )
    return upsert_job_run(
        {
            **base_record,
            "status": status,
            "result_payload": {
                "as_of_date": resolved_as_of,
                "command_results": command_results,
            },
            "error_message": error_message,
            "log_excerpt": tail(log_text, 2000),
            "finished_at": utc_now(),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local price refresh job wrapper.")
    parser.add_argument("--as-of-date", help="Review market data date. Defaults to previous trading day.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned commands and avoid writes.")
    parser.add_argument(
        "--trigger-source",
        default="codex_automation",
        choices=["codex_automation", "manual", "local", "api", "retry", "cron"],
        help="Job trigger source.",
    )
    parser.add_argument("--triggered-by", default="codex_automation", help="Human or system actor label.")
    parser.add_argument("--attempt-no", type=int, default=1, help="Attempt number for this job execution.")
    parser.add_argument("--job-id", help="Optional existing job id.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    explicit_date = args.as_of_date is not None
    as_of_date = parse_compact_date(args.as_of_date) if args.as_of_date else default_price_date()
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
                        "as_of_date": as_of_date,
                        **skip_payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        commands = build_price_refresh_commands(as_of_date, dry_run=True)
        print(
            json.dumps(
                {
                    "status": "planned",
                    "trigger_source": args.trigger_source,
                    "as_of_date": as_of_date,
                    "commands": commands,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    record = run_price_refresh_job(
        job_id=args.job_id,
        as_of_date=args.as_of_date,
        dry_run=False,
        trigger_source=args.trigger_source,
        triggered_by=args.triggered_by,
        attempt_no=args.attempt_no,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return 0 if record.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
