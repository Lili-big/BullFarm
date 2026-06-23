# 选股 Agent 项目

这个项目把你的选股框架落成了一个可运行的规则型 Agent：先看 60-120 日趋势，再看近 5 日启动，再看板块是否是近期主线，最后用大盘环境决定能不能进攻和仓位。

## 目录

- `agent.yaml`：Agent 项目配置和处理流程。
- `config/scoring_rules.json`：评分阈值、流动性门槛和风险参数。
- `data/sample_candidates.csv`：虚构样例数据，用来验证流程。
- `skills/stock-selection-agent/SKILL.md`：可复用的 Codex Skill 能力说明。
- `skills/stock-selection-agent/scripts/score_candidates.py`：评分脚本。
- `skills/stock-selection-agent/references/scoring-model.md`：完整评分规则。
- `outputs/`：生成报告的位置。

## 快速运行

在 `stock-selection-agent` 目录下运行：

```powershell
python .\skills\stock-selection-agent\scripts\score_candidates.py `
  --input .\data\sample_candidates.csv `
  --config .\config\scoring_rules.json `
  --output .\outputs\selection_report.md `
  --csv-output .\outputs\selection_scores.csv
```

运行后会生成：

- `outputs/selection_report.md`：可读的选股报告。
- `outputs/selection_scores.csv`：结构化评分结果。

## 输入字段

最重要的字段包括：

- 基础信息：`symbol`、`name`、`sector`、`is_st`
- 趋势：`close`、`ma5`、`ma20`、`ma60`、`ma5_slope_pct`、`ma20_slope_pct`、`ma60_slope_pct`
- 流动性：`avg_amount_20d_billion`
- 结构：`platform_breakout`、`trend_pullback`、`strong_consolidation_restart`、`downtrend_rebound`
- 近 5 日：`recent5_low_rising`、`recent5_gain_pct`、`volume_breakout`、`volume_pullback_shrink`、`upper_shadow_ratio`
- 板块：`sector_strength_vs_index_3d_pct`、`sector_amount_expanding`、`sector_rank_percentile`、`sector_leaders_count`、`sector_frontline`
- 大盘：`market_index_above_ma5_ma10`、`market_amount_expanding`、`market_limit_up_premium_good`、`market_limit_down_risk_low`

## 结论分层

- `强参与`：总分 80 分以上，且趋势、启动、板块、大盘都过线。
- `轻仓试错`：65-80 分，或个股不错但市场/板块限制仓位。
- `只观察`：50-65 分，等待突破、回踩确认或板块走强。
- `回避`：50 分以下、趋势不合格、下降趋势反抽、ST、流动性不足或高位强转弱。

风险提示：这个工具只做规则化筛选，不构成投资建议；真实使用前需要接入实时行情、公告、流动性和个人风控。
