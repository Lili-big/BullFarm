from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "stock-selection-agent" / "scripts" / "run_daily_selection.py"
SPEC = importlib.util.spec_from_file_location("run_daily_selection", SCRIPT)
daily = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = daily
SPEC.loader.exec_module(daily)


class DailySelectionJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        (self.project_root / "config").mkdir(parents=True)
        self.config_path = self.project_root / "config" / "daily_selection.json"
        self.write_config(ROOT / "data" / "sample_candidates.csv")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_config(self, offline_candidate_csv: Path) -> None:
        payload = {
            "paths": {
                "snapshot_root": "data/snapshots",
                "daily_output_root": "outputs/daily",
                "latest_name": "latest",
            },
            "strategy": {
                "id": "v1_trend_startup",
                "version": "v1_0",
            },
            "run_id_template": "{run_date}_daily_{strategy_version}",
            "live_fetch": {
                "enabled": True,
                "script": str(ROOT / "skills" / "stock-selection-agent" / "scripts" / "fetch_live_candidates.py"),
                "provider": "akshare",
                "workers": 4,
                "quote_batch_size": 800,
                "include_bj": False,
                "candidate_name": "candidates.csv",
                "meta_name": "fetch_meta.json",
                "skip_live_fetch_sources": [str(offline_candidate_csv)],
            },
            "scoring": {
                "script": str(ROOT / "skills" / "stock-selection-agent" / "scripts" / "score_candidates.py"),
                "config": str(ROOT / "config" / "scoring_rules.json"),
                "report_name": "selection_report.md",
                "scores_name": "selection_scores.csv",
            },
            "price_update": {"enabled": False, "command": []},
            "supabase": {"enabled": False, "command": []},
        }
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_live_fetch_command_passes_tencent_tuning_options(self) -> None:
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        payload["live_fetch"]["provider"] = "tencent_range"
        payload["live_fetch"]["include_bj"] = True
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        config = daily.load_config(self.config_path)
        command = daily.build_live_fetch_command(
            self.project_root,
            config,
            self.project_root / "data" / "snapshots" / "20260625" / "candidates.csv",
            self.project_root / "data" / "snapshots" / "20260625" / "fetch_meta.json",
            "20260625",
        )

        self.assertIn("--quote-batch-size", command)
        self.assertEqual("800", command[command.index("--quote-batch-size") + 1])
        self.assertIn("--include-bj", command)
        self.assertIn("--meta-output", command)
        self.assertTrue(command[command.index("--meta-output") + 1].endswith("fetch_meta.json"))
        self.assertEqual("4", command[command.index("--workers") + 1])

    def enable_supabase_plugin_handoff(self) -> None:
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        payload["supabase"] = {
            "enabled": True,
            "plugin_handoff": True,
            "require_write": True,
            "commands": [
                [
                    "{python}",
                    str(ROOT / "skills" / "stock-selection-agent" / "scripts" / "sync_supabase.py"),
                    "--run-id",
                    "{run_id}",
                    "--selection-date",
                    "{as_of_date}",
                    "--scores",
                    "{scores}",
                    "--candidates",
                    "{candidate_csv}",
                    "--metadata",
                    "{fetch_meta}",
                    "--report",
                    "{report}",
                    "--workbook",
                    str(self.project_root / "missing_workbook.xlsx"),
                    "--write-sql-dir",
                    "{supabase_sql_dir}",
                    "--sql-compact",
                    "--env-file",
                    str(self.project_root / "missing.env"),
                ]
            ],
        }
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def run_job(self, *extra: str) -> int:
        return daily.main(
            [
                "--project-root",
                str(self.project_root),
                "--config",
                str(self.config_path),
                *extra,
            ]
        )

    def read_manifest(self, run_date: str) -> dict:
        path = self.project_root / "outputs" / "daily" / run_date / "run_manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_skip_live_fetch_archives_outputs_and_updates_latest(self) -> None:
        code = self.run_job(
            "--run-date",
            "2026-06-25",
            "--as-of-date",
            "2026-06-25",
            "--skip-live-fetch",
            "--skip-supabase",
            "--skip-price-update",
        )

        self.assertEqual(0, code)
        snapshot_dir = self.project_root / "data" / "snapshots" / "20260625"
        output_dir = self.project_root / "outputs" / "daily" / "20260625"
        self.assertTrue((snapshot_dir / "candidates.csv").exists())
        self.assertTrue((snapshot_dir / "fetch_meta.json").exists())
        self.assertTrue((output_dir / "selection_report.md").exists())
        self.assertTrue((output_dir / "selection_scores.csv").exists())
        self.assertTrue((self.project_root / "data" / "snapshots" / "latest" / "candidates.csv").exists())
        self.assertTrue((self.project_root / "outputs" / "daily" / "latest" / "selection_scores.csv").exists())

        manifest = self.read_manifest("20260625")
        self.assertEqual("success", manifest["status"])
        self.assertEqual("20260625", manifest["run_date"])
        self.assertEqual("20260625_daily_v1_0", manifest["run_id"])
        self.assertEqual("skipped", manifest["stages"][0]["status"])
        self.assertEqual("score_candidates", manifest["stages"][1]["name"])
        self.assertEqual("success", manifest["stages"][1]["status"])

    def test_failure_writes_manifest_without_updating_latest(self) -> None:
        self.assertEqual(
            0,
            self.run_job(
                "--run-date",
                "20260625",
                "--skip-live-fetch",
                "--skip-supabase",
                "--skip-price-update",
            ),
        )
        latest_manifest = self.project_root / "outputs" / "daily" / "latest" / "run_manifest.json"
        self.assertEqual("20260625", json.loads(latest_manifest.read_text(encoding="utf-8"))["run_date"])

        missing_source = self.project_root / "missing_candidates.csv"
        self.write_config(missing_source)
        code = self.run_job(
            "--run-date",
            "20260626",
            "--skip-live-fetch",
            "--skip-supabase",
            "--skip-price-update",
        )

        self.assertEqual(1, code)
        failure = self.read_manifest("20260626")
        self.assertEqual("failed", failure["status"])
        self.assertIn("No candidate CSV", failure["error"]["message"])
        self.assertEqual("20260625", json.loads(latest_manifest.read_text(encoding="utf-8"))["run_date"])

    def test_dry_run_prints_plan_without_writing_archives(self) -> None:
        code = self.run_job("--dry-run", "--run-date", "20260625", "--skip-live-fetch")

        self.assertEqual(0, code)
        self.assertFalse((self.project_root / "outputs").exists())
        self.assertFalse((self.project_root / "data").exists())

    def test_as_of_date_defaults_to_latest_complete_weekday_before_close(self) -> None:
        self.assertEqual(
            "20260624",
            daily.latest_complete_market_date("20260625", datetime(2026, 6, 25, 8, 30)),
        )
        self.assertEqual(
            "20260625",
            daily.latest_complete_market_date("20260625", datetime(2026, 6, 25, 15, 30)),
        )
        self.assertEqual(
            "20260626",
            daily.latest_complete_market_date("20260627", datetime(2026, 6, 27, 8, 30)),
        )

    def test_as_of_date_uses_trading_calendar_holiday(self) -> None:
        (self.project_root / "config" / "trading_calendar.json").write_text(
            json.dumps({"holidays": ["2026-06-26"]}),
            encoding="utf-8",
        )

        self.assertEqual(
            "20260625",
            daily.latest_complete_market_date(
                "20260626",
                datetime(2026, 6, 26, 15, 30),
                project_root=self.project_root,
            ),
        )

    def test_missing_supabase_env_creates_sql_bundle_and_blocks_latest_until_finalize(self) -> None:
        self.enable_supabase_plugin_handoff()
        code = self.run_job(
            "--run-date",
            "2026-06-25",
            "--as-of-date",
            "2026-06-25",
            "--skip-live-fetch",
            "--skip-price-update",
        )

        self.assertEqual(2, code)
        manifest = self.read_manifest("20260625")
        self.assertEqual("pending_supabase", manifest["status"])
        self.assertIn("supabase_sql_bundle", manifest)
        sql_dir = self.project_root / "outputs" / "daily" / "20260625" / "supabase_sql"
        self.assertTrue((sql_dir / "manifest.json").exists())
        self.assertFalse((self.project_root / "outputs" / "daily" / "latest").exists())

        finalize_code = self.run_job(
            "--finalize-run",
            "2026-06-25",
            "--verified-run-id",
            manifest["run_id"],
        )

        self.assertEqual(0, finalize_code)
        finalized = self.read_manifest("20260625")
        self.assertEqual("success", finalized["status"])
        self.assertTrue((self.project_root / "outputs" / "daily" / "latest" / "selection_scores.csv").exists())


if __name__ == "__main__":
    unittest.main()
