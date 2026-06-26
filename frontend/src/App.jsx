import React, { useEffect, useMemo, useState } from "react";

const config = {
  supabaseUrl: import.meta.env.VITE_SUPABASE_URL || "",
  supabaseAnonKey: import.meta.env.VITE_SUPABASE_ANON_KEY || "",
  runsIndexView: import.meta.env.VITE_DASHBOARD_RUNS_INDEX_VIEW || "dashboard_runs_index",
  runDetailView: import.meta.env.VITE_DASHBOARD_RUN_DETAIL_VIEW || "dashboard_runs",
  enableLocalFallback:
    import.meta.env.DEV || String(import.meta.env.VITE_ENABLE_LOCAL_FALLBACK || "").toLowerCase() === "true",
  localIndexUrl: "/data/dashboard/runs_index.json",
  localRunsBaseUrl: "/data/dashboard/runs/",
};

function hasSupabaseConfig() {
  return Boolean(config.supabaseUrl && config.supabaseAnonKey);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", ...options });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function fetchSupabaseRows(view, query) {
  const baseUrl = config.supabaseUrl.replace(/\/$/, "");
  return fetchJson(`${baseUrl}/rest/v1/${view}?${query}`, {
    headers: {
      apikey: config.supabaseAnonKey,
      Authorization: `Bearer ${config.supabaseAnonKey}`,
      Accept: "application/json",
    },
  });
}

function dateKey(value) {
  const text = String(value || "");
  const match = text.match(/(20\d{2})[-_/]?(\d{2})[-_/]?(\d{2})/);
  return match ? `${match[1]}${match[2]}${match[3]}` : text;
}

function normalizeIndexPayload(payload) {
  if (Array.isArray(payload)) {
    if (payload.length && payload[0].payload) {
      return normalizeIndexPayload(payload[0].payload);
    }
    const runs = payload
      .map((row) => ({
        date: dateKey(row.date || row.date_key || row.selection_date),
        selection_date: row.selection_date || row.date || row.date_key,
        run_id: row.run_id || "",
        label: row.label || row.market_env || row.run_id || "",
        market_env: row.market_env || "",
        total_selected_count: Number(row.total_selected_count || row.selected_count || 0),
        top_score: row.top_score ?? null,
        average_score: row.average_score ?? null,
        score_buckets: row.score_buckets || {},
        has_review: Boolean(row.has_review),
        review_status: row.review_status || "missing_review",
        run_count: Number(row.run_count || 1),
      }))
      .filter((row) => row.date);
    runs.sort((a, b) => b.date.localeCompare(a.date));
    return { schema_version: 1, latest_date: runs[0]?.date || "", runs };
  }
  return payload || { runs: [] };
}

function normalizeDetailPayload(payload) {
  if (Array.isArray(payload)) {
    if (!payload.length) {
      throw new Error("empty detail view");
    }
    return normalizeDetailPayload(payload[0].payload || payload[0]);
  }
  return payload || {};
}

async function loadIndex() {
  if (hasSupabaseConfig()) {
    const rows = await fetchSupabaseRows(config.runsIndexView, "select=*&order=date.desc");
    return { source: "Supabase", data: normalizeIndexPayload(rows) };
  }
  if (config.enableLocalFallback) {
    return { source: "本地 JSON", data: normalizeIndexPayload(await fetchJson(config.localIndexUrl)) };
  }
  throw new Error("缺少 VITE_SUPABASE_URL 或 VITE_SUPABASE_ANON_KEY。");
}

async function loadDetail(runDate) {
  if (hasSupabaseConfig()) {
    const rows = await fetchSupabaseRows(
      config.runDetailView,
      `select=*&date=eq.${encodeURIComponent(runDate)}&limit=1`
    );
    return { source: "Supabase", data: normalizeDetailPayload(rows) };
  }
  if (config.enableLocalFallback) {
    return {
      source: "本地 JSON",
      data: normalizeDetailPayload(await fetchJson(`${config.localRunsBaseUrl}${runDate}.json`)),
    };
  }
  throw new Error("缺少 Supabase 公共读取配置。");
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function formatPct(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "-";
  }
  return `${number.toFixed(2)}%`;
}

function reviewLabel(status) {
  const map = {
    ready: "复盘完成",
    reviewed: "已复盘",
    partial_review: "部分复盘",
    insufficient_data: "数据不足",
    missing_review: "暂无复盘",
  };
  return map[status] || status || "-";
}

function chipTone(value) {
  if (["强参与", "ready", "reviewed", "成功"].includes(value)) {
    return "good";
  }
  if (["回避", "失败"].includes(value)) {
    return "bad";
  }
  if (["轻仓试错", "只观察", "partial_review", "insufficient_data", "missing_review", "数据不足"].includes(value)) {
    return "warn";
  }
  return "";
}

function scoreWidth(score) {
  const number = Number(score);
  if (!Number.isFinite(number)) {
    return 0;
  }
  return Math.max(0, Math.min(100, number));
}

function Metric({ label, value, hint }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint || ""}</small>
    </article>
  );
}

function EmptyState({ title, message }) {
  return (
    <section className="empty-state">
      <strong>{title}</strong>
      <p>{message}</p>
    </section>
  );
}

export default function App() {
  const [index, setIndex] = useState(null);
  const [detail, setDetail] = useState(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [source, setSource] = useState("Supabase");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState({ keyword: "", decision: "", sector: "", model: "", minScore: "" });

  useEffect(() => {
    let active = true;
    setLoading(true);
    loadIndex()
      .then(({ source: dataSource, data }) => {
        if (!active) return;
        setSource(dataSource);
        setIndex(data);
        setSelectedDate(data.latest_date || data.runs?.[0]?.date || "");
      })
      .catch((err) => {
        if (!active) return;
        setError(err.message);
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    let active = true;
    setLoading(true);
    loadDetail(selectedDate)
      .then(({ source: dataSource, data }) => {
        if (!active) return;
        setSource(dataSource);
        setDetail(data);
        setError("");
      })
      .catch((err) => {
        if (!active) return;
        setDetail(null);
        setError(err.message);
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [selectedDate]);

  const picks = useMemo(() => {
    const rows = detail?.picks || [];
    const keyword = filters.keyword.trim().toLowerCase();
    const minScore = Number(filters.minScore);
    return rows.filter((pick) => {
      const text = `${pick.name || ""} ${pick.stock_code || ""} ${pick.symbol || ""}`.toLowerCase();
      if (keyword && !text.includes(keyword)) return false;
      if (filters.decision && pick.decision !== filters.decision) return false;
      if (filters.sector && pick.sector !== filters.sector) return false;
      if (filters.model && pick.buy_model !== filters.model) return false;
      if (Number.isFinite(minScore) && String(filters.minScore) && Number(pick.total_score || 0) < minScore) return false;
      return true;
    });
  }, [detail, filters]);

  const metrics = detail?.metrics || {};
  const review = metrics.review || {};
  const effectiveness = detail?.strategy_effectiveness || {};
  const currentRun = detail?.run || {};
  const reviewEmpty = detail?.review?.empty_state;
  const dateOptions = index?.runs || [];

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>牧牛记</h1>
          <p className="subtitle">核心指标与明细数据来自 Supabase 公共视图。</p>
        </div>
        <div className="toolbar">
          <label>
            日期
            <select value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)}>
              {dateOptions.map((run) => (
                <option key={`${run.date}-${run.run_id}`} value={run.date}>
                  {run.date} {run.label ? `· ${run.label}` : ""}
                </option>
              ))}
            </select>
          </label>
          <div className="source-pill">
            <span />
            {loading ? "读取中" : source}
          </div>
        </div>
      </header>

      {error ? (
        <EmptyState title="数据读取未完成" message={error} />
      ) : (
        <>
          <section className="metrics">
            <Metric label="标的数" value={formatValue(metrics.selected_count)} hint={`${formatValue(metrics.sector_count)} 个板块`} />
            <Metric label="最高分" value={formatValue(metrics.top_score)} hint={`平均 ${formatValue(metrics.average_score)}`} />
            <Metric label="强参与" value={formatValue(metrics.score_buckets?.strong || 0)} hint="80 分及以上" />
            <Metric label="轻仓试错" value={formatValue(metrics.score_buckets?.trial || 0)} hint="65-79 分" />
            <Metric
              label="T3 胜率"
              value={formatPct(review.win_rate_t3)}
              hint={review.valid_stock_count ? `${review.valid_stock_count} 条有效` : reviewLabel(metrics.review_status)}
            />
            <Metric label="T3 均收" value={formatPct(review.avg_return_t3_pct)} hint={review.conclusion || reviewLabel(metrics.review_status)} />
            <Metric label="策略样本" value={formatValue(effectiveness.reviewed_run_count || 0)} hint={`${formatValue(effectiveness.valid_stock_count || 0)} 条复盘`} />
            <Metric
              label="策略结论"
              value={formatValue(effectiveness.conclusion)}
              hint={`T3 ${formatPct(effectiveness.avg_return_t3_pct)} · 最新 ${formatPct(effectiveness.avg_return_latest_pct)}`}
            />
          </section>

          <section className="run-strip">
            <span>Run ID：{formatValue(currentRun.run_id || detail?.active_run_id)}</span>
            <span>策略：{formatValue(currentRun.strategy_version)}</span>
            <span>环境：{formatValue(currentRun.market_env)}</span>
            <span>生成：{formatValue(detail?.generated_at)}</span>
          </section>

          {reviewEmpty ? <EmptyState title={reviewEmpty.title} message={reviewEmpty.message} /> : null}

          <section className="filters">
            <label>
              搜索
              <input
                value={filters.keyword}
                onChange={(event) => setFilters({ ...filters, keyword: event.target.value })}
                placeholder="股票名或代码"
              />
            </label>
            <label>
              结论
              <select value={filters.decision} onChange={(event) => setFilters({ ...filters, decision: event.target.value })}>
                <option value="">全部结论</option>
                {(detail?.filters?.decisions || []).map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.value} ({item.count})
                  </option>
                ))}
              </select>
            </label>
            <label>
              板块
              <select value={filters.sector} onChange={(event) => setFilters({ ...filters, sector: event.target.value })}>
                <option value="">全部板块</option>
                {(detail?.filters?.sectors || []).map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.value} ({item.count})
                  </option>
                ))}
              </select>
            </label>
            <label>
              买点
              <select value={filters.model} onChange={(event) => setFilters({ ...filters, model: event.target.value })}>
                <option value="">全部买点</option>
                {(detail?.filters?.buy_models || []).map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.value} ({item.count})
                  </option>
                ))}
              </select>
            </label>
            <label>
              最低分
              <input
                type="number"
                min="0"
                max="100"
                value={filters.minScore}
                onChange={(event) => setFilters({ ...filters, minScore: event.target.value })}
                placeholder="0"
              />
            </label>
          </section>

          <section className="results-head">
            <strong>选股明细</strong>
            <span>{picks.length} 条</span>
          </section>

          <section className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="rank">排名</th>
                  <th>标的</th>
                  <th>板块</th>
                  <th className="score-col">评分</th>
                  <th className="decision-col">结论</th>
                  <th className="review-col">复盘</th>
                </tr>
              </thead>
              <tbody>
                {picks.map((pick) => {
                  const reviewData = pick.review || {};
                  const reviewStatus = reviewData.status || "missing_review";
                  return (
                    <tr key={`${pick.stock_code || pick.symbol}-${pick.rank}`}>
                      <td className="rank">#{formatValue(pick.rank)}</td>
                      <td>
                        <div className="name">{formatValue(pick.name)}</div>
                        <div className="code">{formatValue(pick.stock_code || pick.symbol)}</div>
                        <details>
                          <summary>详情</summary>
                          <div className="detail-grid">
                            <div><strong>买点</strong>{formatValue(pick.buy_model)}<br />{formatValue(pick.continuation)}</div>
                            <div><strong>计划</strong>{formatValue(pick.plan)}</div>
                            <div><strong>理由</strong>{formatValue(pick.notes)}</div>
                            <div><strong>风险</strong>{formatValue(pick.risks || pick.hard_rejects)}</div>
                            <div>
                              <strong>价格</strong>
                              入选 {formatValue(pick.selection_price)} / 止损 {formatValue(pick.stop_loss_price)} / 止盈 {formatValue(pick.take_profit_price)}
                            </div>
                            <div>
                              <strong>复盘</strong>
                              {formatValue(reviewData.result_label || reviewLabel(reviewStatus))}
                              <br />
                              T1 {formatPct(reviewData.returns?.return_t1_close_pct)} / T2 {formatPct(reviewData.returns?.return_t2_close_pct)} / T3 {formatPct(reviewData.returns?.return_t3_close_pct)}
                            </div>
                          </div>
                        </details>
                      </td>
                      <td><span className="chip">{formatValue(pick.sector)}</span></td>
                      <td className="score-col">
                        <div className="score">
                          <strong>{formatValue(pick.total_score)}</strong>
                          <div className="score-line"><span style={{ width: `${scoreWidth(pick.total_score)}%` }} /></div>
                        </div>
                      </td>
                      <td className="decision-col">
                        <span className={`chip ${chipTone(pick.decision)}`}>{formatValue(pick.decision)}</span>
                      </td>
                      <td className="review-col">
                        <span className={`chip ${chipTone(reviewStatus)}`}>{reviewLabel(reviewStatus)}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {picks.length === 0 ? <div className="empty-rows">没有匹配结果</div> : null}
          </section>
        </>
      )}
    </main>
  );
}
