from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

from backend.api import DailySelectionRequest, create_daily_selection_job, read_job, require_admin_token
from backend.jobs import daily_selection
from backend.jobs.supabase_price_update import (
    build_latest_performance_rows,
    build_latest_price_rows,
    pct_change,
)
from backend.supabase_jobs import LOCAL_JOB_STORE


ROOT = Path(__file__).resolve().parents[1]


class CloudRefactorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        LOCAL_JOB_STORE.clear()

    def test_render_cron_target_date_uses_previous_complete_trading_weekday(self) -> None:
        shanghai = timezone(timedelta(hours=8))

        self.assertEqual(
            "20260625",
            daily_selection.default_target_date(datetime(2026, 6, 26, 8, 30, tzinfo=shanghai)),
        )
        self.assertEqual(
            "20260626",
            daily_selection.default_target_date(datetime(2026, 6, 29, 8, 30, tzinfo=shanghai)),
        )

    def test_render_wrapper_builds_existing_runner_command(self) -> None:
        command = daily_selection.build_daily_selection_command(
            "2026-06-25",
            as_of_date="20260625",
            dry_run=True,
            project_root=ROOT,
        )

        self.assertIn(str(ROOT / "skills" / "stock-selection-agent" / "scripts" / "run_daily_selection.py"), command)
        self.assertIn("--config", command)
        self.assertEqual(Path("config/render_daily_selection.json"), Path(command[command.index("--config") + 1]))
        self.assertEqual("20260625", command[command.index("--run-date") + 1])
        self.assertEqual("20260625", command[command.index("--as-of-date") + 1])
        self.assertIn("--dry-run", command)

    def test_api_requires_admin_token_and_can_create_dry_run_job(self) -> None:
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

            payload = create_daily_selection_job(
                BackgroundTasks(),
                DailySelectionRequest(run_date="20260625", as_of_date="20260625", dry_run=True),
                None,
            )
            self.assertEqual("queued", payload["status"])
            self.assertTrue(payload["dry_run"])

            status = read_job(payload["job_id"], None)
            self.assertEqual(payload["job_id"], status["job_id"])
            self.assertEqual("queued", status["status"])

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
                "decision": "轻仓试错",
                "buy_model": "突破",
                "sector": "AI应用",
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
        self.assertEqual(105.0, prices[0]["close"])
        self.assertEqual(5.0, performance[0]["return_latest_pct"])
        self.assertTrue(performance[0]["is_profitable_latest"])
        self.assertEqual(5.0, pct_change(105, 100))

    def test_frontend_and_deploy_configs_keep_service_role_server_side(self) -> None:
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

        render = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("startCommand: uvicorn backend.api:app --host 0.0.0.0 --port $PORT", render)
        self.assertIn('schedule: "30 0 * * *"', render)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", render)
        self.assertIn("sync: false", render)

    def test_render_daily_config_writes_supabase_without_local_dashboard_or_workbook(self) -> None:
        config = json.loads((ROOT / "config" / "render_daily_selection.json").read_text(encoding="utf-8"))

        self.assertFalse(config["validation_snapshot"]["enabled"])
        self.assertFalse(config["price_update"]["enabled"])
        self.assertFalse(config["dashboard"]["enabled"])
        self.assertTrue(config["supabase"]["enabled"])
        self.assertFalse(config["supabase"]["plugin_handoff"])
        command = config["supabase"]["commands"][0]
        self.assertIn("--fail-on-skip", command)
        self.assertNotIn("--include-workbook-runs", command)
        self.assertNotIn("--write-sql-dir", command)


if __name__ == "__main__":
    unittest.main()
