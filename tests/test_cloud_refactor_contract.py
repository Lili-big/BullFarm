from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

from backend.api import (
    DailySelectionRequest,
    PriceRefreshRequest,
    RetryJobRequest,
    create_daily_selection_job,
    create_price_refresh_job,
    list_jobs,
    read_job,
    read_job_logs,
    require_admin_token,
    retry_job,
)
from backend.jobs import daily_selection, price_refresh, trading_calendar
from backend.jobs.supabase_price_update import (
    build_latest_performance_rows,
    build_latest_price_rows,
    pct_change,
)
from backend.supabase_jobs import LOCAL_JOB_STORE, upsert_job_run


ROOT = Path(__file__).resolve().parents[1]


class LocalAutomationRefactorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        LOCAL_JOB_STORE.clear()

    def test_local_selection_target_date_uses_previous_complete_trading_weekday(self) -> None:
        shanghai = timezone(timedelta(hours=8))

        self.assertEqual(
            "20260625",
            daily_selection.default_target_date(datetime(2026, 6, 26, 8, 30, tzinfo=shanghai)),
        )
        self.assertEqual(
            "20260626",
            daily_selection.default_target_date(datetime(2026, 6, 29, 8, 30, tzinfo=shanghai)),
        )

    def test_price_refresh_defaults_to_previous_trading_day(self) -> None:
        shanghai = timezone(timedelta(hours=8))

        self.assertEqual(
            "20260625",
            price_refresh.default_price_date(datetime(2026, 6, 26, 9, 30, tzinfo=shanghai)),
        )
        self.assertEqual(
            "20260625",
            price_refresh.default_price_date(datetime(2026, 6, 26, 16, 10, tzinfo=shanghai)),
        )
        self.assertEqual(
            "20260626",
            price_refresh.default_price_date(datetime(2026, 6, 27, 16, 10, tzinfo=shanghai)),
        )
        self.assertEqual(
            "20260626",
            price_refresh.default_price_date(datetime(2026, 6, 29, 16, 10, tzinfo=shanghai)),
        )

    def test_trading_calendar_holidays_change_previous_trading_day(self) -> None:
        shanghai = timezone(timedelta(hours=8))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "trading_calendar.json").write_text(
                json.dumps(
                    {
                        "holidays": ["2026-06-26"],
                        "makeup_trading_days": ["2026-06-20"],
                    }
                ),
                encoding="utf-8",
            )

            self.assertFalse(trading_calendar.is_trading_day("20260626", project_root=root))
            self.assertTrue(trading_calendar.is_trading_day("20260620", project_root=root))
            self.assertEqual(
                "20260625",
                daily_selection.default_target_date(datetime(2026, 6, 29, 8, 30, tzinfo=shanghai), project_root=root),
            )
            self.assertEqual(
                "20260625",
                price_refresh.default_price_date(datetime(2026, 6, 29, 16, 10, tzinfo=shanghai), project_root=root),
            )

    def test_codex_automation_skips_non_trading_day_without_explicit_date(self) -> None:
        shanghai = timezone(timedelta(hours=8))
        now = datetime(2026, 6, 27, 8, 30, tzinfo=shanghai)
        with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}, clear=False):
            daily_record = daily_selection.run_daily_selection_job(
                job_id="00000000-0000-0000-0000-000000000101",
                dry_run=True,
                trigger_source="codex_automation",
                now=now,
            )
            price_record = price_refresh.run_price_refresh_job(
                job_id="00000000-0000-0000-0000-000000000102",
                dry_run=True,
                trigger_source="codex_automation",
                now=now,
            )

        self.assertEqual("success", daily_record["status"])
        self.assertTrue(daily_record["result_payload"]["skipped"])
        self.assertEqual("non_trading_day", daily_record["result_payload"]["reason"])
        self.assertEqual("20260626", daily_record["result_payload"]["target_date"])

        self.assertEqual("success", price_record["status"])
        self.assertTrue(price_record["result_payload"]["skipped"])
        self.assertEqual("non_trading_day", price_record["result_payload"]["reason"])
        self.assertEqual("20260626", price_record["result_payload"]["as_of_date"])

    def test_explicit_scheduled_dates_can_rerun_on_non_trading_day(self) -> None:
        shanghai = timezone(timedelta(hours=8))
        with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}, clear=False):
            record = price_refresh.run_price_refresh_job(
                job_id="00000000-0000-0000-0000-000000000103",
                as_of_date="20260625",
                dry_run=True,
                trigger_source="codex_automation",
                now=datetime(2026, 6, 27, 16, 10, tzinfo=shanghai),
            )

        self.assertEqual("success", record["status"])
        self.assertNotIn("skipped", record["result_payload"])
        self.assertEqual("20260625", record["result_payload"]["as_of_date"])

    def test_local_selection_wrapper_builds_existing_runner_command(self) -> None:
        command = daily_selection.build_daily_selection_command(
            "2026-06-25",
            as_of_date="20260625",
            dry_run=True,
            project_root=ROOT,
        )

        self.assertIn(str(ROOT / "skills" / "stock-selection-agent" / "scripts" / "run_daily_selection.py"), command)
        self.assertIn("--config", command)
        self.assertEqual(Path("config/local_selection_job.json"), Path(command[command.index("--config") + 1]))
        self.assertEqual("20260625", command[command.index("--run-date") + 1])
        self.assertEqual("20260625", command[command.index("--as-of-date") + 1])
        self.assertIn("--dry-run", command)

    def test_price_refresh_wrapper_builds_update_analyze_and_sync_commands(self) -> None:
        commands = price_refresh.build_price_refresh_commands("20260625", project_root=ROOT, dry_run=True)

        self.assertEqual(3, len(commands))
        self.assertIn("validate_selection_results.py", commands[0][1])
        self.assertIn("update-prices", commands[0])
        self.assertIn("--latest", commands[0])
        self.assertIn("analyze", commands[1])
        self.assertIn("sync_supabase.py", commands[2][1])
        self.assertIn("--include-workbook-runs", commands[2])
        self.assertIn("--fail-on-skip", commands[2])

    def test_api_requires_admin_token_and_can_create_local_jobs(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ADMIN_TRIGGER_TOKEN": "unit-token",
                "SUPABASE_URL": "",
                "SUPABASE_SERVICE_ROLE_KEY": "",
            },
            clear=False,
        ):
            request = SimpleNamespace(headers={})
            with self.assertRaises(HTTPException) as raised:
                require_admin_token(request, None)
            self.assertEqual(401, raised.exception.status_code)

            authed_request = SimpleNamespace(headers={"authorization": "Bearer unit-token"})
            require_admin_token(authed_request, None)

            daily_payload = create_daily_selection_job(
                BackgroundTasks(),
                DailySelectionRequest(run_date="20260625", as_of_date="20260625", dry_run=True),
                None,
            )
            self.assertEqual("queued", daily_payload["status"])
            self.assertEqual("daily_selection", read_job(daily_payload["job_id"], None)["job_type"])

            price_payload = create_price_refresh_job(
                BackgroundTasks(),
                PriceRefreshRequest(as_of_date="20260625", dry_run=True),
                None,
            )
            self.assertEqual("queued", price_payload["status"])
            self.assertEqual("price_refresh", read_job(price_payload["job_id"], None)["job_type"])

            jobs = list_jobs(None, None, 10, None)["jobs"]
            self.assertEqual(2, len(jobs))

    def test_api_can_retry_and_read_logs(self) -> None:
        original = upsert_job_run(
            {
                "job_id": "00000000-0000-0000-0000-000000000001",
                "job_type": "price_refresh",
                "trigger_source": "api",
                "target_date": "2026-06-25",
                "status": "failed",
                "dry_run": True,
                "request_payload": {"as_of_date": "20260625"},
                "result_payload": {"command_results": [{"stdout_tail": "old", "stderr_tail": "failed"}]},
                "log_excerpt": "failed log",
            }
        )

        retry = retry_job(original["job_id"], BackgroundTasks(), RetryJobRequest(dry_run=True), None)

        self.assertEqual(original["job_id"], retry["retry_of"])
        self.assertEqual("price_refresh", retry["job_type"])
        self.assertEqual(2, retry["attempt_no"])
        self.assertEqual("queued", read_job(retry["job_id"], None)["status"])
        logs = read_job_logs(original["job_id"], None)
        self.assertEqual("failed log", logs["log_excerpt"])
        self.assertEqual("price_refresh", logs["job_type"])

    def test_supabase_price_update_payloads_do_not_require_workbook(self) -> None:
        selections = [
            {
                "run_id": "20260625_daily_v1_0",
                "stock_code": "300223",
                "stock_name": "Sample Tech",
                "selection_date": "2026-06-25",
                "selection_price": 100,
                "total_score": 72,
                "rank_in_run": 1,
                "decision": "watch",
                "buy_model": "breakout",
                "sector": "AI",
            }
        ]
        quotes = {
            "300223.SZ": {
                "trade_date": "2026-06-26",
                "open": 101,
                "high": 106,
                "low": 100,
                "close": 105,
                "volume": 1000000,
                "amount": 105000000,
            }
        }

        prices = build_latest_price_rows(selections, quotes)
        performance = build_latest_performance_rows(selections, quotes)

        self.assertEqual("LATEST", prices[0]["trading_day_offset"])
        self.assertEqual("local_supabase_price_update", prices[0]["data_source"])
        self.assertEqual(105.0, prices[0]["close"])
        self.assertEqual(5.0, performance[0]["return_latest_pct"])
        self.assertTrue(performance[0]["is_profitable_latest"])
        self.assertEqual(5.0, pct_change(105, 100))

    def test_frontend_and_local_configs_keep_service_role_server_side(self) -> None:
        frontend_files = [
            path
            for path in (ROOT / "frontend").rglob("*")
            if path.is_file() and path.suffix in {".js", ".jsx", ".css", ".html", ".json", ".example"}
        ]
        frontend_text = "\n".join(path.read_text(encoding="utf-8") for path in frontend_files)
        self.assertIn("VITE_SUPABASE_URL", frontend_text)
        self.assertIn("VITE_SUPABASE_ANON_KEY", frontend_text)
        self.assertNotIn("SERVICE_ROLE", frontend_text.upper())

        netlify = (ROOT / "netlify.toml").read_text(encoding="utf-8")
        self.assertIn('base = "frontend"', netlify)
        self.assertIn('publish = "dist"', netlify)

        local_config = json.loads((ROOT / "config" / "local_selection_job.json").read_text(encoding="utf-8"))
        self.assertTrue(local_config["supabase"]["enabled"])
        self.assertFalse(local_config["supabase"]["plugin_handoff"])
        self.assertFalse(local_config["price_update"]["enabled"])
        command = local_config["supabase"]["commands"][0]
        self.assertIn("--fail-on-skip", command)
        self.assertNotIn("--include-workbook-runs", command)
        self.assertNotIn("--write-sql-dir", command)

    def test_local_job_migration_extends_private_job_table(self) -> None:
        migration_files = list((ROOT / "supabase" / "migrations").glob("*.sql"))
        sql = "\n".join(path.read_text(encoding="utf-8").lower() for path in migration_files)

        self.assertIn("add column if not exists job_type", sql)
        self.assertIn("add column if not exists attempt_no", sql)
        self.assertIn("add column if not exists pipeline_version", sql)
        self.assertIn("add column if not exists triggered_by", sql)
        self.assertIn("add column if not exists log_excerpt", sql)
        self.assertIn("price_refresh", sql)
        self.assertIn("revoke all on table public.stock_selection_job_runs from anon", sql)


if __name__ == "__main__":
    unittest.main()
