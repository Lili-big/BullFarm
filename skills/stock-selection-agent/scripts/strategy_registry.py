from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    version: str
    schema_version: int
    description: str


V1_TREND_STARTUP = StrategySpec(
    strategy_id="v1_trend_startup",
    version="v1_0",
    schema_version=1,
    description="40/25/25/10 trend, startup, sector, and market scoring model.",
)

STRATEGIES = {
    V1_TREND_STARTUP.version: V1_TREND_STARTUP,
    V1_TREND_STARTUP.strategy_id: V1_TREND_STARTUP,
}


def resolve_strategy(value: str | None = None) -> StrategySpec:
    if not value:
        return V1_TREND_STARTUP
    key = value.strip()
    if key in STRATEGIES:
        return STRATEGIES[key]
    raise ValueError(f"Unknown strategy version or id: {value}")
