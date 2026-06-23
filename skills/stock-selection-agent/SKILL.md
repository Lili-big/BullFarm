---
name: stock-selection-agent
description: Rule-based A-share stock selection and 2-3 day continuation assessment using medium-term trend, recent 5-day startup, sector strength, and market environment filters. Use when the user asks to screen stocks, score candidates, judge whether a trend setup can continue, convert K-line/volume/sector/market data into an actionable watchlist, or apply the 60-120 day trend to recent 5-day confirmation to sector mainline to market permission framework.
---

# Stock Selection Agent

## Overview

Use this skill to turn candidate stock data into a ranked watchlist with four scores: medium-term trend, recent 5-day startup, sector strength, and market environment. Treat every output as a rule-based decision aid, not investment advice.

## Workflow

1. Collect candidate data for at least the latest 60-120 trading days, plus recent 5-day price/volume behavior, sector ranking, sector leaders, and market breadth.
2. Normalize the data into a CSV matching the project schema. If data comes from screenshots, first extract the visible values and state any missing fields as assumptions.
3. Run `scripts/score_candidates.py` when a CSV is available. Use `references/scoring-model.md` for manual scoring, field mapping, and interpretation.
4. Report each candidate with: trend score, 5-day startup score, sector score, market score, total score, continuation type, buy model, stop conditions, and final participation level.
5. Always call out missing data, hard rejection reasons, and market/sector conditions that cap position size.

## Decision Rules

- Strong participation: total score >= 80, trend >= 25, startup >= 15, sector >= 15, and market >= 5.
- Light trial: total score 65-79, or a strong individual setup capped by a merely neutral market.
- Watch only: total score 50-64, sector is not active, or startup confirmation is incomplete.
- Avoid: total score < 50, trend score < 25, ST/liquidity failure, clear downtrend rebound, or high-volume upper-shadow failure.

## Output Style

For each stock, use this concise format:

- Trend: score and whether the 60-120 day base is valid.
- 5-day startup: score and whether lows are rising, price is above the 5-day average, and volume confirms.
- Sector: score and whether it is a recent mainline or only a one-day move.
- Market: offensive, low-absorption only, watch, or defensive.
- 2-3 day view: strong continuation, weak continuation, divergence-to-strength, or strong-to-weak.
- Plan: buy trigger, add trigger, stop trigger, and position cap.

## Resources

- `scripts/score_candidates.py`: deterministic scorer for candidate CSV files.
- `references/scoring-model.md`: detailed scoring rubric, input fields, and interpretation notes.

Do not invent live market facts. If current market, sector ranking, limit-up counts, or money flow are needed and not provided, ask for data or explicitly mark them as missing.
