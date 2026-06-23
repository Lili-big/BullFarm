# Stock Selection Scoring Model

Use this rubric to score candidate stocks for 2-3 day continuation probability. The strategy filters in this order: medium-term trend health, recent 5-day startup confirmation, sector mainline strength, then market permission.

## Hard Gates

Reject or cap participation when any of these apply:

- ST stock or other excluded security flag.
- 20-day average turnover below the configured minimum, default 3 billion CNY.
- Clear downtrend rebound: price below 60-day MA while 20-day and 60-day MA are both falling.
- High-volume long upper shadow after an acceleration move.
- Market score below 5: do not allow "strong participation" even if the individual setup looks good.

## Scores

Medium-term trend, 40 points:

| Condition | Points |
| --- | ---: |
| Price above 20-day MA | 8 |
| Price above 60-day MA | 8 |
| 20-day MA rising | 8 |
| 60-day MA flat or rising | 6 |
| Clear platform breakout, trend pullback, or consolidation restart | 10 |

Recent 5-day startup, 25 points:

| Condition | Points |
| --- | ---: |
| Recent 5-day lows are rising | 6 |
| 5-day MA is rising | 5 |
| Volume-backed bullish startup candle | 6 |
| Pullback volume shrinks | 4 |
| No long upper-shadow stagnation | 4 |

Sector strength, 25 points:

| Condition | Points |
| --- | ---: |
| Sector beat the broad index in the last 2-3 days | 7 |
| Sector turnover expanded | 6 |
| Sector rank is near the top | 5 |
| Sector has at least two leading strong stocks | 5 |
| Candidate is front-row, not late follower | 2 |

Market environment, 10 points:

| Condition | Points |
| --- | ---: |
| Major index above 5-day and 10-day MA | 3 |
| Market turnover expanded | 3 |
| Limit-up premium is good | 2 |
| Limit-down and large-loss risk is low | 2 |

## Participation Levels

- Strong participation: total >= 80, all section minimums pass, market >= 5.
- Light trial: total 65-79, or a good stock setup in a neutral market.
- Watch only: total 50-64, incomplete startup, weak sector, or capped by market.
- Avoid: total < 50, trend < 25, hard gate failure, or clear strong-to-weak behavior.

## Buy Model Mapping

- Platform breakout: 10-30 day range breakout with volume and close above platform top. Prefer late-day confirmation, next-day non-break, or low-volume pullback to the platform top.
- Trend pullback: medium-term uptrend, pullback holds 5/10/20-day MA, volume contracts, then volume-backed reversal candle appears.
- Strong turnover: front-row sector stock after limit-up or large bullish candle, next day not deeply lower, intraday turnover is sufficient, and it regains intraday average or prior close after divergence.

## Sell and Stop Rules

Exit or reduce when:

- No next-day premium after a limit-up or large bullish candle.
- Price breaks the startup candle low.
- Price breaks the 5-day MA and cannot reclaim it.
- High-volume long upper shadow appears and the next day cannot reverse.
- Sector leaders fail, open boards, or fall sharply.

## CSV Field Notes

The scorer accepts English field names and a few common Chinese aliases. Important fields include:

- `symbol`, `name`, `sector`, `is_st`
- `close`, `ma5`, `ma10`, `ma20`, `ma60`
- `ma5_slope_pct`, `ma20_slope_pct`, `ma60_slope_pct`
- `avg_amount_20d_billion`
- `platform_breakout`, `trend_pullback`, `strong_consolidation_restart`, `downtrend_rebound`
- `recent5_low_rising`, `recent5_gain_pct`, `volume_breakout`, `volume_pullback_shrink`, `has_volume_bullish_day`, `upper_shadow_ratio`
- `sector_strength_vs_index_3d_pct`, `sector_amount_expanding`, `sector_rank_percentile`, `sector_leaders_count`, `sector_frontline`
- `market_index_above_ma5_ma10`, `market_amount_expanding`, `market_limit_up_premium_good`, `market_limit_down_risk_low`
