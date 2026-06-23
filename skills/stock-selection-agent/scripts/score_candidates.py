from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "liquidity": {
        "min_avg_amount_20d_billion": 3.0
    },
    "risk": {
        "max_recent5_gain_pct": 30.0,
        "caution_recent5_gain_pct": 25.0,
        "max_upper_shadow_ratio": 0.05
    },
    "sector": {
        "top_rank_percentile": 30.0,
        "min_leaders_count": 2
    },
    "thresholds": {
        "strong": 80,
        "trial": 65,
        "watch": 50,
        "min_trend": 25,
        "min_startup": 15,
        "min_sector": 15,
        "min_market_for_attack": 5
    }
}

TRUE_VALUES = {"1", "true", "yes", "y", "是", "是的", "true", "ok", "pass", "符合"}
FALSE_VALUES = {"0", "false", "no", "n", "否", "不是", "fail", "不符合", ""}


@dataclass
class ScoreBreakdown:
    trend: int = 0
    startup: int = 0
    sector: int = 0
    market: int = 0
    notes: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    hard_rejects: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.trend + self.startup + self.sector + self.market


@dataclass
class CandidateResult:
    symbol: str
    name: str
    sector_name: str
    score: ScoreBreakdown
    decision: str
    continuation: str
    buy_model: str
    plan: str


def load_config(path: Path | None) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if not path:
        return config
    with path.open("r", encoding="utf-8-sig") as handle:
        override = json.load(handle)
    deep_update(config, override)
    return config


def deep_update(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value


def first_value(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        if key in row and str(row[key]).strip() != "":
            return str(row[key]).strip()
    return None


def as_float(row: dict[str, str], *keys: str, default: float | None = None) -> float | None:
    raw = first_value(row, *keys)
    if raw is None:
        return default
    cleaned = raw.replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return default


def as_ratio(row: dict[str, str], *keys: str, default: float = 0.0) -> float:
    value = as_float(row, *keys, default=default)
    if value is None:
        return default
    return value / 100 if value > 1 else value


def as_percentile(row: dict[str, str], *keys: str, default: float = 100.0) -> float:
    value = as_float(row, *keys, default=default)
    if value is None:
        return default
    return value * 100 if 0 < value <= 1 else value


def as_bool(row: dict[str, str], *keys: str, default: bool | None = False) -> bool | None:
    raw = first_value(row, *keys)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    try:
        return float(normalized) != 0
    except ValueError:
        return default


def is_slope_up(row: dict[str, str], pct_key: str, text_key: str) -> bool:
    direction = first_value(row, text_key)
    if direction:
        if direction in {"向上", "上行", "拐头向上", "走平向上", "up", "rising"}:
            return True
        if direction in {"向下", "下行", "down", "falling"}:
            return False
    slope = as_float(row, pct_key, default=None)
    return slope is not None and slope > 0


def is_slope_flat_or_up(row: dict[str, str], pct_key: str, text_key: str) -> bool:
    direction = first_value(row, text_key)
    if direction:
        if direction in {"向上", "上行", "拐头向上", "走平", "走平向上", "up", "flat", "rising"}:
            return True
        if direction in {"向下", "下行", "down", "falling"}:
            return False
    slope = as_float(row, pct_key, default=None)
    return slope is not None and slope >= -0.05


def score_candidate(row: dict[str, str], config: dict[str, Any]) -> CandidateResult:
    score = ScoreBreakdown()
    symbol = first_value(row, "symbol", "code", "股票代码", "证券代码") or ""
    name = first_value(row, "name", "股票名称", "证券简称") or symbol
    sector_name = first_value(row, "sector", "所属板块", "行业") or "未提供"

    close = as_float(row, "close", "收盘价", default=None)
    ma5 = as_float(row, "ma5", "5日线", "5日均线", default=None)
    ma20 = as_float(row, "ma20", "20日线", "20日均线", default=None)
    ma60 = as_float(row, "ma60", "60日线", "60日均线", default=None)

    above_ma20 = as_bool(row, "price_above_ma20", "股价站上20日线", default=None)
    if above_ma20 is None and close is not None and ma20 is not None:
        above_ma20 = close > ma20
    above_ma60 = as_bool(row, "price_above_ma60", "股价站上60日线", default=None)
    if above_ma60 is None and close is not None and ma60 is not None:
        above_ma60 = close > ma60

    if above_ma20:
        score.trend += 8
    else:
        score.risks.append("股价未确认站上20日线")
    if above_ma60:
        score.trend += 8
    else:
        score.risks.append("股价未确认站上60日线")
    if is_slope_up(row, "ma20_slope_pct", "ma20_direction"):
        score.trend += 8
    else:
        score.risks.append("20日线未确认向上")
    if is_slope_flat_or_up(row, "ma60_slope_pct", "ma60_direction"):
        score.trend += 6
    else:
        score.risks.append("60日线仍偏下行")

    structure_flags = {
        "平台突破": as_bool(row, "platform_breakout", "平台突破", default=False),
        "趋势回踩": as_bool(row, "trend_pullback", "趋势回踩", default=False),
        "强势震荡再启动": as_bool(row, "strong_consolidation_restart", "强势震荡再启动", default=False),
    }
    if any(structure_flags.values()):
        score.trend += 10
        score.notes.append("中期结构清晰：" + "、".join(k for k, v in structure_flags.items() if v))
    elif as_bool(row, "above_mid_platform", "站上中期平台", default=False):
        score.trend += 5
        score.notes.append("站上中期平台，但突破/回踩结构还需确认")
    else:
        score.risks.append("缺少平台突破、趋势回踩或再启动结构")

    recent5_low_rising = as_bool(row, "recent5_low_rising", "近5日低点抬高", default=False)
    if recent5_low_rising:
        score.startup += 6
    else:
        score.risks.append("近5日低点未确认抬高")

    ma5_up = is_slope_up(row, "ma5_slope_pct", "ma5_direction")
    if ma5_up:
        score.startup += 5
    else:
        score.risks.append("5日线未确认向上")

    if close is not None and ma5 is not None and close <= ma5:
        score.risks.append("股价未站稳5日线")

    volume_start = as_bool(row, "has_volume_bullish_day", "volume_breakout", "放量阳线启动", "突破放量", default=False)
    if volume_start:
        score.startup += 6
    else:
        score.risks.append("缺少放量阳线启动")

    if as_bool(row, "volume_pullback_shrink", "回踩缩量", default=False):
        score.startup += 4
    else:
        score.risks.append("回调缩量未确认")

    upper_shadow_ratio = as_ratio(row, "upper_shadow_ratio", "上影线比例", default=0.0)
    long_upper_shadow = as_bool(row, "long_upper_shadow", "长上影", default=False) or upper_shadow_ratio > config["risk"]["max_upper_shadow_ratio"]
    if not long_upper_shadow:
        score.startup += 4
    else:
        score.risks.append("存在长上影或冲高回落")

    sector_strength = as_float(row, "sector_strength_vs_index_3d_pct", "板块近3日强于大盘", default=None)
    if (sector_strength is not None and sector_strength > 0) or as_bool(row, "sector_stronger_than_index", "板块强于大盘", default=False):
        score.sector += 7
    else:
        score.risks.append("板块近2-3日未确认强于大盘")

    if as_bool(row, "sector_amount_expanding", "板块成交额放大", default=False):
        score.sector += 6
    else:
        score.risks.append("板块成交额未确认放大")

    sector_rank = as_percentile(row, "sector_rank_percentile", "板块涨幅排名分位", default=100.0)
    if sector_rank <= config["sector"]["top_rank_percentile"]:
        score.sector += 5
    else:
        score.risks.append("板块排名不够靠前")

    leaders_count = as_float(row, "sector_leaders_count", "板块核心股数量", default=0) or 0
    if leaders_count >= config["sector"]["min_leaders_count"]:
        score.sector += 5
    else:
        score.risks.append("板块内核心强势股不足")

    if as_bool(row, "sector_frontline", "个股前排", default=False):
        score.sector += 2
    else:
        score.risks.append("个股可能不是板块前排")

    if as_bool(row, "market_index_above_ma5_ma10", "指数站上5日10日线", default=False):
        score.market += 3
    else:
        score.risks.append("指数未确认站上5日线和10日线")

    if as_bool(row, "market_amount_expanding", "市场成交额放大", default=False):
        score.market += 3
    else:
        score.risks.append("市场成交额未确认放大")

    if as_bool(row, "market_limit_up_premium_good", "涨停溢价较好", default=False):
        score.market += 2
    else:
        score.risks.append("涨停溢价未确认")

    if as_bool(row, "market_limit_down_risk_low", "跌停风险较低", default=False):
        score.market += 2
    else:
        score.risks.append("跌停/大面风险未确认较低")

    apply_hard_gates(row, score, config)
    buy_model = classify_buy_model(row, structure_flags)
    decision = classify_decision(score, config)
    continuation = classify_continuation(row, score, config, long_upper_shadow)
    plan = build_plan(decision, buy_model, score)
    return CandidateResult(symbol, name, sector_name, score, decision, continuation, buy_model, plan)


def apply_hard_gates(row: dict[str, str], score: ScoreBreakdown, config: dict[str, Any]) -> None:
    if as_bool(row, "is_st", "ST", "是否ST", default=False):
        score.hard_rejects.append("ST或风险警示标的")

    amount = as_float(row, "avg_amount_20d_billion", "20日平均成交额_十亿", default=None)
    if amount is not None and amount < config["liquidity"]["min_avg_amount_20d_billion"]:
        score.hard_rejects.append(f"20日平均成交额不足{config['liquidity']['min_avg_amount_20d_billion']}十亿")

    if as_bool(row, "downtrend_rebound", "下降趋势反抽", default=False):
        score.hard_rejects.append("疑似长期下降趋势中的反抽")

    recent5_gain = as_float(row, "recent5_gain_pct", "近5日涨幅", default=0.0) or 0.0
    if recent5_gain >= config["risk"]["max_recent5_gain_pct"]:
        score.hard_rejects.append(f"近5日涨幅{recent5_gain:.1f}%过度透支")
    elif recent5_gain >= config["risk"]["caution_recent5_gain_pct"]:
        score.risks.append(f"近5日涨幅{recent5_gain:.1f}%偏高，追高风险增加")


def classify_buy_model(row: dict[str, str], structure_flags: dict[str, bool | None]) -> str:
    if structure_flags.get("平台突破"):
        return "平台突破买点"
    if structure_flags.get("趋势回踩"):
        return "趋势回踩买点"
    if as_bool(row, "strong_turnover_setup", "强势换手", default=False):
        return "强势换手买点"
    if structure_flags.get("强势震荡再启动"):
        return "强势震荡再启动"
    return "等待放量突破或回踩确认"


def classify_decision(score: ScoreBreakdown, config: dict[str, Any]) -> str:
    t = config["thresholds"]
    if score.hard_rejects or score.trend < t["min_trend"]:
        return "回避"

    if score.total >= t["strong"]:
        decision = "强参与"
    elif score.total >= t["trial"]:
        decision = "轻仓试错"
    elif score.total >= t["watch"]:
        decision = "只观察"
    else:
        decision = "回避"

    if score.startup < t["min_startup"] and decision in {"强参与", "轻仓试错"}:
        decision = "只观察"
        score.risks.append("近5日启动分低于参与线")

    if score.sector < t["min_sector"] and decision in {"强参与", "轻仓试错"}:
        decision = "只观察"
        score.risks.append("板块分低于参与线")

    if score.market < t["min_market_for_attack"]:
        if decision == "强参与":
            decision = "轻仓试错"
        elif decision == "轻仓试错":
            decision = "只观察"
        score.risks.append("大盘环境低于进攻线，必须降仓")

    return decision


def classify_continuation(row: dict[str, str], score: ScoreBreakdown, config: dict[str, Any], long_upper_shadow: bool) -> str:
    recent5_gain = as_float(row, "recent5_gain_pct", "近5日涨幅", default=0.0) or 0.0
    sector_fading = as_bool(row, "sector_fading", "板块退潮", default=False)

    if score.hard_rejects or long_upper_shadow or sector_fading or recent5_gain >= config["risk"]["max_recent5_gain_pct"]:
        return "强转弱风险"
    if score.total >= 80 and score.startup >= 18 and score.sector >= 18 and score.market >= 5:
        return "强延续"
    if score.total >= 65 and score.market >= 5:
        return "分歧转强观察"
    if score.total >= 50:
        return "弱延续"
    return "无交易价值"


def build_plan(decision: str, buy_model: str, score: ScoreBreakdown) -> str:
    if decision == "强参与":
        prefix = "2成仓先手；突破确认或回踩不破再加到3成，总仓不超过60%-70%。"
    elif decision == "轻仓试错":
        prefix = "1成仓试错；只做确认买点，不追高开和连续加速。"
    elif decision == "只观察":
        prefix = "加入观察池；等待放量突破、缩量回踩确认或板块重新走强。"
    else:
        prefix = "不参与；等待趋势、启动和板块重新满足条件。"

    if buy_model == "平台突破买点":
        trigger = "触发：收盘站稳平台上沿，或次日不低开且回踩平台不破。"
        stop = "止损：跌回平台内部、跌破突破K低点、跌破5日线无法收回。"
    elif buy_model == "趋势回踩买点":
        trigger = "触发：回踩5/10/20日线缩量企稳，并出现放量反包。"
        stop = "止损：跌破10日线、跌破启动阳线低点、放量阴线破位。"
    elif buy_model == "强势换手买点":
        trigger = "触发：盘中充分换手后重新站上分时均线或昨日收盘价。"
        stop = "止损：高开低走、跌破昨日收盘无法收回、板块前排炸板。"
    else:
        trigger = "触发：补齐平台突破、趋势回踩或强势换手信号。"
        stop = "止损：跌破5日线、启动K低点或板块退潮。"

    if score.hard_rejects:
        return prefix + " 硬性原因：" + "；".join(score.hard_rejects)
    return f"{prefix} {trigger} {stop}"


def read_candidates(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(results: list[CandidateResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank", "symbol", "name", "sector", "total_score", "trend_score",
        "startup_score", "sector_score", "market_score", "decision",
        "continuation", "buy_model", "notes", "risks", "hard_rejects", "plan"
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, result in enumerate(results, start=1):
            writer.writerow({
                "rank": rank,
                "symbol": result.symbol,
                "name": result.name,
                "sector": result.sector_name,
                "total_score": result.score.total,
                "trend_score": result.score.trend,
                "startup_score": result.score.startup,
                "sector_score": result.score.sector,
                "market_score": result.score.market,
                "decision": result.decision,
                "continuation": result.continuation,
                "buy_model": result.buy_model,
                "notes": "；".join(result.score.notes),
                "risks": "；".join(result.score.risks),
                "hard_rejects": "；".join(result.score.hard_rejects),
                "plan": result.plan,
            })


def write_markdown(results: list[CandidateResult], path: Path, source: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# 选股 Agent 评分报告")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 数据来源：`{source}`")
    lines.append("- 风险提示：本报告是规则化筛选结果，不构成投资建议；真实交易前必须复核实时行情、流动性、公告和风险事件。")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append("| 排名 | 代码 | 名称 | 板块 | 总分 | 趋势 | 5日启动 | 板块 | 大盘 | 结论 | 2-3日判断 | 买点模型 |")
    lines.append("| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |")
    for rank, result in enumerate(results, start=1):
        s = result.score
        lines.append(
            f"| {rank} | {result.symbol} | {result.name} | {result.sector_name} | "
            f"{s.total} | {s.trend} | {s.startup} | {s.sector} | {s.market} | "
            f"{result.decision} | {result.continuation} | {result.buy_model} |"
        )
    lines.append("")
    lines.append("## 明细")
    lines.append("")
    for rank, result in enumerate(results, start=1):
        s = result.score
        lines.append(f"### {rank}. {result.name}（{result.symbol}）")
        lines.append("")
        lines.append(f"- 板块：{result.sector_name}")
        lines.append(f"- 评分：总分{s.total}，中期趋势{s.trend}/40，近5日启动{s.startup}/25，板块{s.sector}/25，大盘{s.market}/10")
        lines.append(f"- 结论：{result.decision}；2-3日判断：{result.continuation}；买点模型：{result.buy_model}")
        if s.notes:
            lines.append(f"- 有利条件：{'；'.join(s.notes)}")
        if s.risks:
            lines.append(f"- 风险/缺口：{'；'.join(s.risks[:8])}")
        if s.hard_rejects:
            lines.append(f"- 硬性回避：{'；'.join(s.hard_rejects)}")
        lines.append(f"- 参与策略：{result.plan}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def decision_rank(decision: str) -> int:
    return {"强参与": 0, "轻仓试错": 1, "只观察": 2, "回避": 3}.get(decision, 9)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score stock candidates with the trend/startup/sector/market model.")
    parser.add_argument("--input", required=True, type=Path, help="Candidate CSV path.")
    parser.add_argument("--config", type=Path, help="Optional scoring config JSON path.")
    parser.add_argument("--output", type=Path, default=Path("outputs/selection_report.md"), help="Markdown report output path.")
    parser.add_argument("--csv-output", type=Path, default=Path("outputs/selection_scores.csv"), help="Scored CSV output path.")
    args = parser.parse_args()

    config = load_config(args.config)
    rows = read_candidates(args.input)
    if not rows:
        raise SystemExit("No candidate rows found.")

    results = [score_candidate(row, config) for row in rows]
    results.sort(key=lambda result: (decision_rank(result.decision), -result.score.total, result.symbol))
    write_markdown(results, args.output, args.input)
    write_csv(results, args.csv_output)
    print(f"Scored {len(results)} candidates.")
    print(f"Markdown report: {args.output}")
    print(f"CSV scores: {args.csv_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
