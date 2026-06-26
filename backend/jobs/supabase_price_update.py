from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from backend.supabase_jobs import get_supabase_client


def as_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pct_change(latest_price: Any, selection_price: Any) -> float | None:
    latest = as_float(latest_price)
    base = as_float(selection_price)
    if latest is None or base in {None, 0}:
        return None
    return round((latest - base) / base * 100, 4)


def normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        return text
    if text.startswith(("60", "68", "90")):
        return f"{text}.SH"
    return f"{text}.SZ"


def build_latest_price_rows(
    selections: list[dict[str, Any]],
    quote_by_code: dict[str, dict[str, Any]],
    *,
    data_source: str = "render_supabase_price_update",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    updated_at = datetime.now().isoformat(timespec="seconds")
    for selection in selections:
        stock_code = normalize_code(selection.get("stock_code") or selection.get("symbol"))
        quote = quote_by_code.get(stock_code) or quote_by_code.get(stock_code.split(".")[0]) or {}
        latest_price = as_float(quote.get("close") or quote.get("latest_price"))
        if not stock_code or latest_price is None:
            continue
        rows.append(
            {
                "run_id": selection.get("run_id"),
                "stock_code": stock_code,
                "stock_name": selection.get("stock_name"),
                "selection_date": selection.get("selection_date"),
                "trading_day_offset": "LATEST",
                "price_date": quote.get("price_date") or quote.get("trade_date"),
                "open": as_float(quote.get("open")),
                "high": as_float(quote.get("high")),
                "low": as_float(quote.get("low")),
                "close": latest_price,
                "volume": as_float(quote.get("volume")),
                "amount": as_float(quote.get("amount")),
                "turnover_rate": as_float(quote.get("turnover_rate")),
                "is_suspended": bool(quote.get("is_suspended", False)),
                "data_source": data_source,
                "price_payload": quote,
                "updated_at": updated_at,
            }
        )
    return rows


def build_latest_performance_rows(
    selections: list[dict[str, Any]],
    quote_by_code: dict[str, dict[str, Any]],
    *,
    data_status: str = "latest",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    updated_at = datetime.now().isoformat(timespec="seconds")
    for selection in selections:
        stock_code = normalize_code(selection.get("stock_code") or selection.get("symbol"))
        quote = quote_by_code.get(stock_code) or quote_by_code.get(stock_code.split(".")[0]) or {}
        latest_price = as_float(quote.get("close") or quote.get("latest_price"))
        if not stock_code or latest_price is None:
            continue
        return_latest = pct_change(latest_price, selection.get("selection_price"))
        rows.append(
            {
                "run_id": selection.get("run_id"),
                "stock_code": stock_code,
                "stock_name": selection.get("stock_name"),
                "selection_date": selection.get("selection_date"),
                "sector": selection.get("sector"),
                "strategy_label": selection.get("buy_model") or selection.get("strategy_label"),
                "participation_level": selection.get("decision") or selection.get("participation_level"),
                "total_score": selection.get("total_score"),
                "rank_in_run": selection.get("rank_in_run"),
                "selection_price": as_float(selection.get("selection_price")),
                "latest_price": latest_price,
                "latest_price_date": quote.get("price_date") or quote.get("trade_date"),
                "return_latest_pct": return_latest,
                "is_profitable_latest": return_latest is not None and return_latest > 0,
                "result_label": "success" if return_latest is not None and return_latest > 0 else "pending",
                "data_status": data_status,
                "performance_payload": {"quote": quote, "selection": selection},
                "updated_at": updated_at,
            }
        )
    return rows


def upsert_price_update(
    selections: list[dict[str, Any]],
    quote_by_code: dict[str, dict[str, Any]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    price_rows = build_latest_price_rows(selections, quote_by_code)
    performance_rows = build_latest_performance_rows(selections, quote_by_code)
    if dry_run:
        return {
            "status": "dry_run",
            "prices": len(price_rows),
            "performance": len(performance_rows),
        }
    client = get_supabase_client()
    if client is None:
        return {"status": "skipped", "reason": "Missing Supabase service-role credentials."}
    if price_rows:
        client.table("stock_selection_prices").upsert(
            price_rows,
            on_conflict="run_id,stock_code,trading_day_offset",
        ).execute()
    if performance_rows:
        client.table("stock_selection_performance").upsert(
            performance_rows,
            on_conflict="run_id,stock_code",
        ).execute()
    return {"status": "success", "prices": len(price_rows), "performance": len(performance_rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upsert latest quote/performance rows into Supabase.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    summary = upsert_price_update([], {}, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in {"success", "dry_run", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
