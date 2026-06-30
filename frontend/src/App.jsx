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

function normalizeStockCode(value) {
  const text = String(value || "").trim().toUpperCase();
  const match = text.match(/(\d{6})/);
  if (!match) return text;
  const code = match[1];
  if (text.endsWith(".SH") || text.endsWith(".SZ") || text.endsWith(".BJ")) {
    return `${code}.${text.slice(-2)}`;
  }
  if (code.startsWith("6") || code.startsWith("9")) return `${code}.SH`;
  if (code.startsWith("4") || code.startsWith("8")) return `${code}.BJ`;
  return `${code}.SZ`;
}

function numericValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function calculateReturnPct(closePrice, basePrice) {
  const close = numericValue(closePrice);
  const base = numericValue(basePrice);
  if (close === null || base === null || base === 0) return null;
  return Number((((close - base) / base) * 100).toFixed(4));
}

function pricePointOrder(offset) {
  const text = String(offset || "").toUpperCase();
  if (text === "LATEST") return Number.MAX_SAFE_INTEGER;
  const match = text.match(/\d+/);
  return match ? Number(match[0]) : Number.MAX_SAFE_INTEGER - 1;
}

function buildPricePointsFromRows(rows, basePrice) {
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => !["T0", "0"].includes(String(row.trading_day_offset || "").toUpperCase()))
    .map((row) => ({
      trading_day_offset: row.trading_day_offset,
      price_date: row.price_date,
      close: numericValue(row.close),
      return_pct: calculateReturnPct(row.close, basePrice),
    }))
    .filter((row) => row.trading_day_offset && (row.price_date || row.close !== null))
    .sort((a, b) => {
      const dateCompare = String(a.price_date || "").localeCompare(String(b.price_date || ""));
      return dateCompare || pricePointOrder(a.trading_day_offset) - pricePointOrder(b.trading_day_offset);
    });
}

async function enrichDetailWithSupabasePrices(detail) {
  const runId = detail?.run?.run_id || detail?.active_run_id;
  const picks = Array.isArray(detail?.picks) ? detail.picks : [];
  if (!hasSupabaseConfig() || !runId || !picks.length) return detail;

  const query = [
    "select=stock_code,trading_day_offset,price_date,close",
    `run_id=eq.${encodeURIComponent(runId)}`,
    "order=stock_code.asc,price_date.asc",
  ].join("&");
  const priceRows = await fetchSupabaseRows("stock_selection_prices", query);
  if (!Array.isArray(priceRows) || !priceRows.length) return detail;

  const pricesByCode = new Map();
  priceRows.forEach((row) => {
    const code = normalizeStockCode(row.stock_code);
    if (!code) return;
    if (!pricesByCode.has(code)) pricesByCode.set(code, []);
    pricesByCode.get(code).push(row);
  });

  return {
    ...detail,
    picks: picks.map((pick) => {
      const code = normalizeStockCode(pick.stock_code || pick.symbol);
      const rows = pricesByCode.get(code) || [];
      if (!rows.length) return pick;
      const review = pick.review || {};
      const basePrice = review.selection_price ?? pick.selection_price;
      return {
        ...pick,
        review: {
          ...review,
          price_points: buildPricePointsFromRows(rows, basePrice),
        },
      };
    }),
  };
}

function dateKey(value) {
  const text = String(value || "");
  const match = text.match(/(20\d{2})[-_/]?(\d{2})[-_/]?(\d{2})/);
  return match ? `${match[1]}${match[2]}${match[3]}` : text;
}

function isInternalRunLabel(value) {
  const text = String(value || "").trim().toLowerCase();
  return ["local", "stability_check", "稳定性检查", "用例文件"].includes(text);
}

function isPublishedDashboardRun(row) {
  const runId = String(row.run_id || "").toLowerCase();
  if (runId.includes("stability_check") || runId.includes("_local")) {
    return false;
  }
  return !isInternalRunLabel(row.label) && !isInternalRunLabel(row.market_env);
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
      .filter((row) => row.date && isPublishedDashboardRun(row));
    runs.sort(
      (a, b) =>
        b.date.localeCompare(a.date) ||
        Number(b.has_review) - Number(a.has_review) ||
        String(b.run_id || "").localeCompare(String(a.run_id || ""))
    );
    return { schema_version: 1, latest_date: runs[0]?.date || "", runs };
  }
  return payload || { runs: [] };
}

function runOptionValue(run) {
  return run?.run_id || run?.date || "";
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

async function loadDetail(run) {
  const runDate = typeof run === "string" ? run : run?.date;
  const runId = typeof run === "string" ? "" : run?.run_id;
  if (hasSupabaseConfig()) {
    const filter = runId
      ? `run_id=eq.${encodeURIComponent(runId)}`
      : `date=eq.${encodeURIComponent(runDate)}`;
    const rows = await fetchSupabaseRows(
      config.runDetailView,
      `select=*&${filter}&limit=1`
    );
    return { source: "Supabase", data: await enrichDetailWithSupabasePrices(normalizeDetailPayload(rows)) };
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

function formatSignedPct(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "-";
  }
  const sign = number > 0 ? "+" : "";
  return `${sign}${number.toFixed(2)}%`;
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

function changeTone(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) {
    return "";
  }
  return number > 0 ? "price-up" : "price-down";
}

function joinPresent(parts, separator = " / ") {
  const values = parts.map(formatValue).filter((value) => value !== "-");
  return values.length ? values.join(separator) : "-";
}

function pickKey(pick) {
  return `${pick.stock_code || pick.symbol || pick.name || "stock"}-${pick.rank || ""}`;
}

function stageOrder(offset) {
  const match = String(offset || "").match(/\d+/);
  return match ? Number(match[0]) : Number.MAX_SAFE_INTEGER;
}

function getPriceStages(picks) {
  const stages = new Map();
  picks.forEach((pick) => {
    const rows = Array.isArray(pick.review?.price_points) ? pick.review.price_points : [];
    rows.forEach((point) => {
      const offset = formatValue(point.trading_day_offset);
      if (offset === "-") return;
      if (!stages.has(offset)) {
        stages.set(offset, { offset, dates: new Set() });
      }
      const date = formatValue(point.price_date);
      if (date !== "-") {
        stages.get(offset).dates.add(date);
      }
    });
  });
  return Array.from(stages.values())
    .sort((a, b) => stageOrder(a.offset) - stageOrder(b.offset) || a.offset.localeCompare(b.offset))
    .map((stage) => {
      const dates = Array.from(stage.dates).sort();
      return {
        offset: stage.offset,
        dateLabel: dates.length === 1 ? dates[0] : dates.length ? `${dates[0]} 等` : "",
      };
    });
}

function findPricePoint(points, offset) {
  const rows = Array.isArray(points) ? points : [];
  return rows.find((point) => String(point.trading_day_offset || "") === offset) || null;
}

function TruncatedText({ value, className = "" }) {
  const text = formatValue(value);
  return (
    <span className={`truncate ${className}`} title={text !== "-" ? text : ""}>
      {text}
    </span>
  );
}

function PriceChangeCell({ price, pct, date, baseline = false }) {
  const priceText = formatValue(price);
  const pctText = baseline ? "入选基准" : formatSignedPct(pct);
  const isEmpty = priceText === "-" && !baseline;
  const title = isEmpty ? "" : joinPresent([date, `价格 ${priceText}`, baseline ? "入选基准" : pctText], " / ");
  return (
    <div className={`price-cell ${baseline ? "base" : ""}`} title={title}>
      <strong>{priceText}</strong>
      <span className={baseline ? "" : changeTone(pct)}>{isEmpty ? "-" : pctText}</span>
    </div>
  );
}

function PriceSummary({ pick }) {
  return (
    <TruncatedText
      value={`入选 ${formatValue(pick.selection_price)} / 止损 ${formatValue(pick.stop_loss_price)} / 止盈 ${formatValue(pick.take_profit_price)}`}
    />
  );
}

function ReviewSummary({ reviewData, reviewStatus }) {
  const returns = reviewData.returns || {};
  const label = reviewData.result_label || reviewLabel(reviewStatus);
  const text = joinPresent([
    label,
    `T1 ${formatPct(returns.return_t1_close_pct)}`,
    `T2 ${formatPct(returns.return_t2_close_pct)}`,
    `T3 ${formatPct(returns.return_t3_close_pct)}`,
  ]);
  return <TruncatedText value={text} />;
}

function PricePointsSummary({ points }) {
  const rows = Array.isArray(points) ? points : [];
  if (!rows.length) {
    return <TruncatedText value="暂无后续价格" className="muted" />;
  }
  const text = rows
    .map((point) =>
      joinPresent([
        formatValue(point.trading_day_offset),
        formatValue(point.price_date),
        `收盘 ${formatValue(point.close)}`,
        formatSignedPct(point.return_pct),
      ], " ")
    )
    .join("；");
  return <TruncatedText value={text} />;
}

function DetailBlock({ label, value }) {
  const text = formatValue(value);
  return (
    <div className="detail-block">
      <span>{label}</span>
      <p title={text !== "-" ? text : ""}>{text}</p>
    </div>
  );
}

function PickDetailSidebar({ pick, onClose }) {
  const reviewData = pick.review || {};
  const reviewStatus = reviewData.status || "missing_review";
  const points = Array.isArray(reviewData.price_points) ? reviewData.price_points : [];
  return (
    <aside className="detail-sidebar">
      <div className="detail-sidebar-head">
        <div>
          <strong>{formatValue(pick.name)}</strong>
          <span>{formatValue(pick.stock_code || pick.symbol)}</span>
        </div>
        <button type="button" className="plain-button" onClick={onClose}>关闭</button>
      </div>

      <section className="detail-sidebar-section">
        <h3>选股信息</h3>
        <DetailBlock label="板块" value={pick.sector} />
        <DetailBlock label="买点" value={joinPresent([pick.buy_model, pick.continuation], "：")} />
        <DetailBlock label="计划" value={pick.plan} />
        <DetailBlock label="理由" value={pick.notes} />
        <DetailBlock label="风险" value={pick.risks || pick.hard_rejects} />
      </section>

      <section className="detail-sidebar-section">
        <h3>价格复盘</h3>
        <DetailBlock
          label="入选价格"
          value={`入选 ${formatValue(pick.selection_price)} / 止损 ${formatValue(pick.stop_loss_price)} / 止盈 ${formatValue(pick.take_profit_price)}`}
        />
        <DetailBlock label="复盘结果" value={reviewData.result_label || reviewLabel(reviewStatus)} />
        {points.length ? (
          <div className="sidebar-price-list">
            {points.map((point) => (
              <div key={`${point.trading_day_offset}-${point.price_date}`} className="sidebar-price-row">
                <span>{joinPresent([point.trading_day_offset, point.price_date], " · ")}</span>
                <PriceChangeCell price={point.close} pct={point.return_pct} date={point.price_date} />
              </div>
            ))}
          </div>
        ) : (
          <span className="muted">暂无后续价格</span>
        )}
      </section>
    </aside>
  );
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

function CurrentResultsTable({ picks }) {
  return (
    <section className="table-wrap">
      <table className="current-table">
        <thead>
          <tr>
            <th className="rank">排名</th>
            <th className="target-col">标的</th>
            <th className="sector-col">板块</th>
            <th className="buy-col">买点</th>
            <th className="plan-col">计划</th>
            <th className="reason-col">理由</th>
            <th className="risk-col">风险</th>
            <th className="price-col">价格</th>
            <th className="score-col">评分</th>
            <th className="decision-col">结论</th>
            <th className="review-col">复盘</th>
            <th className="price-points-col">后续价格</th>
          </tr>
        </thead>
        <tbody>
          {picks.map((pick) => {
            const reviewData = pick.review || {};
            const reviewStatus = reviewData.status || "missing_review";
            return (
              <tr key={pickKey(pick)}>
                <td className="rank">#{formatValue(pick.rank)}</td>
                <td className="target-col">
                  <div
                    className="target-line"
                    title={joinPresent([pick.name, pick.stock_code || pick.symbol], " ")}
                  >
                    <span className="name">{formatValue(pick.name)}</span>
                    <span className="code">{formatValue(pick.stock_code || pick.symbol)}</span>
                  </div>
                </td>
                <td className="sector-col"><span className="chip" title={formatValue(pick.sector)}>{formatValue(pick.sector)}</span></td>
                <td className="buy-col">
                  <TruncatedText value={joinPresent([pick.buy_model, pick.continuation], "：")} />
                </td>
                <td className="plan-col">
                  <TruncatedText value={pick.plan} />
                </td>
                <td className="reason-col">
                  <TruncatedText value={pick.notes} />
                </td>
                <td className="risk-col">
                  <TruncatedText value={pick.risks || pick.hard_rejects} />
                </td>
                <td className="price-col">
                  <PriceSummary pick={pick} />
                </td>
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
                  <ReviewSummary reviewData={reviewData} reviewStatus={reviewStatus} />
                </td>
                <td className="price-points-col">
                  <PricePointsSummary points={reviewData.price_points} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {picks.length === 0 ? <div className="empty-rows">没有匹配结果</div> : null}
    </section>
  );
}

function HistoricalResultsView({ picks, priceStages, selectedPick, onSelectPick, onCloseDetail }) {
  return (
    <section className={`history-layout ${selectedPick ? "has-detail" : ""}`}>
      <section className="table-wrap">
        <table className="history-table">
          <thead>
            <tr>
              <th className="rank">排名</th>
              <th className="target-col">标的</th>
              <th className="selection-price-col">入选价格</th>
              {priceStages.map((stage) => (
                <th key={stage.offset} className="price-stage-col">
                  <span>{stage.offset}价格</span>
                  <small>{stage.dateLabel}</small>
                </th>
              ))}
              <th className="review-col">复盘</th>
              <th className="score-col">评分</th>
              <th className="detail-action-col">详情</th>
            </tr>
          </thead>
          <tbody>
            {picks.map((pick) => {
              const reviewData = pick.review || {};
              const reviewStatus = reviewData.status || "missing_review";
              const rowKey = pickKey(pick);
              return (
                <tr
                  key={rowKey}
                  className={selectedPick && pickKey(selectedPick) === rowKey ? "selected-row" : ""}
                  onClick={() => onSelectPick(rowKey)}
                >
                  <td className="rank">#{formatValue(pick.rank)}</td>
                  <td className="target-col">
                    <div
                      className="target-line"
                      title={joinPresent([pick.name, pick.stock_code || pick.symbol], " ")}
                    >
                      <span className="name">{formatValue(pick.name)}</span>
                      <span className="code">{formatValue(pick.stock_code || pick.symbol)}</span>
                    </div>
                  </td>
                  <td className="selection-price-col">
                    <PriceChangeCell price={pick.selection_price} baseline />
                  </td>
                  {priceStages.map((stage) => {
                    const point = findPricePoint(reviewData.price_points, stage.offset);
                    return (
                      <td key={stage.offset} className="price-stage-col">
                        <PriceChangeCell price={point?.close} pct={point?.return_pct} date={point?.price_date || stage.dateLabel} />
                      </td>
                    );
                  })}
                  <td className="review-col">
                    <span className={`chip ${chipTone(reviewStatus)}`}>{formatValue(reviewData.result_label || reviewLabel(reviewStatus))}</span>
                  </td>
                  <td className="score-col">
                    <div className="score compact-score">
                      <strong>{formatValue(pick.total_score)}</strong>
                      <div className="score-line"><span style={{ width: `${scoreWidth(pick.total_score)}%` }} /></div>
                    </div>
                  </td>
                  <td className="detail-action-col">
                    <button
                      type="button"
                      className="plain-button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelectPick(rowKey);
                      }}
                    >
                      查看
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {picks.length === 0 ? <div className="empty-rows">没有匹配结果</div> : null}
      </section>
      {selectedPick ? <PickDetailSidebar pick={selectedPick} onClose={onCloseDetail} /> : null}
    </section>
  );
}

export default function App() {
  const [index, setIndex] = useState(null);
  const [detail, setDetail] = useState(null);
  const [selectedRunKey, setSelectedRunKey] = useState("");
  const [source, setSource] = useState("Supabase");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState({ keyword: "", decision: "", sector: "", model: "", minScore: "" });
  const [selectedPickKey, setSelectedPickKey] = useState("");
  const dateOptions = index?.runs || [];
  const selectedRun = useMemo(
    () => dateOptions.find((run) => runOptionValue(run) === selectedRunKey) || null,
    [dateOptions, selectedRunKey]
  );
  const selectedDate = selectedRun?.date || "";

  useEffect(() => {
    let active = true;
    setLoading(true);
    loadIndex()
      .then(({ source: dataSource, data }) => {
        if (!active) return;
        setSource(dataSource);
        setIndex(data);
        setSelectedRunKey(runOptionValue(data.runs?.[0]) || data.latest_date || "");
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
    if (!selectedRunKey || !selectedRun) return;
    let active = true;
    setLoading(true);
    loadDetail(selectedRun)
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
  }, [selectedRunKey, selectedRun]);

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

  useEffect(() => {
    setSelectedPickKey("");
  }, [selectedRunKey]);

  useEffect(() => {
    if (selectedPickKey && !picks.some((pick) => pickKey(pick) === selectedPickKey)) {
      setSelectedPickKey("");
    }
  }, [picks, selectedPickKey]);

  const metrics = detail?.metrics || {};
  const review = metrics.review || {};
  const effectiveness = detail?.strategy_effectiveness || {};
  const currentRun = detail?.run || {};
  const reviewEmpty = detail?.review?.empty_state;
  const latestDate = index?.latest_date || dateOptions[0]?.date || "";
  const priceStages = useMemo(() => getPriceStages(picks), [picks]);
  const hasPriceStages = priceStages.length > 0;
  const isHistoricalView = Boolean(hasPriceStages || (selectedDate && latestDate && selectedDate !== latestDate));
  const selectedPick = useMemo(
    () => picks.find((pick) => pickKey(pick) === selectedPickKey) || null,
    [picks, selectedPickKey]
  );

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
            <select value={selectedRunKey} onChange={(event) => setSelectedRunKey(event.target.value)}>
              {dateOptions.map((run) => (
                <option key={`${run.date}-${run.run_id}`} value={runOptionValue(run)}>
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
            <div className="results-title">
              <strong>选股明细</strong>
              <span className="view-pill">{isHistoricalView ? "历史复盘视图" : "当日选股视图"}</span>
            </div>
            <span>{picks.length} 条</span>
          </section>

          {isHistoricalView ? (
            <HistoricalResultsView
              picks={picks}
              priceStages={priceStages}
              selectedPick={selectedPick}
              onSelectPick={setSelectedPickKey}
              onCloseDetail={() => setSelectedPickKey("")}
            />
          ) : (
            <CurrentResultsTable picks={picks} />
          )}
        </>
      )}
    </main>
  );
}
