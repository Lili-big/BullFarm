# 选股 Agent 项目

这个项目把你的选股框架落成了一个可运行的规则型 Agent：先看 60-120 日趋势，再看近 5 日启动，再看板块是否是近期主线，最后用大盘环境决定能不能进攻和仓位。

## 目录

- `agent.yaml`：Agent 项目配置和处理流程。
- `config/scoring_rules.json`：评分阈值、流动性门槛和风险参数。
- `data/sample_candidates.csv`：虚构样例数据，用来验证流程。
- `data/snapshots/`：真实行情快照输出目录，运行抓取脚本后自动生成。
- `requirements.txt`：真实数据抓取所需的 Python 依赖。
- `skills/stock-selection-agent/SKILL.md`：可复用的 Codex Skill 能力说明。
- `skills/stock-selection-agent/scripts/fetch_live_candidates.py`：AKShare 真实数据快照生成脚本。
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

## Dashboard

生成本地 Dashboard 数据：

```powershell
python .\skills\stock-selection-agent\scripts\build_dashboard_data.py
```

脚本会写入：

- `data/dashboard/runs_index.json`：日期索引和核心指标摘要。
- `data/dashboard/runs/YYYYMMDD.json`：单日选股明细、筛选项和复盘状态。

页面入口是 `dashboard/index.html`。本地预览时在项目根目录启动静态服务：

```powershell
python -m http.server 8000
```

然后打开 `http://127.0.0.1:8000/dashboard/`。页面会优先读取 `window.STOCK_DASHBOARD_CONFIG` 或 `localStorage.stockDashboardSupabase` 中配置的 Supabase 公共视图；未配置或读取失败时，自动读取本地 JSON。

## 真实数据快照

第一版真实数据接入使用 AKShare。先安装依赖：

```powershell
python -m pip install -r .\requirements.txt
```

收盘后或盘中都可以生成快照，盘中快照会在元数据中标记为 `intraday`：

```powershell
python .\skills\stock-selection-agent\scripts\fetch_live_candidates.py `
  --provider tencent_range `
  --mode prefilter `
  --eastmoney-route auto `
  --top 100 `
  --max-history 500 `
  --workers 4 `
  --quote-batch-size 800 `
  --output-dir .\data\snapshots
```

Tencent range fetch defaults to common SH/SZ code ranges. Use `--include-bj`
only when the broad Beijing Stock Exchange scan is required. Tencent history
fetching supports `--workers`; the daily config uses 4 by default.

脚本会生成：

- `data/snapshots/YYYYMMDD_candidates.csv`：兼容评分器的真实候选股快照。
- `data/snapshots/YYYYMMDD_fetch_meta.json`：抓取统计、接口异常、跳过原因和市场环境元数据。

如果同一天的快照已经存在，脚本默认生成 `YYYYMMDD_HHMMSS_candidates.csv`；传入 `--overwrite` 会覆盖当天快照。

Tencent 路径默认用 `--workers 4` 并发抓历史 K 线；AKShare 兜底路径仍可按网络质量调整 `--workers`。

脚本不会修改 Windows、本机代理或当前终端的 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`。东方财富 `push2.eastmoney.com` 实时行情和行业接口默认使用脚本内部的独立 direct session，并只在这个 session 上禁用环境代理；这不会影响 Codex 或其他程序的代理设置。

`--eastmoney-route` 可选值：

- `auto`：默认值，优先使用项目内 direct session，失败后降级到 AKShare/Sina 路径。
- `direct`：只使用项目内 direct session 获取东方财富实时行情；行情入口失败时退出。
- `akshare`：使用 AKShare 自带东方财富接口，便于对照调试代理行为。
- `off`：跳过东方财富实时/行业接口，只走现有 fallback。

生成快照后，用真实数据执行评分：

```powershell
python .\skills\stock-selection-agent\scripts\score_candidates.py `
  --input .\data\snapshots\YYYYMMDD_candidates.csv `
  --config .\config\scoring_rules.json `
  --output .\outputs\selection_report.md `
  --csv-output .\outputs\selection_scores.csv
```

## Daily orchestration

Run the daily job from the project root with the archive date and market
as-of date set to the same complete trading day:

```powershell
python .\skills\stock-selection-agent\scripts\run_daily_selection.py `
  --run-date 20260625 `
  --as-of-date 20260625
```

The Codex automation `股票筛选每日全量选股` is scheduled for 08:30
Asia/Shanghai every day. It first computes `target_date` as the previous
complete trading day, then runs:

```powershell
python .\skills\stock-selection-agent\scripts\run_daily_selection.py `
  --run-date <target_date> `
  --as-of-date <target_date>
```

The job archives inputs under `data/snapshots/YYYYMMDD/` and results under
`outputs/daily/YYYYMMDD/`. On success it refreshes `data/snapshots/latest/`
and `outputs/daily/latest/`; on failure it writes
`outputs/daily/YYYYMMDD/run_manifest.json` and leaves `latest` untouched.
The configured pipeline also updates historical validation prices with the
latest available quote, rebuilds dashboard JSON, and syncs the run payload to
Supabase.

Supabase is a publication gate. If the service-role environment is unavailable,
the runner writes a SQL bundle under `outputs/daily/YYYYMMDD/supabase_sql/`,
marks the manifest `pending_supabase`, and does not publish `latest`. Execute
the bundle, verify the public dashboard views and anon read-only permissions,
then finalize with:

```powershell
python .\skills\stock-selection-agent\scripts\run_daily_selection.py `
  --finalize-run <target_date> `
  --verified-run-id <run_id>
```

Useful safe-run flags:

- `--dry-run`: print the planned stages and commands without writing outputs.
- `--skip-live-fetch`: use an existing snapshot or `data/sample_candidates.csv`.
- `--skip-supabase`: skip the publish/upload stage.
- `--skip-price-update`: skip the validation price-update stage.

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

## 选股结果验证闭环

评分完成后，可以把每一次选股结果写入统一 Excel 总表，并在后续交易日补充 T0/T1/T2/T3/T5/T10 行情，复盘这批结果是否盈利。

默认总表位置：`data/validation/output/stock_selection_log.xlsx`。脚本每次写入前会把旧总表备份到 `data/validation/output/backup/`。

```powershell
python .\skills\stock-selection-agent\scripts\validate_selection_results.py snapshot `
  --scores .\outputs\selection_scores.csv `
  --candidates .\data\snapshots\YYYYMMDD_candidates.csv `
  --market-env 震荡

python .\skills\stock-selection-agent\scripts\validate_selection_results.py update-prices `
  --run-id 20260623_153000_v1_0 `
  --offsets 0,1,2,3,5,10

python .\skills\stock-selection-agent\scripts\validate_selection_results.py analyze `
  --run-id 20260623_153000_v1_0

python .\skills\stock-selection-agent\scripts\validate_selection_results.py compare `
  --group-by participation_level

python .\skills\stock-selection-agent\scripts\validate_selection_results.py report `
  --run-id 20260623_153000_v1_0
```

验证逻辑使用选股快照里的 `close` 作为默认 `selection_price`，再按真实交易日补充后续收盘价。收益按 `(future_price - selection_price) / selection_price * 100` 计算；停牌、缺价、未来价格不足会写入状态，不会中断复盘流程。

离线调试补价时，可以传入本地 CSV 或 Excel 行情文件：

```powershell
python .\skills\stock-selection-agent\scripts\validate_selection_results.py update-prices `
  --run-id 20260623_153000_v1_0 `
  --price-file .\data\validation\input\prices\prices.csv

```

## Supabase sync environment

The Supabase sync script builds local upsert payloads first and only writes when both server-side credentials are present.

Local setup:

```powershell
Copy-Item .\config\local.env.example .\config\local.env
notepad .\config\local.env
```

Fill in:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

`config/local.env` is ignored by git and must never be committed. OS-level environment variables with the same names still take precedence over this local file.

Dry-run example:

```powershell
python .\skills\stock-selection-agent\scripts\sync_supabase.py --dry-run --print-payload
```

If either variable is missing, the script reports `skipped` and does not connect to Supabase.

本地价格文件字段至少包含：`trade_date`、`stock_code`、`open`、`high`、`low`、`close`、`volume`、`amount`、`turnover_rate`。
