---
name: a-share-short-term-strategy
description: Chinese A-share short-term trading analysis for market trend, sector/direction rotation, and single-stock participation decisions. Use when the user asks about A-share market mood, today's or tomorrow's tradability, sector rotation, theme direction, potential short-term stocks, or whether a specific A-share can be chased, bought on pullback, watched, or avoided over the next 2-3 trading days.
---

# A-Share Short-Term Strategy

## Purpose

Use this skill to produce concise Chinese short-term A-share analysis. Focus on 2-3 trading day participation value, not long-term valuation.

Always treat the output as a rule-based decision aid, not investment advice. Never claim certainty.

## Required Reference

Before producing the final answer, read `references/analysis-framework.md` and use the matching template:

- Market trend questions: market mood, today/tomorrow, tradability, index environment, whether to attack or defend.
- Sector/direction questions: industry, concept, theme, policy direction, rotation opportunity.
- Single-stock questions: stock name, ticker, K-line, buy/sell decision, chase or pullback, 2-3 day continuation.

If a request combines multiple types, route to the most specific type. Single-stock analysis should still include sector and market resonance.

## Data Discipline

Do not invent current market facts. For current-day or latest analysis, use live or provided data when available. If data is missing, explicitly say which fields are missing and give only conditional conclusions.

Useful data includes:

- Market: trading date, total turnover, up/down counts, limit-up and limit-down counts, failed-board rate, prior-limit-up premium, sector ranking, and market risk events.
- Sector: recent 2-3 day relative strength, sector turnover expansion, rank among sectors, leading stocks, front-row continuation, and whether the move is mainline or one-day rotation.
- Stock: latest daily K-line, 60-120 trading day history, MA5/MA20/MA60, volume, turnover, 5-day highs/lows, upper shadows, sector, liquidity, ST/delisting flags, and whether it is front-row or follower.

When the data is insufficient, do not force a definitive buy/sell call. Use "data insufficient, conditional judgment only" in Chinese.

## Core Rules

- Default to excluding ST, delisting-risk names, and illiquid small caps.
- Analyze market permission before aggressive participation.
- For single stocks, judge in this order: medium-term trend, recent 5-day startup, sector resonance, market environment, then entry/exit plan.
- Every participation suggestion must include a trigger condition and a stop-loss condition.
- Do not recommend unconditional chasing.
- Do not recommend averaging down.
- Downgrade the conclusion when the market is weak, the sector is cooling, the stock is back-row, or the move is only an oversold rebound.
- Prefer actionable language: chase strength, buy pullback, wait for confirmation, observe, avoid, reduce, stop-loss, or take profit.

## Current Project Fit

This skill is a human-facing analysis layer. If the user asks for runnable batch screening, scored CSV output, dashboard publication, or historical validation in this repository, use it together with `skills/stock-selection-agent`, which owns the deterministic scoring and local automation pipeline.
