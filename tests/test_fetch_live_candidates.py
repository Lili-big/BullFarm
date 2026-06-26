from __future__ import annotations

import csv
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FETCH_SCRIPT = PROJECT_ROOT / "skills" / "stock-selection-agent" / "scripts" / "fetch_live_candidates.py"
SCORE_SCRIPT = PROJECT_ROOT / "skills" / "stock-selection-agent" / "scripts" / "score_candidates.py"


def load_fetch_module():
    spec = importlib.util.spec_from_file_location("fetch_live_candidates", FETCH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fetch_live_candidates = load_fetch_module()


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, payloads: dict[int, dict]) -> None:
        self.payloads = payloads
        self.trust_env = True
        self.headers: dict[str, str] = {}
        self.calls: list[dict] = []

    def get(self, url: str, params: dict, timeout: int) -> FakeResponse:
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        page = int(params["pn"])
        return FakeResponse(self.payloads[page])


class FailingEastmoneyClient:
    def fetch_a_spot(self) -> pd.DataFrame:
        raise RuntimeError("direct failed")


class AkshareSpotStub:
    def stock_sh_a_spot_em(self) -> pd.DataFrame:
        return pd.DataFrame()

    def stock_sz_a_spot_em(self) -> pd.DataFrame:
        return pd.DataFrame()

    def stock_bj_a_spot_em(self) -> pd.DataFrame:
        return pd.DataFrame()

    def stock_zh_a_spot(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "代码": "300001",
                    "名称": "测试科技",
                    "最新价": 20.0,
                    "成交额": 700_000_000,
                    "涨跌幅": 3.2,
                }
            ]
        )


class AkshareHistoryFallbackStub:
    def __init__(self) -> None:
        self.daily_calls: list[dict[str, str]] = []

    def stock_zh_a_hist(self, **kwargs: str) -> pd.DataFrame:
        raise RuntimeError("eastmoney history failed")

    def stock_zh_a_daily(self, **kwargs: str) -> pd.DataFrame:
        self.daily_calls.append(dict(kwargs))
        return make_history(90)


def make_history(days: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=days, freq="B")
    base = pd.Series([10 + idx * 0.08 for idx in range(days)], dtype="float64")
    amount = pd.Series([900_000_000 + idx * 4_000_000 for idx in range(days)], dtype="float64")
    return pd.DataFrame(
        {
            "date": dates,
            "open": base * 0.99,
            "close": base,
            "high": base * 1.02,
            "low": base * 0.98,
            "amount": amount,
        }
    )


class FetchLiveCandidatesTests(unittest.TestCase):
    def make_meta(self) -> fetch_live_candidates.FetchMeta:
        return fetch_live_candidates.FetchMeta(
            generated_at="2026-06-23T13:00:00",
            source="akshare",
            mode="prefilter",
            snapshot_session="intraday",
            requested_top=5,
            max_history=40,
            workers=1,
        )

    def test_eastmoney_client_does_not_change_environment_proxy(self) -> None:
        old_http = os.environ.get("HTTP_PROXY")
        os.environ["HTTP_PROXY"] = "http://127.0.0.1:9999"
        try:
            session = FakeSession({1: {"rc": 0, "data": {"total": 0, "diff": []}}})
            client = fetch_live_candidates.EastmoneyClient(session=session)

            self.assertFalse(client.session.trust_env)
            self.assertEqual("http://127.0.0.1:9999", os.environ["HTTP_PROXY"])
        finally:
            if old_http is None:
                os.environ.pop("HTTP_PROXY", None)
            else:
                os.environ["HTTP_PROXY"] = old_http

    def test_eastmoney_pagination_and_field_mapping(self) -> None:
        payloads = {
            1: {
                "rc": 0,
                "data": {
                    "total": 2,
                    "diff": [
                        {"f12": "300001", "f14": "测试科技", "f2": 20.0, "f3": 3.2, "f6": 700_000_000, "f24": 12.5}
                    ],
                },
            },
            2: {
                "rc": 0,
                "data": {
                    "total": 2,
                    "diff": [
                        {"f12": "600002", "f14": "测试电力", "f2": 10.0, "f3": 1.2, "f6": 500_000_000, "f24": 8.5}
                    ],
                },
            },
        }
        client = fetch_live_candidates.EastmoneyClient(page_size=1, session=FakeSession(payloads))

        spot = client.fetch_a_spot()

        self.assertEqual(["300001", "600002"], spot["代码"].tolist())
        self.assertEqual(["测试科技", "测试电力"], spot["名称"].tolist())
        self.assertEqual([1, 2], [call["params"]["pn"] for call in client.session.calls])
        self.assertEqual(2, client.stats["pages_ok"])

    def test_eastmoney_board_and_cons_mapping(self) -> None:
        board_client = fetch_live_candidates.EastmoneyClient(
            session=FakeSession(
                {
                    1: {
                        "rc": 0,
                        "data": {
                            "total": 1,
                            "diff": [{"f12": "BK0001", "f14": "AI应用", "f2": 1000, "f3": 2.5, "f104": 8, "f105": 2}],
                        },
                    }
                }
            )
        )
        cons_client = fetch_live_candidates.EastmoneyClient(
            session=FakeSession(
                {
                    1: {
                        "rc": 0,
                        "data": {
                            "total": 1,
                            "diff": [{"f12": "300001", "f14": "测试科技", "f2": 20.0, "f3": 6.0, "f6": 800_000_000}],
                        },
                    }
                }
            )
        )

        boards = board_client.fetch_industry_boards()
        cons = cons_client.fetch_industry_cons("BK0001")

        self.assertEqual("AI应用", boards.iloc[0]["板块名称"])
        self.assertEqual("BK0001", boards.iloc[0]["板块代码"])
        self.assertEqual("300001", cons.iloc[0]["代码"])
        self.assertEqual("测试科技", cons.iloc[0]["名称"])

    def test_parser_accepts_tencent_provider_alias(self) -> None:
        parser = fetch_live_candidates.build_parser()
        args = parser.parse_args(["--provider", "tencent_range", "--quote-batch-size", "300", "--include-bj"])

        self.assertEqual("tencent_range", args.source)
        self.assertEqual(300, args.quote_batch_size)
        self.assertTrue(args.include_bj)

    def test_tencent_quote_symbols_exclude_bj_by_default(self) -> None:
        default_symbols = fetch_live_candidates.iter_tencent_quote_symbols()
        expanded_symbols = fetch_live_candidates.iter_tencent_quote_symbols(include_bj=True)

        self.assertEqual(13_999, len(default_symbols))
        self.assertEqual(53_999, len(expanded_symbols))
        self.assertIn("sh600000", default_symbols)
        self.assertNotIn("bj430000", default_symbols)
        self.assertIn("bj430000", expanded_symbols)

    def test_tencent_history_builder_merges_worker_stats(self) -> None:
        meta = self.make_meta()
        stats = {"history_requests": 0, "history_ok": 0, "history_failed": 0}
        records = [
            (0, {"symbol": "300001", "name": "A"}),
            (1, {"symbol": "300002", "name": "B"}),
            (2, {"symbol": "600003", "name": "C"}),
        ]

        def fake_builder(idx, record, *_args):
            return {"symbol": record["symbol"], "name": record["name"]}, None, {
                "history_requests": 1,
                "history_ok": 1,
                "history_failed": 0,
            }, []

        with patch.object(fetch_live_candidates, "build_tencent_candidate_row_from_record", side_effect=fake_builder):
            rows = fetch_live_candidates.build_tencent_candidate_rows_concurrently(
                records,
                "20260625",
                70,
                3,
                2,
                {},
                {},
                meta,
                stats,
            )

        self.assertEqual(["300001", "300002", "600003"], [row["symbol"] for row in rows])
        self.assertEqual(3, stats["history_requests"])
        self.assertEqual(3, stats["history_ok"])
        self.assertEqual(0, stats["history_failed"])
        self.assertIn("history_elapsed_seconds", stats)

    def test_tencent_quote_parser_maps_fields_to_spot_contract(self) -> None:
        fields = [""] * 58
        fields[1] = "Sample Tech"
        fields[2] = "300001"
        fields[3] = "20.5"
        fields[32] = "3.2"
        fields[57] = "70000"
        text = 'v_sz300001="' + "~".join(fields) + '";'

        rows = fetch_live_candidates.parse_tencent_quote_text(text)

        self.assertEqual(1, len(rows))
        self.assertEqual("300001", rows[0]["symbol"])
        self.assertEqual("Sample Tech", rows[0]["name"])
        self.assertEqual(20.5, rows[0]["close"])
        self.assertEqual(700_000_000, rows[0]["amount"])
        self.assertEqual("SZ", rows[0]["_market"])

    def test_tencent_qfq_payload_normalizes_to_daily_history(self) -> None:
        payload = {
            "data": {
                "sz300001": {
                    "qfqday": [
                        ["2026-06-22", "10", "11", "12", "9", "1000", "", "", "12000000"],
                        ["2026-06-23", "11", "12", "13", "10", "1100", "", "", "13000000"],
                        ["2026-06-24", "12", "13", "14", "11", "1200", "", "", "14000000"],
                    ]
                }
            }
        }

        history = fetch_live_candidates.normalize_tencent_kline_payload(payload, "sz300001", "20260623")

        self.assertEqual(2, len(history))
        self.assertEqual(12.0, history.iloc[-1]["close"])
        self.assertEqual(13_000_000, history.iloc[-1]["amount"])

    def test_direct_spot_failure_falls_back_to_sina_without_env_change(self) -> None:
        meta = self.make_meta()
        meta.network_policy = {"fallbacks": []}

        spot = fetch_live_candidates.fetch_spot_market(
            AkshareSpotStub(),
            meta,
            FailingEastmoneyClient(),
            "auto",
        )

        self.assertEqual(["300001"], spot["symbol"].tolist())
        self.assertEqual("sina_fallback", meta.network_policy["spot_route"])
        self.assertEqual("spot", meta.network_policy["fallbacks"][0]["stage"])

    def test_prefilter_keeps_only_valid_liquid_positive_60d_names(self) -> None:
        spot = pd.DataFrame(
            [
                {"symbol": "300001", "name": "测试科技", "close": 20.0, "amount": 700_000_000, "pct60": 20},
                {"symbol": "600002", "name": "*ST测试", "close": 5.0, "amount": 900_000_000, "pct60": 50},
                {"symbol": "000003", "name": "低量股份", "close": 6.0, "amount": 100_000_000, "pct60": 40},
                {"symbol": "000004", "name": "弱势股份", "close": 7.0, "amount": 800_000_000, "pct60": -1},
            ]
        )

        result = fetch_live_candidates.prefilter_spot(spot, max_history=10, min_amount_billion=0.5)

        self.assertEqual(["300001"], result["symbol"].tolist())

    def test_build_candidate_row_matches_scoring_contract(self) -> None:
        row = fetch_live_candidates.build_candidate_row(
            {"symbol": "300001", "name": "测试科技", "is_st": False},
            make_history(),
            {
                "sector": "AI应用",
                "sector_strength_vs_index_3d_pct": 2.5,
                "sector_amount_expanding": True,
                "sector_rank_percentile": 10,
                "sector_leaders_count": 3,
                "sector_frontline": True,
            },
            {
                "index_above_ma5_ma10": True,
                "amount_expanding": True,
                "limit_up_premium_good": True,
                "limit_down_risk_low": True,
            },
        )

        self.assertEqual(fetch_live_candidates.CANDIDATE_FIELDS, list(row.keys()))
        self.assertEqual("300001", row["symbol"])
        self.assertEqual("测试科技", row["name"])
        self.assertEqual("AI应用", row["sector"])
        self.assertEqual("true", row["market_index_above_ma5_ma10"])

    def test_history_fetch_falls_back_to_sina_daily(self) -> None:
        meta = self.make_meta()
        meta.network_policy = {"fallbacks": []}
        ak = AkshareHistoryFallbackStub()

        history = fetch_live_candidates.fetch_stock_history(
            ak,
            "603986",
            "20260623",
            80,
            meta,
        )

        self.assertEqual(80, len(history))
        self.assertEqual("sh603986", ak.daily_calls[0]["symbol"])
        self.assertEqual("history", meta.network_policy["fallbacks"][0]["stage"])
        self.assertEqual("stock_zh_a_daily", meta.network_policy["fallbacks"][0]["to"])
        self.assertEqual("stock_zh_a_hist:603986", meta.api_errors[0]["endpoint"])

    def test_snapshot_path_uses_timestamp_when_same_day_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            existing = output_dir / "20260623_candidates.csv"
            existing.write_text("", encoding="utf-8")

            resolved = fetch_live_candidates.resolve_output_path(
                output_dir,
                datetime(2026, 6, 23, 13, 5, 7),
                overwrite=False,
            )

            self.assertEqual("20260623_130507_candidates.csv", resolved.name)

    def test_generated_csv_can_be_scored_by_existing_scorer(self) -> None:
        candidate = fetch_live_candidates.build_candidate_row(
            {"symbol": "300001", "name": "测试科技", "is_st": False},
            make_history(),
            {
                "sector": "AI应用",
                "sector_strength_vs_index_3d_pct": 2.5,
                "sector_amount_expanding": True,
                "sector_rank_percentile": 10,
                "sector_leaders_count": 3,
                "sector_frontline": True,
            },
            {
                "index_above_ma5_ma10": True,
                "amount_expanding": True,
                "limit_up_premium_good": True,
                "limit_down_risk_low": True,
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_csv = tmp_path / "candidates.csv"
            report = tmp_path / "report.md"
            scores = tmp_path / "scores.csv"
            with input_csv.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fetch_live_candidates.CANDIDATE_FIELDS)
                writer.writeheader()
                writer.writerow(candidate)

            subprocess.run(
                [
                    sys.executable,
                    str(SCORE_SCRIPT),
                    "--input",
                    str(input_csv),
                    "--config",
                    str(PROJECT_ROOT / "config" / "scoring_rules.json"),
                    "--output",
                    str(report),
                    "--csv-output",
                    str(scores),
                ],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertTrue(report.exists())
            self.assertTrue(scores.exists())
            with scores.open(encoding="utf-8-sig") as handle:
                scored_rows = list(csv.DictReader(handle))
            self.assertEqual("300001", scored_rows[0]["symbol"])


if __name__ == "__main__":
    unittest.main()
