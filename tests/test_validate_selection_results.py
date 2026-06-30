from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "stock-selection-agent" / "scripts" / "validate_selection_results.py"
SPEC = importlib.util.spec_from_file_location("validate_selection_results", SCRIPT)
validation = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = validation
SPEC.loader.exec_module(validation)


class ValidationResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.scores = self.base / "selection_scores.csv"
        self.candidates = self.base / "candidates.csv"
        self.prices = self.base / "prices.csv"
        self.output_excel = self.base / "stock_selection_log.xlsx"
        self.config = self.base / "validation_rules.json"
        self.config.write_text(
            """{
              "validation": {
                "output_excel": "stock_selection_log.xlsx",
                "report_dir": "reports",
                "backup_dir": "backup",
                "default_offsets": [0, 1, 2, 3, 5, 10],
                "holding_days": 3,
                "stop_loss_pct": -3,
                "take_profit_pct": 5,
                "auto_backup_excel": true
              }
            }""",
            encoding="utf-8",
        )
        self.write_csv(
            self.scores,
            [
                {
                    "rank": 1,
                    "symbol": "300223",
                    "name": "北京君正",
                    "sector": "电子器件",
                    "total_score": 70,
                    "trend_score": 40,
                    "startup_score": 25,
                    "sector_score": 5,
                    "market_score": 0,
                    "decision": "只观察",
                    "continuation": "弱延续",
                    "buy_model": "平台突破买点",
                    "notes": "中期结构清晰",
                    "risks": "板块分低",
                    "hard_rejects": "",
                    "plan": "加入观察池",
                }
            ],
        )
        self.write_csv(
            self.candidates,
            [
                {
                    "symbol": "300223",
                    "name": "北京君正",
                    "sector": "电子器件",
                    "close": 100.0,
                }
            ],
        )
        price_rows = []
        closes = [100, 101, 99, 104, 103, 105, 106, 107, 108, 109, 110]
        lows = [99, 100, 96, 102, 101, 104, 105, 106, 107, 108, 109]
        highs = [101, 102, 101, 106, 104, 106, 107, 108, 109, 110, 111]
        dates = [
            "2026-06-23",
            "2026-06-24",
            "2026-06-25",
            "2026-06-26",
            "2026-06-29",
            "2026-06-30",
            "2026-07-01",
            "2026-07-02",
            "2026-07-03",
            "2026-07-06",
            "2026-07-07",
        ]
        for idx, trade_date in enumerate(dates):
            price_rows.append(
                {
                    "trade_date": trade_date,
                    "stock_code": "300223.SZ",
                    "open": closes[idx] - 0.5,
                    "high": highs[idx],
                    "low": lows[idx],
                    "close": closes[idx],
                    "volume": 1000000 + idx,
                    "amount": 100000000 + idx,
                    "turnover_rate": 2.1,
                }
            )
        self.write_csv(self.prices, price_rows)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        fields = list(rows[0].keys())
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def run_cli(self, *args: str) -> int:
        return validation.main(
            [
                "--config",
                str(self.config),
                "--output-excel",
                str(self.output_excel),
                *args,
            ]
        )

    def load_records(self, sheet: str) -> list[dict[str, object]]:
        workbook = validation.ensure_workbook(self.output_excel)
        return validation.worksheet_records(workbook, sheet)

    def test_code_normalization_and_run_id(self) -> None:
        self.assertEqual(validation.normalize_stock_code("600000"), "600000.SH")
        self.assertEqual(validation.normalize_stock_code("000001"), "000001.SZ")
        self.assertEqual(validation.normalize_stock_code("430001"), "430001.BJ")
        run_id = validation.generate_run_id("2026-06-23", "v1.0")
        self.assertRegex(run_id, r"^20260623_\d{6}_v1_0$")

    def test_snapshot_rejects_duplicate_run_unless_force(self) -> None:
        args = [
            "snapshot",
            "--scores",
            str(self.scores),
            "--candidates",
            str(self.candidates),
            "--run-id",
            "20260623_153000_v1_0",
            "--selection-date",
            "2026-06-23",
            "--market-env",
            "震荡",
        ]
        self.assertEqual(self.run_cli(*args), 0)
        self.assertEqual(self.run_cli(*args), 2)
        self.assertEqual(self.run_cli(*args, "--force"), 0)
        selected = self.load_records("selected_stocks")
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["stock_code"], "300223.SZ")
        self.assertEqual(float(selected[0]["selection_price"]), 100.0)

    def test_full_validation_flow_generates_excel_and_report(self) -> None:
        run_id = "20260623_153000_v1_0"
        self.assertEqual(
            self.run_cli(
                "snapshot",
                "--scores",
                str(self.scores),
                "--candidates",
                str(self.candidates),
                "--run-id",
                run_id,
                "--selection-date",
                "2026-06-23",
                "--market-env",
                "震荡",
            ),
            0,
        )
        self.assertEqual(
            self.run_cli(
                "update-prices",
                "--run-id",
                run_id,
                "--price-file",
                str(self.prices),
                "--offsets",
                "0,1,2,3,5,10",
            ),
            0,
        )
        self.assertEqual(self.run_cli("analyze", "--run-id", run_id), 0)
        self.assertEqual(self.run_cli("compare", "--group-by", "participation_level"), 0)
        report_dir = self.base / "reports"
        self.assertEqual(self.run_cli("report", "--run-id", run_id, "--report-dir", str(report_dir)), 0)

        future_prices = self.load_records("future_prices")
        performance = self.load_records("performance")
        summary = self.load_records("summary_by_run")
        comparison = self.load_records("comparison")
        self.assertEqual(len(future_prices), 6)
        self.assertEqual(performance[0]["result_label"], "成功")
        self.assertAlmostEqual(float(performance[0]["return_t3_close_pct"]), 4.0)
        self.assertAlmostEqual(float(performance[0]["max_drawdown_3d_pct"]), -4.0)
        self.assertTrue(bool(performance[0]["hit_stop_loss"]))
        self.assertTrue(bool(performance[0]["hit_take_profit"]))
        self.assertEqual(summary[0]["run_id"], run_id)
        self.assertAlmostEqual(float(summary[0]["win_rate_t3"]), 100.0)
        self.assertEqual(comparison[0]["group_name"], "只观察")
        self.assertTrue((report_dir / f"report_{run_id}.md").exists())

    def test_latest_price_update_adds_latest_offset_and_updates_performance(self) -> None:
        run_id = "20260623_153000_v1_0"
        self.assertEqual(
            self.run_cli(
                "snapshot",
                "--scores",
                str(self.scores),
                "--candidates",
                str(self.candidates),
                "--run-id",
                run_id,
                "--selection-date",
                "2026-06-23",
                "--market-env",
                "震荡",
            ),
            0,
        )
        self.assertEqual(
            self.run_cli(
                "update-prices",
                "--run-id",
                run_id,
                "--price-file",
                str(self.prices),
                "--offsets",
                "0,1,2,3,5,10",
                "--latest",
            ),
            0,
        )
        self.assertEqual(self.run_cli("analyze", "--run-id", run_id), 0)

        future_prices = self.load_records("future_prices")
        performance = self.load_records("performance")
        offsets = {str(row["trading_day_offset"]) for row in future_prices}
        self.assertIn("T10", offsets)
        self.assertEqual(6, len(future_prices))
        self.assertEqual("2026-07-07", performance[0]["latest_price_date"])
        self.assertAlmostEqual(float(performance[0]["latest_price"]), 110.0)

    def test_auto_price_provider_falls_back_to_tencent(self) -> None:
        run_id = "20260623_153000_v1_0"
        self.assertEqual(
            self.run_cli(
                "snapshot",
                "--scores",
                str(self.scores),
                "--candidates",
                str(self.candidates),
                "--run-id",
                run_id,
                "--selection-date",
                "2026-06-23",
                "--market-env",
                "震荡",
            ),
            0,
        )
        tencent_records = [
            validation.PriceRecord(
                trade_date="2026-06-23",
                stock_code="300223.SZ",
                open=100.0,
                high=102.0,
                low=99.0,
                close=101.0,
                volume=None,
                amount=12000000.0,
                turnover_rate=None,
                is_suspended=False,
            )
        ]
        with (
            patch.object(validation, "fetch_akshare_prices", side_effect=RuntimeError("eastmoney unavailable")),
            patch.object(validation, "fetch_tencent_prices", return_value=tencent_records),
        ):
            self.assertEqual(
                self.run_cli("update-prices", "--run-id", run_id, "--offsets", "0", "--latest"),
                0,
            )

        future_prices = self.load_records("future_prices")
        self.assertEqual(1, len(future_prices))
        self.assertEqual("tencent.qfq_kline", future_prices[0]["data_source"])
        self.assertAlmostEqual(101.0, float(future_prices[0]["close"]))


if __name__ == "__main__":
    unittest.main()

