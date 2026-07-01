# Frontend And Local Data Boundary

## Summary

牧牛记页面是本地数据看板。后端任务负责生成结构化 JSON，前端负责读取和展示这些 JSON，不直接触发选股算法，也不保存运行结果。

## Boundary

| 层级 | 责任 |
| --- | --- |
| Codex 自动化 | 定时唤醒本地任务。 |
| 本地任务控制面 | 触发、查询、重试、记录任务状态。 |
| 选股与复盘脚本 | 抓取行情、评分、更新价格、生成报告。 |
| 本地结构化数据 | 保存 `outputs/daily/`、`outputs/jobs/`、`data/dashboard/`。 |
| 前端页面 | 读取 `data/dashboard/` 并提供筛选、指标和复盘视图。 |

## Frontend Data Contract

前端固定读取：

- `/data/dashboard/runs_index.json`
- `/data/dashboard/runs/<YYYYMMDD>.json`

详情 JSON 至少包含：

- `run`
- `metrics`
- `strategy_effectiveness`
- `filters`
- `review`
- `picks`
- `picks[].review.price_points`

历史复盘表的动态列只从 `price_points` 生成，不写死日期。

## Local Development

`frontend/vite.config.js` 的 `local-dashboard-data` 插件在 dev 和 preview 模式下都把仓库根目录 `data/dashboard/` 挂载为 `/data/dashboard/`。

本地页面启动：

```powershell
npm.cmd --prefix frontend run dev
```

本地数据刷新：

```powershell
python .\skills\stock-selection-agent\scripts\build_dashboard_data.py
```

## Acceptance

- 页面顶部数据源显示“本地 JSON”。
- 日期选择来自 `runs_index.json`。
- 指标、筛选项、选股明细和历史复盘都来自单日详情 JSON。
- 缺少复盘或价格点时显示本地 JSON 中的空状态。
- 前端源码和构建产物不包含远端数据库或部署平台配置。
