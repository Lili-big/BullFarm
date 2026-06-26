from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests


CANDIDATE_FIELDS = [
    "symbol",
    "name",
    "sector",
    "is_st",
    "close",
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "ma5_slope_pct",
    "ma20_slope_pct",
    "ma60_slope_pct",
    "avg_amount_20d_billion",
    "above_mid_platform",
    "platform_breakout",
    "trend_pullback",
    "strong_consolidation_restart",
    "downtrend_rebound",
    "recent5_low_rising",
    "recent5_gain_pct",
    "volume_breakout",
    "volume_pullback_shrink",
    "has_volume_bullish_day",
    "upper_shadow_ratio",
    "sector_strength_vs_index_3d_pct",
    "sector_amount_expanding",
    "sector_rank_percentile",
    "sector_leaders_count",
    "sector_frontline",
    "market_index_above_ma5_ma10",
    "market_amount_expanding",
    "market_limit_up_premium_good",
    "market_limit_down_risk_low",
]

SPOT_FUNCTIONS = [
    ("stock_sh_a_spot_em", "SH"),
    ("stock_sz_a_spot_em", "SZ"),
    ("stock_bj_a_spot_em", "BJ"),
]

EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"
EASTMONEY_STOCK_FIELDS = (
    "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,"
    "f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152"
)
EASTMONEY_BOARD_FIELDS = (
    "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,"
    "f23,f24,f25,f26,f22,f33,f11,f62,f128,f136,f115,f152,f124,f107,f104,"
    "f105,f140,f141,f207,f208,f209,f222"
)
EASTMONEY_CONS_FIELDS = (
    "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,"
    "f23,f25,f22,f11,f62,f128,f136,f115,f152,f45"
)

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={symbols}"
TENCENT_QFQ_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_BATCH_SIZE = 800
TENCENT_COMMON_CODE_RANGES = (
    ("sz", 1, 3999),
    ("sz", 300000, 301999),
    ("sh", 600000, 605999),
    ("sh", 688000, 689999),
)
TENCENT_BJ_CODE_RANGES = (
    ("bj", 430000, 439999),
    ("bj", 830000, 839999),
    ("bj", 870000, 879999),
    ("bj", 920000, 929999),
)
TENCENT_CODE_RANGES = TENCENT_COMMON_CODE_RANGES


@dataclass
class FetchMeta:
    generated_at: str
    source: str
    mode: str
    snapshot_session: str
    requested_top: int
    max_history: int
    workers: int
    output_csv: str = ""
    total_spot_rows: int = 0
    prefiltered_rows: int = 0
    written_rows: int = 0
    skipped: list[dict[str, str]] = field(default_factory=list)
    api_errors: list[dict[str, str]] = field(default_factory=list)
    market: dict[str, Any] = field(default_factory=dict)
    network_policy: dict[str, Any] = field(default_factory=dict)

    def add_error(self, endpoint: str, exc: Exception) -> None:
        self.api_errors.append({"endpoint": endpoint, "error": f"{type(exc).__name__}: {exc}"})

    def skip(self, symbol: str, name: str, reason: str) -> None:
        self.skipped.append({"symbol": symbol, "name": name, "reason": reason})


class EastmoneyClientError(RuntimeError):
    pass


class EastmoneyClient:
    def __init__(
        self,
        page_size: int = 50,
        retries: int = 3,
        timeout: int = 20,
        session: requests.Session | None = None,
    ) -> None:
        self.page_size = page_size
        self.retries = retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://quote.eastmoney.com/",
                "Connection": "close",
            }
        )
        self.stats: dict[str, Any] = {
            "eastmoney_route": "direct_session",
            "trust_env": self.session.trust_env,
            "headers": "browser_like",
            "page_size": page_size,
            "retries": retries,
            "timeout": timeout,
            "requests": 0,
            "pages_ok": 0,
            "pages_failed": 0,
            "endpoints": {},
        }

    def fetch_a_spot(self) -> pd.DataFrame:
        params = self._base_params(
            fid="f12",
            fs="m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            fields=EASTMONEY_STOCK_FIELDS,
        )
        raw = self._fetch_paginated(
            "stock_spot",
            "https://82.push2.eastmoney.com/api/qt/clist/get",
            params,
        )
        return self._map_stock_spot(raw)

    def fetch_industry_boards(self) -> pd.DataFrame:
        params = self._base_params(
            fid="f3",
            fs="m:90 t:2 f:!50",
            fields=EASTMONEY_BOARD_FIELDS,
        )
        raw = self._fetch_paginated(
            "industry_boards",
            "https://17.push2.eastmoney.com/api/qt/clist/get",
            params,
        )
        return self._map_industry_boards(raw)

    def fetch_industry_cons(self, board_code: str) -> pd.DataFrame:
        params = self._base_params(
            fid="f3",
            fs=f"b:{board_code} f:!50",
            fields=EASTMONEY_CONS_FIELDS,
        )
        raw = self._fetch_paginated(
            f"industry_cons:{board_code}",
            "https://29.push2.eastmoney.com/api/qt/clist/get",
            params,
        )
        return self._map_industry_cons(raw)

    def _base_params(self, fid: str, fs: str, fields: str) -> dict[str, Any]:
        return {
            "pn": 1,
            "pz": self.page_size,
            "po": 1,
            "np": 1,
            "ut": EASTMONEY_UT,
            "fltt": 2,
            "invt": 2,
            "fid": fid,
            "fs": fs,
            "fields": fields,
        }

    def _fetch_paginated(self, endpoint: str, url: str, base_params: dict[str, Any]) -> pd.DataFrame:
        first_json = self._request_json(endpoint, url, {**base_params, "pn": 1})
        data = first_json.get("data") or {}
        first_diff = data.get("diff") or []
        total = int(data.get("total") or len(first_diff))
        if not first_diff:
            return pd.DataFrame()

        frames = [pd.DataFrame(first_diff)]
        total_pages = max(1, math.ceil(total / max(1, len(first_diff))))
        for page in range(2, total_pages + 1):
            page_json = self._request_json(endpoint, url, {**base_params, "pn": page})
            page_data = page_json.get("data") or {}
            frames.append(pd.DataFrame(page_data.get("diff") or []))
        result = pd.concat(frames, ignore_index=True)
        if "f3" in result.columns:
            result["f3"] = pd.to_numeric(result["f3"], errors="coerce")
            result.sort_values(by=["f3"], ascending=False, inplace=True, ignore_index=True)
        result.reset_index(drop=True, inplace=True)
        result.insert(0, "index", result.index + 1)
        return result

    def _request_json(self, endpoint: str, url: str, params: dict[str, Any]) -> dict[str, Any]:
        endpoint_stats = self.stats["endpoints"].setdefault(
            endpoint,
            {"pages_ok": 0, "pages_failed": 0, "last_error": ""},
        )
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.stats["requests"] += 1
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                if payload.get("rc") not in {0, None}:
                    raise EastmoneyClientError(f"Eastmoney rc={payload.get('rc')}: {payload}")
                self.stats["pages_ok"] += 1
                endpoint_stats["pages_ok"] += 1
                return payload
            except Exception as exc:
                last_error = exc
                endpoint_stats["last_error"] = f"{type(exc).__name__}: {exc}"
                if attempt < self.retries:
                    time.sleep(0.4 * attempt)
        self.stats["pages_failed"] += 1
        endpoint_stats["pages_failed"] += 1
        raise EastmoneyClientError(f"{endpoint} failed after {self.retries} attempts: {last_error}")

    @staticmethod
    def _map_stock_spot(raw: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "序号": raw.get("index"),
                "代码": raw.get("f12"),
                "名称": raw.get("f14"),
                "最新价": pd.to_numeric(raw.get("f2"), errors="coerce"),
                "涨跌幅": pd.to_numeric(raw.get("f3"), errors="coerce"),
                "成交额": pd.to_numeric(raw.get("f6"), errors="coerce"),
                "60日涨跌幅": pd.to_numeric(raw.get("f24"), errors="coerce"),
            }
        )

    @staticmethod
    def _map_industry_boards(raw: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "排名": raw.get("index"),
                "板块名称": raw.get("f14"),
                "板块代码": raw.get("f12"),
                "最新价": pd.to_numeric(raw.get("f2"), errors="coerce"),
                "涨跌幅": pd.to_numeric(raw.get("f3"), errors="coerce"),
                "上涨家数": pd.to_numeric(raw.get("f104"), errors="coerce"),
                "下跌家数": pd.to_numeric(raw.get("f105"), errors="coerce"),
            }
        )

    @staticmethod
    def _map_industry_cons(raw: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "序号": raw.get("index"),
                "代码": raw.get("f12"),
                "名称": raw.get("f14"),
                "最新价": pd.to_numeric(raw.get("f2"), errors="coerce"),
                "涨跌幅": pd.to_numeric(raw.get("f3"), errors="coerce"),
                "成交额": pd.to_numeric(raw.get("f6"), errors="coerce"),
            }
        )


def import_akshare() -> Any:
    try:
        return importlib.import_module("akshare")
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: akshare. Install project dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc


class TencentClientError(RuntimeError):
    pass


class TencentClient:
    def __init__(
        self,
        batch_size: int = TENCENT_BATCH_SIZE,
        retries: int = 3,
        timeout: int = 20,
        session: requests.Session | None = None,
    ) -> None:
        self.batch_size = batch_size
        self.retries = retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/javascript,*/*",
                "Referer": "https://gu.qq.com/",
                "Connection": "close",
            }
        )
        self.stats: dict[str, Any] = {
            "tencent_route": "direct_session",
            "trust_env": self.session.trust_env,
            "headers": "browser_like",
            "batch_size": batch_size,
            "retries": retries,
            "timeout": timeout,
            "quote_batches": 0,
            "quote_rows": 0,
            "history_requests": 0,
            "history_ok": 0,
            "history_failed": 0,
        }

    def fetch_a_spot(self, include_bj: bool = False) -> pd.DataFrame:
        started = time.monotonic()
        symbols = iter_tencent_quote_symbols(include_bj=include_bj)
        self.stats["quote_symbol_count"] = len(symbols)
        self.stats["quote_scope"] = "common_sh_sz_plus_bj" if include_bj else "common_sh_sz"
        self.stats["include_bj"] = include_bj
        records: list[dict[str, Any]] = []
        try:
            for batch in batched(symbols, self.batch_size):
                text = self._request_text(
                    "quote",
                    TENCENT_QUOTE_URL.format(symbols=",".join(batch)),
                )
                self.stats["quote_batches"] += 1
                for item in parse_tencent_quote_text(text):
                    if item:
                        records.append(item)
        finally:
            self.stats["quote_elapsed_seconds"] = round(time.monotonic() - started, 3)
        self.stats["quote_rows"] = len(records)
        if not records:
            return pd.DataFrame()
        return pd.DataFrame(records)

    def fetch_qfq_history(self, symbol: str, end_date: str, history_days: int) -> pd.DataFrame:
        market_symbol = tencent_symbol(symbol)
        params = {"param": f"{market_symbol},day,,,{max(1, history_days)},qfq"}
        self.stats["history_requests"] += 1
        try:
            payload = self._request_json("qfq_kline", TENCENT_QFQ_KLINE_URL, params=params)
            frame = normalize_tencent_kline_payload(payload, market_symbol, end_date)
        except Exception:
            self.stats["history_failed"] += 1
            raise
        self.stats["history_ok"] += 1
        return frame.tail(history_days)

    def _request_text(self, endpoint: str, url: str, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                if not response.encoding:
                    response.encoding = "gbk"
                return response.text
            except Exception as exc:  # pragma: no cover - exercised by live APIs
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2.0, 0.4 * attempt))
        raise TencentClientError(f"{endpoint} failed after {self.retries} attempts: {last_error}")

    def _request_json(self, endpoint: str, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # pragma: no cover - exercised by live APIs
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2.0, 0.4 * attempt))
        raise TencentClientError(f"{endpoint} failed after {self.retries} attempts: {last_error}")


def normalize_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    return digits[-6:].zfill(6)


def batched(items: list[str], size: int) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), max(1, size))]


def iter_tencent_quote_symbols(include_bj: bool = False) -> list[str]:
    symbols: list[str] = []
    ranges = list(TENCENT_COMMON_CODE_RANGES)
    if include_bj:
        ranges.extend(TENCENT_BJ_CODE_RANGES)
    for market, start, end in ranges:
        for code in range(start, end + 1):
            symbols.append(f"{market}{code:06d}")
    return symbols


def tencent_market_for_code(code: str) -> str:
    normalized = normalize_code(code)
    if normalized.startswith(("60", "68", "90")):
        return "sh"
    if normalized.startswith(("43", "83", "87", "88", "92")):
        return "bj"
    return "sz"


def tencent_symbol(code: str) -> str:
    normalized = normalize_code(code)
    return f"{tencent_market_for_code(normalized)}{normalized}"


def first_tencent_number(fields: list[str], indexes: list[int]) -> float:
    for index in indexes:
        if index < len(fields):
            value = to_float(fields[index])
            if finite(value):
                return value
    return math.nan


def parse_tencent_quote_record(raw: str) -> dict[str, Any] | None:
    if "=" not in raw:
        return None
    prefix, payload = raw.split("=", 1)
    symbol_hint = prefix.split("_")[-1].strip()
    fields = payload.strip().strip('";').split("~")
    if len(fields) < 4:
        return None
    code = normalize_code(fields[2] if len(fields) > 2 else symbol_hint)
    name = fields[1].strip() if len(fields) > 1 else ""
    close = to_float(fields[3] if len(fields) > 3 else math.nan)
    if not code or not name or not finite(close) or close <= 0:
        return None
    amount_base = first_tencent_number(fields, [57, 37, 36])
    amount = amount_base * 10_000 if finite(amount_base) else math.nan
    pct_chg = first_tencent_number(fields, [32, 31])
    return {
        "symbol": code,
        "name": name,
        "close": close,
        "amount": amount,
        "pct_chg": pct_chg,
        "pct60": math.nan,
        "_market": tencent_market_for_code(code).upper(),
    }


def parse_tencent_quote_text(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for part in text.split(";"):
        parsed = parse_tencent_quote_record(part.strip())
        if parsed:
            records.append(parsed)
    return records


def normalize_tencent_kline_payload(payload: dict[str, Any], market_symbol: str, end_date: str) -> pd.DataFrame:
    data = (payload.get("data") or {}).get(market_symbol) or {}
    rows = data.get("qfqday") or data.get("day") or []
    normalized_rows: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, list) or len(item) < 5:
            continue
        close = to_float(item[2])
        volume = to_float(item[5] if len(item) > 5 else math.nan)
        amount = to_float(item[8] if len(item) > 8 else math.nan)
        if not finite(amount) and finite(volume) and finite(close):
            amount = volume * close * 100
        normalized_rows.append(
            {
                "date": item[0],
                "open": item[1],
                "close": item[2],
                "high": item[3],
                "low": item[4],
                "amount": amount,
            }
        )
    frame = normalize_daily_history(pd.DataFrame(normalized_rows))
    if frame.empty:
        return frame
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    return frame[frame["date"] <= end_dt].reset_index(drop=True)


def tencent_sector_name(symbol: str) -> str:
    code = normalize_code(symbol)
    if code.startswith("688"):
        return "科创板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("43", "83", "87", "88", "92")):
        return "北交所"
    if code.startswith(("60", "68", "90")):
        return "沪市主板"
    return "深市主板"


def to_float(value: Any, default: float = math.nan) -> float:
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    text = str(value).replace(",", "").replace("%", "").strip()
    if text in {"", "-", "--", "nan", "None", "无"}:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def finite(value: float | None) -> bool:
    return value is not None and not math.isnan(value) and not math.isinf(value)


def fmt_float(value: float | None, digits: int = 2) -> str:
    if not finite(value):
        return ""
    return f"{float(value):.{digits}f}"


def bool_value(value: bool) -> str:
    return "true" if value else "false"


def first_existing(columns: list[str], aliases: list[str]) -> str | None:
    for alias in aliases:
        if alias in columns:
            return alias
    lowered = {col.lower(): col for col in columns}
    for alias in aliases:
        match = lowered.get(alias.lower())
        if match:
            return match
    return None


def series_from_alias(df: pd.DataFrame, aliases: list[str], default: Any = math.nan) -> pd.Series:
    column = first_existing(list(df.columns), aliases)
    if column is None:
        return pd.Series([default] * len(df), index=df.index)
    return df[column]


def record_network_fallback(meta: FetchMeta, stage: str, reason: str) -> None:
    meta.network_policy.setdefault("fallbacks", []).append({"stage": stage, "reason": reason})


def normalize_spot_frame(raw: pd.DataFrame) -> pd.DataFrame:
    normalized = pd.DataFrame()
    normalized["symbol"] = series_from_alias(raw, ["代码", "证券代码", "code", "symbol"]).map(normalize_code)
    normalized["name"] = series_from_alias(raw, ["名称", "证券简称", "name"], "").astype(str).str.strip()
    normalized["close"] = pd.to_numeric(series_from_alias(raw, ["最新价", "现价", "close", "最新"]), errors="coerce")
    normalized["amount"] = pd.to_numeric(series_from_alias(raw, ["成交额", "amount"]), errors="coerce")
    normalized["pct_chg"] = pd.to_numeric(series_from_alias(raw, ["涨跌幅", "pct_chg", "change_pct"]), errors="coerce")
    normalized["pct60"] = pd.to_numeric(series_from_alias(raw, ["60日涨跌幅", "60日涨跌", "pct60"]), errors="coerce")
    normalized["market"] = raw["_market"].astype(str)
    normalized = normalized.dropna(subset=["symbol", "close", "amount"])
    normalized = normalized[normalized["symbol"] != ""].drop_duplicates("symbol", keep="first")
    return normalized


def fetch_spot_market(
    ak: Any,
    meta: FetchMeta,
    eastmoney_client: EastmoneyClient | None,
    eastmoney_route: str,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    if eastmoney_route in {"auto", "direct"} and eastmoney_client is not None:
        try:
            frame = eastmoney_client.fetch_a_spot()
            if frame is not None and not frame.empty:
                frame = frame.copy()
                frame["_market"] = "EASTMONEY_DIRECT"
                frames.append(frame)
                meta.network_policy["spot_route"] = "eastmoney_direct"
        except Exception as exc:  # pragma: no cover - exercised by live APIs
            meta.add_error("eastmoney_direct:stock_spot", exc)
            record_network_fallback(meta, "spot", f"eastmoney_direct_failed:{type(exc).__name__}")
            if eastmoney_route == "direct":
                raise RuntimeError("Eastmoney direct spot fetch failed.") from exc

    if not frames and eastmoney_route in {"auto", "akshare"}:
        for function_name, market in SPOT_FUNCTIONS:
            try:
                fetcher = getattr(ak, function_name)
                frame = fetcher()
            except Exception as exc:  # pragma: no cover - exercised by live APIs
                meta.add_error(function_name, exc)
                continue
            if frame is None or frame.empty:
                continue
            frame = frame.copy()
            frame["_market"] = market
            frames.append(frame)
        if frames:
            meta.network_policy["spot_route"] = "akshare_eastmoney"

    if not frames and hasattr(ak, "stock_zh_a_spot"):
        try:
            frame = ak.stock_zh_a_spot()
            if frame is not None and not frame.empty:
                frame = frame.copy()
                frame["_market"] = "SINA"
                frames.append(frame)
                meta.network_policy["spot_route"] = "sina_fallback"
        except Exception as exc:  # pragma: no cover - exercised by live APIs
            meta.add_error("stock_zh_a_spot", exc)

    if not frames:
        raise RuntimeError("No spot market data returned from AKShare.")

    normalized = normalize_spot_frame(pd.concat(frames, ignore_index=True))
    meta.total_spot_rows = int(len(normalized))
    return normalized


def is_st_or_risk_name(name: Any) -> bool:
    text = str(name or "").upper()
    return "ST" in text or "退" in text


def prefilter_spot(spot: pd.DataFrame, max_history: int, min_amount_billion: float) -> pd.DataFrame:
    min_amount = min_amount_billion * 1_000_000_000
    filtered = spot.copy()
    if "pct60" not in filtered:
        filtered["pct60"] = math.nan
    if "pct_chg" not in filtered:
        filtered["pct_chg"] = 0.0
    filtered["is_st"] = filtered["name"].map(is_st_or_risk_name)
    filtered["_pct60_or_deferred"] = filtered["pct60"].isna() | (filtered["pct60"] >= 0)
    filtered["_strength_sort"] = filtered["pct60"].where(filtered["pct60"].notna(), filtered["pct_chg"].fillna(0))
    filtered = filtered[
        (~filtered["is_st"])
        & (filtered["close"] > 0)
        & (filtered["amount"] >= min_amount)
        & (filtered["_pct60_or_deferred"])
    ].copy()
    filtered = filtered.sort_values(["amount", "_strength_sort"], ascending=[False, False])
    return filtered.head(max_history).reset_index(drop=True)


def fetch_stock_history(
    ak: Any,
    symbol: str,
    end_date: str,
    history_days: int,
    meta: FetchMeta,
) -> pd.DataFrame:
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    start_dt = end_dt - timedelta(days=max(240, history_days * 2))
    try:
        raw = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=end_date,
            adjust="qfq",
        )
    except Exception as exc:  # pragma: no cover - exercised by live APIs
        meta.add_error(f"stock_zh_a_hist:{symbol}", exc)
        try:
            raw = ak.stock_zh_a_daily(
                symbol=sina_daily_symbol(symbol),
                start_date=start_dt.strftime("%Y%m%d"),
                end_date=end_date,
                adjust="qfq",
            )
            meta.network_policy.setdefault("fallbacks", []).append(
                {
                    "stage": "history",
                    "symbol": symbol,
                    "from": "stock_zh_a_hist",
                    "to": "stock_zh_a_daily",
                    "reason": type(exc).__name__,
                }
            )
        except Exception as fallback_exc:  # pragma: no cover - exercised by live APIs
            meta.add_error(f"stock_zh_a_daily:{symbol}", fallback_exc)
            raise
    return normalize_daily_history(raw).tail(history_days)


def sina_daily_symbol(symbol: str) -> str:
    code = normalize_code(symbol)
    if code.startswith(("60", "68", "90")):
        return f"sh{code}"
    if code.startswith(("43", "83", "87", "88", "92")):
        return f"bj{code}"
    return f"sz{code}"


def normalize_daily_history(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    data = pd.DataFrame()
    data["date"] = pd.to_datetime(series_from_alias(raw, ["日期", "date"]), errors="coerce")
    data["open"] = pd.to_numeric(series_from_alias(raw, ["开盘", "open"]), errors="coerce")
    data["close"] = pd.to_numeric(series_from_alias(raw, ["收盘", "close"]), errors="coerce")
    data["high"] = pd.to_numeric(series_from_alias(raw, ["最高", "high"]), errors="coerce")
    data["low"] = pd.to_numeric(series_from_alias(raw, ["最低", "low"]), errors="coerce")
    data["amount"] = pd.to_numeric(series_from_alias(raw, ["成交额", "amount"]), errors="coerce")
    data = data.dropna(subset=["date", "open", "close", "high", "low"]).sort_values("date")
    return data.reset_index(drop=True)


def rolling_ma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window, min_periods=window).mean()


def slope_pct(ma: pd.Series, lookback: int) -> float:
    if len(ma.dropna()) <= lookback:
        return math.nan
    current = ma.iloc[-1]
    previous = ma.iloc[-1 - lookback]
    if not finite(current) or not finite(previous) or previous == 0:
        return math.nan
    return (current / previous - 1) * 100


def pct_change_from(series: pd.Series, periods: int) -> float:
    if len(series) <= periods:
        return math.nan
    previous = series.iloc[-1 - periods]
    current = series.iloc[-1]
    if not finite(previous) or previous == 0:
        return math.nan
    return (current / previous - 1) * 100


def compute_recent5_low_rising(history: pd.DataFrame) -> bool:
    if len(history) < 5:
        return False
    lows = history["low"].tail(5).reset_index(drop=True)
    return bool(lows.iloc[-1] > lows.iloc[0] and lows.iloc[2:].min() >= lows.iloc[:3].min())


def compute_volume_pullback_shrink(history: pd.DataFrame) -> bool:
    if len(history) < 25 or "amount" not in history:
        return False
    recent = history.tail(5).copy()
    recent["prev_close"] = history["close"].shift(1).tail(5).values
    pullbacks = recent[recent["close"] < recent["prev_close"]]
    if pullbacks.empty:
        return False
    prior_amount = history["amount"].iloc[-25:-5].mean()
    if not finite(prior_amount) or prior_amount <= 0:
        return False
    return bool(pullbacks["amount"].mean() < prior_amount * 0.95)


def compute_volume_bullish_day(history: pd.DataFrame) -> bool:
    if len(history) < 25:
        return False
    recent = history.tail(5)
    prior_amount = history["amount"].iloc[-25:-5].mean()
    if not finite(prior_amount) or prior_amount <= 0:
        return False
    bullish = recent[(recent["close"] > recent["open"]) & (recent["amount"] >= prior_amount * 1.2)]
    return bool(not bullish.empty)


def compute_upper_shadow_ratio(last_row: pd.Series) -> float:
    close = to_float(last_row.get("close"))
    high = to_float(last_row.get("high"))
    open_price = to_float(last_row.get("open"))
    if not finite(close) or close <= 0 or not finite(high) or not finite(open_price):
        return math.nan
    return max(0.0, high - max(open_price, close)) / close


def compute_structure_flags(
    history: pd.DataFrame,
    ma5: float,
    ma10: float,
    ma20: float,
    ma60: float,
    ma20_slope: float,
    ma60_slope: float,
    recent5_gain: float,
    volume_bullish_day: bool,
    volume_pullback_shrink: bool,
    upper_shadow_ratio: float,
) -> dict[str, bool]:
    if len(history) < 65:
        return {
            "above_mid_platform": False,
            "platform_breakout": False,
            "trend_pullback": False,
            "strong_consolidation_restart": False,
            "downtrend_rebound": False,
        }

    last = history.iloc[-1]
    close = float(last["close"])
    amount = to_float(last.get("amount"))
    avg20_amount = history["amount"].tail(20).mean()
    prior20_high = history["high"].iloc[-21:-1].max()

    above_mid_platform = finite(ma20) and close > ma20
    platform_breakout = (
        above_mid_platform
        and finite(prior20_high)
        and close >= prior20_high * 0.995
        and finite(amount)
        and finite(avg20_amount)
        and amount >= avg20_amount * 1.1
    )
    trend_pullback = (
        finite(ma20)
        and finite(ma60)
        and finite(ma20_slope)
        and close >= ma20
        and close <= ma20 * 1.06
        and ma20 > ma60
        and ma20_slope > 0
        and -3 <= (recent5_gain if finite(recent5_gain) else 0) <= 12
        and volume_pullback_shrink
    )
    strong_consolidation_restart = (
        finite(ma5)
        and finite(ma20)
        and finite(ma60)
        and close > ma5 > ma20 > ma60
        and volume_bullish_day
        and finite(recent5_gain)
        and 3 <= recent5_gain <= 20
        and (not finite(upper_shadow_ratio) or upper_shadow_ratio <= 0.05)
    )
    downtrend_rebound = (
        finite(ma60)
        and close < ma60
        and finite(ma20_slope)
        and finite(ma60_slope)
        and ma20_slope < 0
        and ma60_slope < 0
    )
    return {
        "above_mid_platform": bool(above_mid_platform),
        "platform_breakout": bool(platform_breakout),
        "trend_pullback": bool(trend_pullback),
        "strong_consolidation_restart": bool(strong_consolidation_restart),
        "downtrend_rebound": bool(downtrend_rebound),
    }


def normalize_board_name_row(board: pd.Series) -> str:
    for key in ["板块名称", "名称", "行业名称"]:
        if key in board and str(board[key]).strip():
            return str(board[key]).strip()
    return ""


def build_market_info(ak: Any, spot: pd.DataFrame, end_date: str, meta: FetchMeta) -> dict[str, Any]:
    info = {
        "index_pct3": 0.0,
        "index_above_ma5_ma10": False,
        "amount_expanding": False,
        "limit_up_premium_good": False,
        "limit_down_risk_low": False,
    }
    try:
        raw_index = ak.stock_zh_index_daily_em(symbol="sh000001")
        index_history = normalize_daily_history(raw_index)
        if len(index_history) >= 25:
            close = index_history["close"]
            ma5 = rolling_ma(close, 5).iloc[-1]
            ma10 = rolling_ma(close, 10).iloc[-1]
            latest_close = close.iloc[-1]
            info["index_pct3"] = pct_change_from(close, 3)
            info["index_above_ma5_ma10"] = bool(latest_close > ma5 and latest_close > ma10)
            recent_amount = index_history["amount"].tail(3).mean()
            prior_amount = index_history["amount"].iloc[-23:-3].mean()
            info["amount_expanding"] = bool(finite(recent_amount) and finite(prior_amount) and recent_amount > prior_amount)
    except Exception as exc:  # pragma: no cover - exercised by live APIs
        meta.add_error("stock_zh_index_daily_em:sh000001", exc)

    info["limit_up_premium_good"] = compute_limit_up_premium(ak, spot, end_date, meta)
    down_ratio = float((spot["pct_chg"].fillna(0) <= -7).mean()) if len(spot) else 1.0
    limit_down_count = int((spot["pct_chg"].fillna(0) <= -9.5).sum()) if len(spot) else 9999
    info["limit_down_risk_low"] = bool(down_ratio <= 0.02 and limit_down_count <= 100)
    meta.market = {
        "index_pct3": fmt_float(info["index_pct3"], 2),
        "index_above_ma5_ma10": info["index_above_ma5_ma10"],
        "amount_expanding": info["amount_expanding"],
        "limit_up_premium_good": info["limit_up_premium_good"],
        "limit_down_risk_low": info["limit_down_risk_low"],
        "large_drop_ratio": fmt_float(down_ratio, 4),
        "limit_down_count": limit_down_count,
    }
    return info


def compute_limit_up_premium(ak: Any, spot: pd.DataFrame, end_date: str, meta: FetchMeta) -> bool:
    try:
        if hasattr(ak, "stock_zt_pool_previous_em"):
            pool = ak.stock_zt_pool_previous_em(date=end_date)
        else:
            pool = ak.stock_zt_pool_em(date=end_date)
    except Exception as exc:  # pragma: no cover - exercised by live APIs
        meta.add_error("stock_zt_pool_previous_em", exc)
        return False
    if pool is None or pool.empty:
        return False
    codes = series_from_alias(pool, ["代码", "证券代码", "code", "symbol"]).map(normalize_code)
    current = spot[spot["symbol"].isin(set(codes))]["pct_chg"].dropna()
    if current.empty:
        return False
    return bool(current.median() > 1.0 and (current > 0).mean() >= 0.5)


def fetch_sector_history(
    ak: Any,
    sector_name: str,
    end_date: str,
    index_pct3: float,
    meta: FetchMeta,
) -> tuple[float, bool]:
    try:
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        start_date = (end_dt - timedelta(days=80)).strftime("%Y%m%d")
        raw = ak.stock_board_industry_hist_em(
            symbol=sector_name,
            start_date=start_date,
            end_date=end_date,
            period="daily",
            adjust="",
        )
        history = normalize_daily_history(raw)
    except Exception as exc:  # pragma: no cover - exercised by live APIs
        meta.add_error(f"stock_board_industry_hist_em:{sector_name}", exc)
        return math.nan, False

    if len(history) < 25:
        return math.nan, False
    sector_pct3 = pct_change_from(history["close"], 3)
    recent_amount = history["amount"].tail(3).mean()
    prior_amount = history["amount"].iloc[-23:-3].mean()
    amount_expanding = bool(finite(recent_amount) and finite(prior_amount) and recent_amount > prior_amount)
    strength = sector_pct3 - (index_pct3 if finite(index_pct3) else 0.0)
    return strength, amount_expanding


def build_sector_model(
    ak: Any,
    candidate_symbols: set[str],
    end_date: str,
    index_pct3: float,
    meta: FetchMeta,
    eastmoney_client: EastmoneyClient | None,
    eastmoney_route: str,
) -> dict[str, dict[str, Any]]:
    if not candidate_symbols:
        return {}

    if eastmoney_route in {"auto", "direct"} and eastmoney_client is not None:
        try:
            model = build_eastmoney_direct_sector_model(
                ak,
                eastmoney_client,
                candidate_symbols,
                end_date,
                index_pct3,
                meta,
            )
            if model:
                meta.network_policy["sector_route"] = "eastmoney_direct"
                return model
            record_network_fallback(meta, "sector", "eastmoney_direct_empty")
        except Exception as exc:  # pragma: no cover - exercised by live APIs
            meta.add_error("eastmoney_direct:sector_model", exc)
            record_network_fallback(meta, "sector", f"eastmoney_direct_failed:{type(exc).__name__}")

    if eastmoney_route not in {"auto", "akshare"}:
        meta.network_policy["sector_route"] = "sina_fallback"
        return build_sina_sector_model(ak, candidate_symbols, index_pct3, meta)

    try:
        board_df = ak.stock_board_industry_name_em()
    except Exception as exc:  # pragma: no cover - exercised by live APIs
        meta.add_error("stock_board_industry_name_em", exc)
        meta.network_policy["sector_route"] = "sina_fallback"
        return build_sina_sector_model(ak, candidate_symbols, index_pct3, meta)

    if board_df is None or board_df.empty:
        meta.network_policy["sector_route"] = "sina_fallback"
        return build_sina_sector_model(ak, candidate_symbols, index_pct3, meta)

    model = build_akshare_eastmoney_sector_model(
        ak,
        board_df,
        candidate_symbols,
        end_date,
        index_pct3,
        meta,
    )
    if model:
        meta.network_policy["sector_route"] = "akshare_eastmoney"
        return model
    meta.network_policy["sector_route"] = "sina_fallback"
    return build_sina_sector_model(ak, candidate_symbols, index_pct3, meta)


def build_akshare_eastmoney_sector_model(
    ak: Any,
    board_df: pd.DataFrame,
    candidate_symbols: set[str],
    end_date: str,
    index_pct3: float,
    meta: FetchMeta,
) -> dict[str, dict[str, Any]]:
    board_df = board_df.copy()
    name_col = first_existing(list(board_df.columns), ["板块名称", "名称", "行业名称"])
    pct_col = first_existing(list(board_df.columns), ["涨跌幅", "涨幅", "change_pct"])
    if name_col is None:
        return {}
    if pct_col is not None:
        board_df["_pct"] = pd.to_numeric(board_df[pct_col], errors="coerce").fillna(-999)
        board_df = board_df.sort_values("_pct", ascending=False).reset_index(drop=True)
    board_count = max(1, len(board_df))
    board_rank_pct = {
        str(row[name_col]).strip(): (idx + 1) / board_count * 100 for idx, row in board_df.iterrows()
    }
    board_daily_pct = {
        str(row[name_col]).strip(): to_float(row.get(pct_col), 0.0) if pct_col else 0.0
        for _, row in board_df.iterrows()
    }

    sector_by_symbol: dict[str, dict[str, Any]] = {}
    symbols_left = set(candidate_symbols)
    for _, board in board_df.iterrows():
        sector_name = normalize_board_name_row(board)
        if not sector_name:
            continue
        try:
            cons = ak.stock_board_industry_cons_em(symbol=sector_name)
        except Exception as exc:  # pragma: no cover - exercised by live APIs
            meta.add_error(f"stock_board_industry_cons_em:{sector_name}", exc)
            continue
        if cons is None or cons.empty:
            continue

        cons = cons.copy()
        cons["symbol"] = series_from_alias(cons, ["代码", "证券代码", "code", "symbol"]).map(normalize_code)
        cons["pct_chg"] = pd.to_numeric(series_from_alias(cons, ["涨跌幅", "pct_chg", "change_pct"]), errors="coerce")
        cons["amount"] = pd.to_numeric(series_from_alias(cons, ["成交额", "amount"]), errors="coerce")
        cons = cons.dropna(subset=["symbol"]).sort_values(["pct_chg", "amount"], ascending=[False, False])
        cons_symbols = set(cons["symbol"])
        hits = symbols_left & cons_symbols
        if not hits:
            continue

        strength, amount_expanding = fetch_sector_history(ak, sector_name, end_date, index_pct3, meta)
        if not finite(strength):
            strength = board_daily_pct.get(sector_name, 0.0) - (index_pct3 if finite(index_pct3) else 0.0)

        leaders_count = int((cons["pct_chg"].fillna(0) >= 5.0).sum())
        front_count = max(3, math.ceil(len(cons) * 0.2))
        front_symbols = set(cons.head(front_count)["symbol"])
        for symbol in hits:
            sector_by_symbol[symbol] = {
                "sector": sector_name,
                "sector_strength_vs_index_3d_pct": strength,
                "sector_amount_expanding": amount_expanding,
                "sector_rank_percentile": board_rank_pct.get(sector_name, 100.0),
                "sector_leaders_count": leaders_count,
                "sector_frontline": symbol in front_symbols,
            }
        symbols_left -= hits
        if not symbols_left:
            break

    return sector_by_symbol


def build_eastmoney_direct_sector_model(
    ak: Any,
    eastmoney_client: EastmoneyClient,
    candidate_symbols: set[str],
    end_date: str,
    index_pct3: float,
    meta: FetchMeta,
) -> dict[str, dict[str, Any]]:
    board_df = eastmoney_client.fetch_industry_boards()
    if board_df is None or board_df.empty:
        return {}

    board_df = board_df.copy()
    name_col = first_existing(list(board_df.columns), ["板块名称", "名称", "行业名称"])
    code_col = first_existing(list(board_df.columns), ["板块代码", "代码"])
    pct_col = first_existing(list(board_df.columns), ["涨跌幅", "涨幅", "change_pct"])
    if name_col is None or code_col is None:
        return {}
    if pct_col is not None:
        board_df["_pct"] = pd.to_numeric(board_df[pct_col], errors="coerce").fillna(-999)
        board_df = board_df.sort_values("_pct", ascending=False).reset_index(drop=True)

    board_count = max(1, len(board_df))
    sector_by_symbol: dict[str, dict[str, Any]] = {}
    symbols_left = set(candidate_symbols)
    for idx, board in board_df.iterrows():
        sector_name = normalize_board_name_row(board)
        board_code = str(board.get(code_col) or "").strip()
        if not sector_name or not board_code:
            continue
        try:
            cons = eastmoney_client.fetch_industry_cons(board_code)
        except Exception as exc:  # pragma: no cover - exercised by live APIs
            meta.add_error(f"eastmoney_direct:industry_cons:{board_code}", exc)
            continue
        if cons is None or cons.empty:
            continue

        cons = cons.copy()
        cons["symbol"] = series_from_alias(cons, ["代码", "证券代码", "code", "symbol"]).map(normalize_code)
        cons["pct_chg"] = pd.to_numeric(series_from_alias(cons, ["涨跌幅", "pct_chg", "change_pct"]), errors="coerce")
        cons["amount"] = pd.to_numeric(series_from_alias(cons, ["成交额", "amount"], 0), errors="coerce")
        cons = cons.dropna(subset=["symbol"]).sort_values(["pct_chg", "amount"], ascending=[False, False])
        hits = symbols_left & set(cons["symbol"])
        if not hits:
            continue

        strength, amount_expanding = fetch_sector_history(ak, sector_name, end_date, index_pct3, meta)
        if not finite(strength):
            strength = to_float(board.get(pct_col), 0.0) - (index_pct3 if finite(index_pct3) else 0.0)

        leaders_count = int((cons["pct_chg"].fillna(0) >= 5.0).sum())
        front_count = max(3, math.ceil(len(cons) * 0.2))
        front_symbols = set(cons.head(front_count)["symbol"])
        for symbol in hits:
            sector_by_symbol[symbol] = {
                "sector": sector_name,
                "sector_strength_vs_index_3d_pct": strength,
                "sector_amount_expanding": amount_expanding,
                "sector_rank_percentile": (idx + 1) / board_count * 100,
                "sector_leaders_count": leaders_count,
                "sector_frontline": symbol in front_symbols,
            }
        symbols_left -= hits
        if not symbols_left:
            break

    return sector_by_symbol


def build_sina_sector_model(
    ak: Any,
    candidate_symbols: set[str],
    index_pct3: float,
    meta: FetchMeta,
) -> dict[str, dict[str, Any]]:
    try:
        sector_spot = ak.stock_sector_spot()
    except Exception as exc:  # pragma: no cover - exercised by live APIs
        meta.add_error("stock_sector_spot", exc)
        return {}

    if sector_spot is None or sector_spot.empty:
        return {}

    sector_spot = sector_spot.copy()
    label_col = first_existing(list(sector_spot.columns), ["label"])
    name_col = first_existing(list(sector_spot.columns), ["板块", "名称"])
    pct_col = first_existing(list(sector_spot.columns), ["涨跌幅", "changepercent"])
    if label_col is None or name_col is None:
        return {}

    sector_spot["_pct"] = pd.to_numeric(series_from_alias(sector_spot, ["涨跌幅", "changepercent"], 0), errors="coerce").fillna(-999)
    sector_spot = sector_spot.sort_values("_pct", ascending=False).reset_index(drop=True)
    sector_count = max(1, len(sector_spot))
    sector_by_symbol: dict[str, dict[str, Any]] = {}
    symbols_left = set(candidate_symbols)

    for idx, sector in sector_spot.iterrows():
        label = str(sector[label_col]).strip()
        sector_name = str(sector[name_col]).strip()
        if not label or not sector_name:
            continue
        try:
            cons = ak.stock_sector_detail(sector=label)
        except Exception as exc:  # pragma: no cover - exercised by live APIs
            meta.add_error(f"stock_sector_detail:{label}", exc)
            continue
        if cons is None or cons.empty:
            continue

        cons = cons.copy()
        cons["symbol"] = series_from_alias(cons, ["code", "代码", "symbol"]).map(normalize_code)
        cons["pct_chg"] = pd.to_numeric(
            series_from_alias(cons, ["changepercent", "涨跌幅", "pct_chg"], 0),
            errors="coerce",
        )
        cons["amount"] = pd.to_numeric(series_from_alias(cons, ["amount", "成交额"], 0), errors="coerce")
        cons = cons.dropna(subset=["symbol"]).sort_values(["pct_chg", "amount"], ascending=[False, False])
        hits = symbols_left & set(cons["symbol"])
        if not hits:
            continue

        leaders_count = int((cons["pct_chg"].fillna(0) >= 5.0).sum())
        front_count = max(3, math.ceil(len(cons) * 0.2))
        front_symbols = set(cons.head(front_count)["symbol"])
        daily_strength = to_float(sector.get(pct_col), 0.0) - (index_pct3 if finite(index_pct3) else 0.0)
        for symbol in hits:
            sector_by_symbol[symbol] = {
                "sector": sector_name,
                "sector_strength_vs_index_3d_pct": daily_strength,
                "sector_amount_expanding": False,
                "sector_rank_percentile": (idx + 1) / sector_count * 100,
                "sector_leaders_count": leaders_count,
                "sector_frontline": symbol in front_symbols,
            }
        symbols_left -= hits
        if not symbols_left:
            break

    return sector_by_symbol


def default_sector_info() -> dict[str, Any]:
    return {
        "sector": "未识别",
        "sector_strength_vs_index_3d_pct": 0.0,
        "sector_amount_expanding": False,
        "sector_rank_percentile": 100.0,
        "sector_leaders_count": 0,
        "sector_frontline": False,
    }


def build_tencent_market_info(spot: pd.DataFrame, meta: FetchMeta) -> dict[str, Any]:
    pct = pd.to_numeric(spot.get("pct_chg"), errors="coerce").fillna(0.0)
    amount = pd.to_numeric(spot.get("amount"), errors="coerce")
    positive_ratio = float((pct > 0).mean()) if len(pct) else 0.0
    strong_ratio = float((pct >= 5).mean()) if len(pct) else 0.0
    down_ratio = float((pct <= -7).mean()) if len(pct) else 1.0
    limit_down_count = int((pct <= -9.5).sum()) if len(pct) else 9999
    info = {
        "index_pct3": float(pct.mean()) if len(pct) else 0.0,
        "index_above_ma5_ma10": positive_ratio >= 0.5,
        "amount_expanding": bool(amount.notna().sum() and amount.quantile(0.75) > amount.median()),
        "limit_up_premium_good": strong_ratio >= 0.03,
        "limit_down_risk_low": bool(down_ratio <= 0.02 and limit_down_count <= 100),
    }
    meta.market = {
        "index_pct3": fmt_float(info["index_pct3"], 2),
        "index_above_ma5_ma10": info["index_above_ma5_ma10"],
        "amount_expanding": info["amount_expanding"],
        "limit_up_premium_good": info["limit_up_premium_good"],
        "limit_down_risk_low": info["limit_down_risk_low"],
        "large_drop_ratio": fmt_float(down_ratio, 4),
        "limit_down_count": limit_down_count,
        "approximation": "tencent_quote_breadth",
    }
    return info


def build_tencent_sector_model(
    candidate_symbols: set[str],
    spot: pd.DataFrame,
    index_pct3: float,
    meta: FetchMeta,
) -> dict[str, dict[str, Any]]:
    if not candidate_symbols:
        return {}
    frame = spot.copy()
    frame["sector"] = frame["symbol"].map(tencent_sector_name)
    frame["pct_chg"] = pd.to_numeric(frame["pct_chg"], errors="coerce").fillna(0.0)
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce").fillna(0.0)
    grouped = frame.groupby("sector", dropna=False)
    sector_strength = grouped["pct_chg"].mean().sort_values(ascending=False)
    sector_rank = {
        sector: (idx + 1) / max(1, len(sector_strength)) * 100
        for idx, sector in enumerate(sector_strength.index)
    }

    model: dict[str, dict[str, Any]] = {}
    for sector, group in grouped:
        sorted_group = group.sort_values(["pct_chg", "amount"], ascending=[False, False]).reset_index(drop=True)
        leaders_count = int((sorted_group["pct_chg"] >= 5.0).sum())
        front_count = max(3, math.ceil(len(sorted_group) * 0.2))
        front_symbols = set(sorted_group.head(front_count)["symbol"])
        strength = float(sector_strength.get(sector, 0.0)) - (index_pct3 if finite(index_pct3) else 0.0)
        recent_amount = sorted_group["amount"].head(front_count).mean()
        baseline_amount = sorted_group["amount"].mean()
        amount_expanding = bool(finite(recent_amount) and finite(baseline_amount) and recent_amount >= baseline_amount)
        for symbol in set(sorted_group["symbol"]) & candidate_symbols:
            model[symbol] = {
                "sector": str(sector),
                "sector_strength_vs_index_3d_pct": strength,
                "sector_amount_expanding": amount_expanding,
                "sector_rank_percentile": sector_rank.get(sector, 100.0),
                "sector_leaders_count": leaders_count,
                "sector_frontline": symbol in front_symbols,
            }
    meta.network_policy["sector_route"] = "tencent_market_segment"
    return model


def build_candidate_row(
    spot_row: dict[str, Any],
    history: pd.DataFrame,
    sector_info: dict[str, Any],
    market_info: dict[str, Any],
) -> dict[str, str]:
    close = history["close"]
    ma5_series = rolling_ma(close, 5)
    ma10_series = rolling_ma(close, 10)
    ma20_series = rolling_ma(close, 20)
    ma60_series = rolling_ma(close, 60)
    ma5 = ma5_series.iloc[-1]
    ma10 = ma10_series.iloc[-1]
    ma20 = ma20_series.iloc[-1]
    ma60 = ma60_series.iloc[-1]
    ma5_slope = slope_pct(ma5_series, 1)
    ma20_slope = slope_pct(ma20_series, 5)
    ma60_slope = slope_pct(ma60_series, 5)
    recent5_gain = pct_change_from(close, 5)
    avg_amount_20d = history["amount"].tail(20).mean() / 1_000_000_000
    volume_bullish_day = compute_volume_bullish_day(history)
    volume_pullback_shrink = compute_volume_pullback_shrink(history)
    upper_shadow_ratio = compute_upper_shadow_ratio(history.iloc[-1])
    structure = compute_structure_flags(
        history,
        ma5,
        ma10,
        ma20,
        ma60,
        ma20_slope,
        ma60_slope,
        recent5_gain,
        volume_bullish_day,
        volume_pullback_shrink,
        upper_shadow_ratio,
    )

    sector = {**default_sector_info(), **sector_info}
    row = {
        "symbol": normalize_code(spot_row.get("symbol")),
        "name": str(spot_row.get("name") or ""),
        "sector": str(sector["sector"]),
        "is_st": bool_value(bool(spot_row.get("is_st", False))),
        "close": fmt_float(history["close"].iloc[-1], 2),
        "ma5": fmt_float(ma5, 2),
        "ma10": fmt_float(ma10, 2),
        "ma20": fmt_float(ma20, 2),
        "ma60": fmt_float(ma60, 2),
        "ma5_slope_pct": fmt_float(ma5_slope, 2),
        "ma20_slope_pct": fmt_float(ma20_slope, 2),
        "ma60_slope_pct": fmt_float(ma60_slope, 2),
        "avg_amount_20d_billion": fmt_float(avg_amount_20d, 2),
        "above_mid_platform": bool_value(structure["above_mid_platform"]),
        "platform_breakout": bool_value(structure["platform_breakout"]),
        "trend_pullback": bool_value(structure["trend_pullback"]),
        "strong_consolidation_restart": bool_value(structure["strong_consolidation_restart"]),
        "downtrend_rebound": bool_value(structure["downtrend_rebound"]),
        "recent5_low_rising": bool_value(compute_recent5_low_rising(history)),
        "recent5_gain_pct": fmt_float(recent5_gain, 2),
        "volume_breakout": bool_value(volume_bullish_day),
        "volume_pullback_shrink": bool_value(volume_pullback_shrink),
        "has_volume_bullish_day": bool_value(volume_bullish_day),
        "upper_shadow_ratio": fmt_float(upper_shadow_ratio, 4),
        "sector_strength_vs_index_3d_pct": fmt_float(sector["sector_strength_vs_index_3d_pct"], 2),
        "sector_amount_expanding": bool_value(bool(sector["sector_amount_expanding"])),
        "sector_rank_percentile": fmt_float(sector["sector_rank_percentile"], 2),
        "sector_leaders_count": str(int(sector["sector_leaders_count"])),
        "sector_frontline": bool_value(bool(sector["sector_frontline"])),
        "market_index_above_ma5_ma10": bool_value(bool(market_info["index_above_ma5_ma10"])),
        "market_amount_expanding": bool_value(bool(market_info["amount_expanding"])),
        "market_limit_up_premium_good": bool_value(bool(market_info["limit_up_premium_good"])),
        "market_limit_down_risk_low": bool_value(bool(market_info["limit_down_risk_low"])),
    }
    return {field: row.get(field, "") for field in CANDIDATE_FIELDS}


def resolve_output_path(output_dir: Path, now: datetime, overwrite: bool, output_csv: Path | None = None) -> Path:
    if output_csv is not None:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        return output_csv
    output_dir.mkdir(parents=True, exist_ok=True)
    date_stem = now.strftime("%Y%m%d")
    output = output_dir / f"{date_stem}_candidates.csv"
    if overwrite or not output.exists():
        return output
    return output_dir / f"{now.strftime('%Y%m%d_%H%M%S')}_candidates.csv"


def meta_path_for(output_csv: Path) -> Path:
    return output_csv.with_name(output_csv.name.replace("_candidates.csv", "_fetch_meta.json"))


def write_candidates_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_meta(meta: FetchMeta, path: Path) -> None:
    path.write_text(
        json.dumps(meta.__dict__, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_after_close(now: datetime) -> bool:
    return now.hour > 15 or (now.hour == 15 and now.minute >= 10)


def fetch_tencent_stock_history(
    client: TencentClient,
    symbol: str,
    end_date: str,
    history_days: int,
    meta: FetchMeta | None,
) -> pd.DataFrame:
    try:
        return client.fetch_qfq_history(symbol, end_date, history_days)
    except Exception as exc:  # pragma: no cover - exercised by live APIs
        if meta is not None:
            meta.add_error(f"tencent_qfq_kline:{symbol}", exc)
        raise


def merge_tencent_history_stats(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in ("history_requests", "history_ok", "history_failed"):
        target[key] = int(target.get(key, 0) or 0) + int(source.get(key, 0) or 0)


def build_tencent_candidate_row_from_record(
    idx: int,
    record: dict[str, Any],
    end_date: str,
    history_days: int,
    sector_model: dict[str, dict[str, Any]],
    market_info: dict[str, Any],
) -> tuple[dict[str, str] | None, str | None, dict[str, Any], list[dict[str, str]]]:
    del idx
    client = TencentClient()
    symbol = str(record["symbol"])
    errors: list[dict[str, str]] = []
    try:
        history = fetch_tencent_stock_history(client, symbol, end_date, history_days, None)
    except Exception as exc:
        errors.append({"endpoint": f"tencent_qfq_kline:{symbol}", "error": f"{type(exc).__name__}: {exc}"})
        return None, "tencent_history_fetch_failed", client.stats, errors
    if len(history) < 65:
        return None, f"history_rows_lt_65:{len(history)}", client.stats, errors
    history_pct60 = pct_change_from(history["close"], 60)
    if finite(history_pct60) and history_pct60 < 0:
        return None, f"history_60d_pct_negative:{history_pct60:.2f}", client.stats, errors
    try:
        row = build_candidate_row(
            record,
            history,
            sector_model.get(symbol, default_sector_info()),
            market_info,
        )
    except Exception as exc:
        return None, f"candidate_build_failed:{type(exc).__name__}:{exc}", client.stats, errors
    return row, None, client.stats, errors


def build_tencent_candidate_rows_concurrently(
    indexed_records: list[tuple[int, dict[str, Any]]],
    end_date: str,
    history_days: int,
    top: int,
    workers: int,
    sector_model: dict[str, dict[str, Any]],
    market_info: dict[str, Any],
    meta: FetchMeta,
    tencent_stats: dict[str, Any],
) -> list[dict[str, str]]:
    built: list[tuple[int, dict[str, str]]] = []
    history_started = time.monotonic()

    def apply_result(
        idx: int,
        record: dict[str, Any],
        result: tuple[dict[str, str] | None, str | None, dict[str, Any], list[dict[str, str]]],
    ) -> None:
        row, reason, stats, errors = result
        merge_tencent_history_stats(tencent_stats, stats)
        meta.api_errors.extend(errors)
        record_outcome(idx, record, (row, reason), built, meta)

    try:
        if workers <= 1:
            for idx, record in indexed_records:
                result = build_tencent_candidate_row_from_record(
                    idx,
                    record,
                    end_date,
                    history_days,
                    sector_model,
                    market_info,
                )
                apply_result(idx, record, result)
                if len(built) >= top:
                    break
            return [row for _, row in sorted(built, key=lambda item: item[0])]

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    build_tencent_candidate_row_from_record,
                    idx,
                    record,
                    end_date,
                    history_days,
                    sector_model,
                    market_info,
                ): (idx, record)
                for idx, record in indexed_records
            }
            for future in as_completed(futures):
                idx, record = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    tencent_stats["history_failed"] = int(tencent_stats.get("history_failed", 0) or 0) + 1
                    meta.add_error(f"tencent_candidate:{record.get('symbol', '')}", exc)
                    result = None, f"candidate_build_failed:{type(exc).__name__}:{exc}", {}, []
                apply_result(idx, record, result)
                if len(built) >= top:
                    for pending in futures:
                        pending.cancel()
                    break
        return [row for _, row in sorted(built, key=lambda item: item[0])[:top]]
    finally:
        tencent_stats["history_elapsed_seconds"] = round(time.monotonic() - history_started, 3)


def fetch_tencent_range_candidates(args: argparse.Namespace) -> tuple[Path, Path, int]:
    if args.mode != "prefilter":
        raise SystemExit("Only --mode prefilter is implemented in the first version.")

    started = time.monotonic()
    now = datetime.now()
    end_date = args.end_date or now.strftime("%Y%m%d")
    workers = max(1, int(getattr(args, "workers", 1) or 1))
    quote_batch_size = max(1, int(getattr(args, "quote_batch_size", TENCENT_BATCH_SIZE) or TENCENT_BATCH_SIZE))
    include_bj = bool(getattr(args, "include_bj", False))
    meta = FetchMeta(
        generated_at=now.isoformat(timespec="seconds"),
        source=args.source,
        mode=args.mode,
        snapshot_session="after_close" if is_after_close(now) else "intraday",
        requested_top=args.top,
        max_history=args.max_history,
        workers=workers,
    )
    client = TencentClient(batch_size=quote_batch_size)
    meta.network_policy = {
        "provider": "tencent_range",
        "environment_proxy_policy": "preserved",
        "direct_session_enabled": True,
        "direct_session_trust_env": client.session.trust_env,
        "tencent": client.stats,
        "fallbacks": [],
    }

    spot = client.fetch_a_spot(include_bj=include_bj)
    if spot is None or spot.empty:
        raise RuntimeError("No spot market data returned from Tencent quote range.")
    spot = normalize_spot_frame(spot)
    meta.total_spot_rows = int(len(spot))
    prefiltered = prefilter_spot(spot, args.max_history, args.min_amount_billion)
    meta.prefiltered_rows = int(len(prefiltered))
    market_info = build_tencent_market_info(spot, meta)
    sector_model = build_tencent_sector_model(
        set(prefiltered["symbol"]),
        spot,
        float(market_info.get("index_pct3") or 0.0),
        meta,
    )

    indexed_records = [(idx, row.to_dict()) for idx, row in prefiltered.iterrows()]
    rows = build_tencent_candidate_rows_concurrently(
        indexed_records,
        end_date,
        args.history_days,
        args.top,
        workers,
        sector_model,
        market_info,
        meta,
        client.stats,
    )
    output_csv = resolve_output_path(args.output_dir, now, args.overwrite, getattr(args, "output_csv", None))
    meta_csv = getattr(args, "meta_output", None) or meta_path_for(output_csv)
    meta.output_csv = str(output_csv)
    meta.written_rows = len(rows)
    client.stats["elapsed_seconds"] = round(time.monotonic() - started, 3)
    meta.network_policy["tencent"] = client.stats
    write_candidates_csv(rows, output_csv)
    write_meta(meta, meta_csv)
    if not rows:
        raise SystemExit(f"No live candidates were generated. Empty snapshot: {output_csv}; fetch metadata: {meta_csv}")
    return output_csv, meta_csv, len(rows)


def fetch_akshare_candidates(args: argparse.Namespace) -> tuple[Path, Path, int]:
    if args.source != "akshare":
        raise SystemExit("Only --source akshare is implemented in the first version.")
    if args.mode != "prefilter":
        raise SystemExit("Only --mode prefilter is implemented in the first version.")

    ak = import_akshare()
    now = datetime.now()
    end_date = args.end_date or now.strftime("%Y%m%d")
    meta = FetchMeta(
        generated_at=now.isoformat(timespec="seconds"),
        source=args.source,
        mode=args.mode,
        snapshot_session="after_close" if is_after_close(now) else "intraday",
        requested_top=args.top,
        max_history=args.max_history,
        workers=max(1, args.workers),
    )
    eastmoney_client = None
    if args.eastmoney_route in {"auto", "direct"}:
        eastmoney_client = EastmoneyClient()
    meta.network_policy = {
        "eastmoney_route": args.eastmoney_route,
        "environment_proxy_policy": "preserved",
        "direct_session_enabled": eastmoney_client is not None,
        "direct_session_trust_env": eastmoney_client.session.trust_env if eastmoney_client else None,
        "eastmoney": eastmoney_client.stats if eastmoney_client else {},
        "fallbacks": [],
    }

    spot = fetch_spot_market(ak, meta, eastmoney_client, args.eastmoney_route)
    prefiltered = prefilter_spot(spot, args.max_history, args.min_amount_billion)
    meta.prefiltered_rows = int(len(prefiltered))
    market_info = build_market_info(ak, spot, end_date, meta)
    sector_model = build_sector_model(
        ak,
        set(prefiltered["symbol"]),
        end_date,
        float(market_info.get("index_pct3") or 0.0),
        meta,
        eastmoney_client,
        args.eastmoney_route,
    )

    indexed_records = [(idx, record.to_dict()) for idx, record in prefiltered.iterrows()]
    rows = build_candidate_rows_concurrently(
        ak,
        indexed_records,
        end_date,
        args.history_days,
        args.top,
        max(1, args.workers),
        sector_model,
        market_info,
        meta,
    )

    output_csv = resolve_output_path(args.output_dir, now, args.overwrite, getattr(args, "output_csv", None))
    meta_csv = getattr(args, "meta_output", None) or meta_path_for(output_csv)
    meta.output_csv = str(output_csv)
    meta.written_rows = len(rows)
    if eastmoney_client:
        meta.network_policy["eastmoney"] = eastmoney_client.stats
    write_candidates_csv(rows, output_csv)
    write_meta(meta, meta_csv)
    if not rows:
        raise SystemExit(f"No live candidates were generated. Empty snapshot: {output_csv}; fetch metadata: {meta_csv}")
    return output_csv, meta_csv, len(rows)


def fetch_live_candidates(args: argparse.Namespace) -> tuple[Path, Path, int]:
    if args.source == "tencent_range":
        return fetch_tencent_range_candidates(args)
    if args.source == "auto":
        try:
            return fetch_tencent_range_candidates(argparse.Namespace(**{**vars(args), "source": "tencent_range"}))
        except Exception as exc:
            print(f"Tencent provider failed, falling back to AKShare: {type(exc).__name__}: {exc}")
            return fetch_akshare_candidates(argparse.Namespace(**{**vars(args), "source": "akshare"}))
    return fetch_akshare_candidates(args)


def build_candidate_rows_concurrently(
    ak: Any,
    indexed_records: list[tuple[int, dict[str, Any]]],
    end_date: str,
    history_days: int,
    top: int,
    workers: int,
    sector_model: dict[str, dict[str, Any]],
    market_info: dict[str, Any],
    meta: FetchMeta,
) -> list[dict[str, str]]:
    built: list[tuple[int, dict[str, str]]] = []
    if workers <= 1:
        for idx, record in indexed_records:
            outcome = build_candidate_row_from_record(
                ak,
                idx,
                record,
                end_date,
                history_days,
                sector_model,
                market_info,
                meta,
            )
            record_outcome(idx, record, outcome, built, meta)
            if len(built) >= top:
                break
        return [row for _, row in sorted(built, key=lambda item: item[0])]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                build_candidate_row_from_record,
                ak,
                idx,
                record,
                end_date,
                history_days,
                sector_model,
                market_info,
                meta,
            ): (idx, record)
            for idx, record in indexed_records
        }
        for future in as_completed(futures):
            idx, record = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:
                outcome = None, f"candidate_build_failed:{type(exc).__name__}:{exc}"
            record_outcome(idx, record, outcome, built, meta)
            if len(built) >= top:
                for pending in futures:
                    pending.cancel()
                break
    return [row for _, row in sorted(built, key=lambda item: item[0])[:top]]


def build_candidate_row_from_record(
    ak: Any,
    idx: int,
    record: dict[str, Any],
    end_date: str,
    history_days: int,
    sector_model: dict[str, dict[str, Any]],
    market_info: dict[str, Any],
    meta: FetchMeta,
) -> tuple[dict[str, str] | None, str | None]:
    del idx
    symbol = str(record["symbol"])
    try:
        history = fetch_stock_history(ak, symbol, end_date, history_days, meta)
    except Exception:
        return None, "history_fetch_failed"
    if len(history) < 65:
        return None, f"history_rows_lt_65:{len(history)}"
    history_pct60 = pct_change_from(history["close"], 60)
    if finite(history_pct60) and history_pct60 < 0:
        return None, f"history_60d_pct_negative:{history_pct60:.2f}"
    try:
        row = build_candidate_row(
            record,
            history,
            sector_model.get(symbol, default_sector_info()),
            market_info,
        )
    except Exception as exc:
        return None, f"candidate_build_failed:{type(exc).__name__}:{exc}"
    return row, None


def record_outcome(
    idx: int,
    record: dict[str, Any],
    outcome: tuple[dict[str, str] | None, str | None],
    built: list[tuple[int, dict[str, str]]],
    meta: FetchMeta,
) -> None:
    row, reason = outcome
    if row is not None:
        built.append((idx, row))
        return
    meta.skip(str(record.get("symbol", "")), str(record.get("name", "")), reason or "unknown_skip")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch real A-share data from AKShare and build a scorer-compatible candidate snapshot."
    )
    parser.add_argument("--source", default="akshare", choices=["akshare", "tencent_range", "auto"], help="Data source provider.")
    parser.add_argument("--provider", dest="source", choices=["akshare", "tencent_range", "auto"], help="Alias for --source.")
    parser.add_argument("--mode", default="prefilter", choices=["prefilter"], help="Candidate generation mode.")
    parser.add_argument(
        "--eastmoney-route",
        default="auto",
        choices=["auto", "direct", "akshare", "off"],
        help="How to access Eastmoney push2 endpoints without changing global proxy settings.",
    )
    parser.add_argument("--top", type=int, default=100, help="Number of final candidates to write.")
    parser.add_argument(
        "--max-history",
        type=int,
        default=500,
        help="Maximum prefiltered symbols to fetch daily history for.",
    )
    parser.add_argument("--history-days", type=int, default=150, help="Daily bars to keep for feature calculation.")
    parser.add_argument(
        "--min-amount-billion",
        type=float,
        default=0.5,
        help="Minimum current-day turnover in billion CNY for prefiltering.",
    )
    parser.add_argument("--workers", type=int, default=1, help="Concurrent stock-history fetch workers.")
    parser.add_argument(
        "--quote-batch-size",
        type=int,
        default=TENCENT_BATCH_SIZE,
        help="Tencent quote symbols per request when --provider tencent_range is used.",
    )
    parser.add_argument(
        "--include-bj",
        action="store_true",
        help="Include the broad Beijing Stock Exchange code ranges in Tencent quote scanning.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/snapshots"), help="Snapshot output directory.")
    parser.add_argument("--output-csv", type=Path, help="Exact candidate CSV output path.")
    parser.add_argument("--meta-output", type=Path, help="Exact fetch metadata JSON output path.")
    parser.add_argument("--end-date", help="AKShare end date in YYYYMMDD format; defaults to today.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite YYYYMMDD snapshot if it already exists.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    output_csv, meta_path, row_count = fetch_live_candidates(args)
    print(f"Generated {row_count} live candidates.")
    print(f"Candidate snapshot: {output_csv}")
    print(f"Fetch metadata: {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
