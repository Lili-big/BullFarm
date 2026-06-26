create table if not exists public.stock_selection_runs (
    run_id text primary key,
    selection_date date not null,
    selection_time time,
    strategy_version text not null default 'v1_0',
    market_env text,
    total_selected_count integer not null default 0,
    data_source text,
    source_provider text,
    source_snapshot text,
    source_metadata jsonb not null default '{}'::jsonb,
    dashboard jsonb not null default '{}'::jsonb,
    report_markdown text,
    operator text,
    notes text,
    generated_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.stock_selection_results (
    run_id text not null references public.stock_selection_runs(run_id) on delete cascade,
    stock_code text not null,
    symbol text,
    stock_name text not null,
    sector text,
    rank_in_run integer,
    total_score integer,
    trend_score integer,
    startup_score integer,
    sector_score integer,
    market_score integer,
    decision text,
    continuation text,
    buy_model text,
    notes text,
    risks text,
    hard_rejects text,
    plan text,
    selection_price numeric,
    stop_loss_price numeric,
    take_profit_price numeric,
    candidate_payload jsonb not null default '{}'::jsonb,
    score_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (run_id, stock_code)
);

create table if not exists public.stock_selection_prices (
    run_id text not null references public.stock_selection_runs(run_id) on delete cascade,
    stock_code text not null,
    stock_name text,
    selection_date date,
    trading_day_offset text not null,
    price_date date,
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume numeric,
    amount numeric,
    turnover_rate numeric,
    is_suspended boolean not null default false,
    data_source text,
    price_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (run_id, stock_code, trading_day_offset)
);

create table if not exists public.stock_selection_performance (
    run_id text not null references public.stock_selection_runs(run_id) on delete cascade,
    stock_code text not null,
    stock_name text,
    selection_date date,
    sector text,
    industry text,
    concept text,
    strategy_label text,
    participation_level text,
    total_score integer,
    rank_in_run integer,
    selection_price numeric,
    latest_price numeric,
    latest_price_date date,
    return_latest_pct numeric,
    return_t1_close_pct numeric,
    return_t2_close_pct numeric,
    return_t3_close_pct numeric,
    return_t5_close_pct numeric,
    return_t10_close_pct numeric,
    max_high_3d numeric,
    max_gain_3d_pct numeric,
    min_low_3d numeric,
    max_drawdown_3d_pct numeric,
    max_high_5d numeric,
    max_gain_5d_pct numeric,
    min_low_5d numeric,
    max_drawdown_5d_pct numeric,
    hit_stop_loss boolean,
    hit_take_profit boolean,
    uncertain_intraday_order boolean,
    is_profitable_latest boolean,
    is_profitable_t1 boolean,
    is_profitable_t2 boolean,
    is_profitable_t3 boolean,
    is_profitable_t5 boolean,
    result_label text,
    failure_reason text,
    data_status text,
    performance_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (run_id, stock_code)
);

create index if not exists stock_selection_runs_selection_date_idx
    on public.stock_selection_runs (selection_date desc);

create index if not exists stock_selection_results_rank_idx
    on public.stock_selection_results (run_id, rank_in_run);

create index if not exists stock_selection_results_stock_code_idx
    on public.stock_selection_results (stock_code);

create index if not exists stock_selection_prices_stock_date_idx
    on public.stock_selection_prices (stock_code, price_date desc);

create index if not exists stock_selection_performance_result_idx
    on public.stock_selection_performance (selection_date desc, result_label);

alter table public.stock_selection_runs
    add column if not exists source_provider text;

alter table public.stock_selection_results
    add column if not exists selection_price numeric,
    add column if not exists stop_loss_price numeric,
    add column if not exists take_profit_price numeric;

alter table public.stock_selection_runs enable row level security;
alter table public.stock_selection_results enable row level security;
alter table public.stock_selection_prices enable row level security;
alter table public.stock_selection_performance enable row level security;

drop policy if exists "Public can read stock selection runs" on public.stock_selection_runs;
create policy "Public can read stock selection runs"
    on public.stock_selection_runs
    for select
    to anon, authenticated
    using (true);

drop policy if exists "Service role can write stock selection runs" on public.stock_selection_runs;
create policy "Service role can write stock selection runs"
    on public.stock_selection_runs
    for all
    to service_role
    using (true)
    with check (true);

drop policy if exists "Public can read stock selection results" on public.stock_selection_results;
create policy "Public can read stock selection results"
    on public.stock_selection_results
    for select
    to anon, authenticated
    using (true);

drop policy if exists "Service role can write stock selection results" on public.stock_selection_results;
create policy "Service role can write stock selection results"
    on public.stock_selection_results
    for all
    to service_role
    using (true)
    with check (true);

drop policy if exists "Public can read stock selection prices" on public.stock_selection_prices;
create policy "Public can read stock selection prices"
    on public.stock_selection_prices
    for select
    to anon, authenticated
    using (true);

drop policy if exists "Service role can write stock selection prices" on public.stock_selection_prices;
create policy "Service role can write stock selection prices"
    on public.stock_selection_prices
    for all
    to service_role
    using (true)
    with check (true);

drop policy if exists "Public can read stock selection performance" on public.stock_selection_performance;
create policy "Public can read stock selection performance"
    on public.stock_selection_performance
    for select
    to anon, authenticated
    using (true);

drop policy if exists "Service role can write stock selection performance" on public.stock_selection_performance;
create policy "Service role can write stock selection performance"
    on public.stock_selection_performance
    for all
    to service_role
    using (true)
    with check (true);

create or replace view public.stock_selection_public_runs
with (security_invoker = true)
as
select
    run_id,
    selection_date,
    selection_time,
    strategy_version,
    market_env,
    total_selected_count,
    source_provider as data_source,
    generated_at,
    created_at,
    updated_at
from public.stock_selection_runs;

create or replace view public.stock_selection_public_results
with (security_invoker = true)
as
select
    r.run_id,
    runs.selection_date,
    r.stock_code,
    r.symbol,
    r.stock_name,
    r.sector,
    r.rank_in_run,
    r.total_score,
    r.trend_score,
    r.startup_score,
    r.sector_score,
    r.market_score,
    r.decision,
    r.continuation,
    r.buy_model,
    r.notes,
    r.risks,
    r.plan,
    r.selection_price,
    r.stop_loss_price,
    r.take_profit_price,
    p.latest_price,
    p.latest_price_date,
    p.return_latest_pct,
    p.return_t1_close_pct,
    p.return_t2_close_pct,
    p.return_t3_close_pct,
    p.result_label,
    p.data_status
from public.stock_selection_results r
join public.stock_selection_runs runs on runs.run_id = r.run_id
left join public.stock_selection_performance p
    on p.run_id = r.run_id
   and p.stock_code = r.stock_code;

create or replace view public.stock_selection_public_performance_by_run
with (security_invoker = true)
as
select
    runs.run_id,
    runs.selection_date,
    runs.strategy_version,
    runs.market_env,
    count(p.stock_code) as evaluated_count,
    count(*) filter (where p.return_t3_close_pct is not null) as valid_t3_count,
    count(*) filter (where p.return_t3_close_pct > 0) as profitable_t3_count,
    round(avg(p.return_t1_close_pct), 4) as avg_return_t1_pct,
    round(avg(p.return_t2_close_pct), 4) as avg_return_t2_pct,
    round(avg(p.return_t3_close_pct), 4) as avg_return_t3_pct,
    round(avg(p.max_drawdown_3d_pct), 4) as avg_max_drawdown_3d_pct,
    round(
        100.0 * count(*) filter (where p.return_t3_close_pct > 0)
        / nullif(count(*) filter (where p.return_t3_close_pct is not null), 0),
        4
    ) as win_rate_t3_pct
from public.stock_selection_runs runs
left join public.stock_selection_performance p on p.run_id = runs.run_id
group by runs.run_id, runs.selection_date, runs.strategy_version, runs.market_env;

create or replace view public.v_selection_runs_public
with (security_invoker = true)
as
select *
from public.stock_selection_public_runs;

create or replace view public.v_selection_results_public
with (security_invoker = true)
as
select *
from public.stock_selection_public_results;

create or replace view public.v_selection_performance_public
with (security_invoker = true)
as
select
    p.run_id,
    runs.selection_date,
    p.stock_code,
    p.stock_name,
    p.sector,
    p.industry,
    p.concept,
    p.strategy_label,
    p.participation_level,
    p.total_score,
    p.rank_in_run,
    p.selection_price,
    p.latest_price,
    p.latest_price_date,
    p.return_latest_pct,
    p.return_t1_close_pct,
    p.return_t2_close_pct,
    p.return_t3_close_pct,
    p.return_t5_close_pct,
    p.return_t10_close_pct,
    p.max_gain_3d_pct,
    p.max_drawdown_3d_pct,
    p.hit_stop_loss,
    p.hit_take_profit,
    p.result_label,
    p.failure_reason,
    p.data_status
from public.stock_selection_performance p
join public.stock_selection_runs runs on runs.run_id = p.run_id;

create or replace view public.v_selection_summary_by_run_public
with (security_invoker = true)
as
select *
from public.stock_selection_public_performance_by_run;

create or replace view public.v_selection_strategy_effectiveness_public
with (security_invoker = true)
as
select
    runs.strategy_version,
    count(distinct runs.run_id) as run_count,
    count(distinct p.run_id) as reviewed_run_count,
    count(*) filter (where coalesce(p.return_t3_close_pct, p.return_latest_pct) is not null) as valid_stock_count,
    round(
        100.0 * count(*) filter (where p.return_t3_close_pct > 0)
        / nullif(count(*) filter (where p.return_t3_close_pct is not null), 0),
        4
    ) as win_rate_t3,
    round(avg(p.return_latest_pct)::numeric, 4) as avg_return_latest_pct,
    round(avg(p.return_t3_close_pct)::numeric, 4) as avg_return_t3_pct,
    round(avg(p.max_drawdown_3d_pct)::numeric, 4) as avg_max_drawdown_3d_pct,
    count(*) filter (where p.hit_stop_loss is true) as hit_stop_loss_count,
    count(*) filter (where p.hit_take_profit is true) as hit_take_profit_count,
    case
        when count(*) filter (where coalesce(p.return_t3_close_pct, p.return_latest_pct) is not null) = 0 then '样本不足'
        when avg(p.return_t3_close_pct) > 0
             and (
                100.0 * count(*) filter (where p.return_t3_close_pct > 0)
                / nullif(count(*) filter (where p.return_t3_close_pct is not null), 0)
             ) >= 50 then '正向验证'
        when avg(p.return_t3_close_pct) > 0 then '小样本正收益'
        when count(*) filter (where p.return_t3_close_pct is not null) = 0
             and avg(p.return_latest_pct) > 0 then '最新价正向，等待T3'
        when count(*) filter (where p.return_t3_close_pct is not null) = 0 then '最新价回撤，等待T3'
        else '需要优化'
    end as conclusion,
    round(
        100.0 * count(*) filter (where p.return_latest_pct > 0)
        / nullif(count(*) filter (where p.return_latest_pct is not null), 0),
        4
    ) as win_rate_latest
from public.stock_selection_runs runs
left join public.stock_selection_performance p on p.run_id = runs.run_id
group by runs.strategy_version;

create or replace view public.dashboard_runs_index
with (security_invoker = true)
as
select
    to_char(r.selection_date, 'YYYYMMDD') as date,
    r.selection_date,
    r.run_id,
    coalesce(r.market_env, r.strategy_version, r.run_id) as label,
    r.market_env,
    r.total_selected_count,
    max(s.total_score) as top_score,
    round(avg(s.total_score)::numeric, 2) as average_score,
    jsonb_build_object(
        'strong', count(*) filter (where s.total_score >= 80),
        'trial', count(*) filter (where s.total_score >= 65 and s.total_score < 80),
        'watch', count(*) filter (where s.total_score >= 50 and s.total_score < 65),
        'avoid', count(*) filter (where s.total_score < 50),
        'unknown', count(*) filter (where s.total_score is null)
    ) as score_buckets,
    exists (
        select 1
        from public.stock_selection_performance p
        where p.run_id = r.run_id
    ) as has_review,
    case
        when exists (
            select 1
            from public.stock_selection_performance p
            where p.run_id = r.run_id
        ) then 'partial_review'
        else 'missing_review'
    end as review_status,
    1 as run_count,
    'runs/' || to_char(r.selection_date, 'YYYYMMDD') || '.json' as json_path
from public.stock_selection_runs r
left join public.stock_selection_results s on s.run_id = r.run_id
group by r.run_id, r.selection_date, r.strategy_version, r.market_env, r.total_selected_count;

create or replace view public.dashboard_runs
with (security_invoker = true)
as
select
    to_char(r.selection_date, 'YYYYMMDD') as date,
    r.run_id,
    jsonb_build_object(
        'schema_version', 1,
        'generated_at', coalesce(r.generated_at::text, r.created_at::text),
        'date', to_char(r.selection_date, 'YYYYMMDD'),
        'selection_date', to_char(r.selection_date, 'YYYY-MM-DD'),
        'active_run_id', r.run_id,
        'run_choices', jsonb_build_array(jsonb_build_object(
            'run_id', r.run_id,
            'selection_time', r.selection_time,
            'market_env', r.market_env,
            'total_selected_count', r.total_selected_count,
            'review_status', case
                when exists (select 1 from public.stock_selection_performance p where p.run_id = r.run_id)
                    then 'partial_review'
                else 'missing_review'
            end
        )),
        'run', jsonb_build_object(
            'run_id', r.run_id,
            'selection_date', to_char(r.selection_date, 'YYYY-MM-DD'),
            'selection_time', r.selection_time,
            'strategy_version', r.strategy_version,
            'market_env', r.market_env,
            'total_selected_count', r.total_selected_count,
            'data_source', r.source_provider
        ),
        'metrics', jsonb_build_object(
            'selected_count', coalesce((select count(*) from public.stock_selection_results s where s.run_id = r.run_id), 0),
            'top_score', (select max(s.total_score) from public.stock_selection_results s where s.run_id = r.run_id),
            'average_score', (select round(avg(s.total_score)::numeric, 2) from public.stock_selection_results s where s.run_id = r.run_id),
            'sector_count', (select count(distinct s.sector) from public.stock_selection_results s where s.run_id = r.run_id),
            'decision_counts', coalesce((
                select jsonb_object_agg(decision_name, decision_count)
                from (
                    select coalesce(s.decision, 'unknown') as decision_name, count(*) as decision_count
                    from public.stock_selection_results s
                    where s.run_id = r.run_id
                    group by coalesce(s.decision, 'unknown')
                ) d
            ), '{}'::jsonb),
            'score_buckets', jsonb_build_object(
                'strong', (select count(*) from public.stock_selection_results s where s.run_id = r.run_id and s.total_score >= 80),
                'trial', (select count(*) from public.stock_selection_results s where s.run_id = r.run_id and s.total_score >= 65 and s.total_score < 80),
                'watch', (select count(*) from public.stock_selection_results s where s.run_id = r.run_id and s.total_score >= 50 and s.total_score < 65),
                'avoid', (select count(*) from public.stock_selection_results s where s.run_id = r.run_id and s.total_score < 50),
                'unknown', (select count(*) from public.stock_selection_results s where s.run_id = r.run_id and s.total_score is null)
            ),
            'review_status', case
                when exists (select 1 from public.stock_selection_performance p where p.run_id = r.run_id)
                    then 'partial_review'
                else 'missing_review'
            end,
            'review_has_data', exists (select 1 from public.stock_selection_performance p where p.run_id = r.run_id),
            'review', coalesce((
                select jsonb_build_object(
                    'valid_stock_count', count(*) filter (where p.return_t3_close_pct is not null),
                    'win_rate_t3', round(100.0 * count(*) filter (where p.return_t3_close_pct > 0) / nullif(count(*) filter (where p.return_t3_close_pct is not null), 0), 4),
                    'avg_return_t3_pct', round(avg(p.return_t3_close_pct)::numeric, 4)
                )
                from public.stock_selection_performance p
                where p.run_id = r.run_id
            ), '{}'::jsonb)
        ),
        'strategy_effectiveness', coalesce((
            select to_jsonb(e) - 'strategy_version'
            from public.v_selection_strategy_effectiveness_public e
            where e.strategy_version = r.strategy_version
        ), '{}'::jsonb),
        'filters', jsonb_build_object(
            'decisions', coalesce((
                select jsonb_agg(jsonb_build_object('value', item_value, 'count', item_count) order by item_count desc, item_value)
                from (
                    select coalesce(s.decision, 'unknown') as item_value, count(*) as item_count
                    from public.stock_selection_results s
                    where s.run_id = r.run_id
                    group by coalesce(s.decision, 'unknown')
                ) items
            ), '[]'::jsonb),
            'sectors', coalesce((
                select jsonb_agg(jsonb_build_object('value', item_value, 'count', item_count) order by item_count desc, item_value)
                from (
                    select coalesce(s.sector, 'unknown') as item_value, count(*) as item_count
                    from public.stock_selection_results s
                    where s.run_id = r.run_id
                    group by coalesce(s.sector, 'unknown')
                ) items
            ), '[]'::jsonb),
            'buy_models', coalesce((
                select jsonb_agg(jsonb_build_object('value', item_value, 'count', item_count) order by item_count desc, item_value)
                from (
                    select coalesce(s.buy_model, 'unknown') as item_value, count(*) as item_count
                    from public.stock_selection_results s
                    where s.run_id = r.run_id
                    group by coalesce(s.buy_model, 'unknown')
                ) items
            ), '[]'::jsonb)
        ),
        'review', jsonb_build_object(
            'has_review', exists (select 1 from public.stock_selection_performance p where p.run_id = r.run_id),
            'status', case
                when exists (select 1 from public.stock_selection_performance p where p.run_id = r.run_id)
                    then 'partial_review'
                else 'missing_review'
            end,
            'empty_state', case
                when exists (select 1 from public.stock_selection_performance p where p.run_id = r.run_id)
                    then null
                else jsonb_build_object('title', 'No review data yet', 'message', 'Price update and analysis will fill this section.')
            end
        ),
        'picks', coalesce((
            select jsonb_agg(
                jsonb_build_object(
                    'rank', s.rank_in_run,
                    'symbol', s.symbol,
                    'stock_code', s.stock_code,
                    'name', s.stock_name,
                    'sector', s.sector,
                    'total_score', s.total_score,
                    'trend_score', s.trend_score,
                    'startup_score', s.startup_score,
                    'sector_score', s.sector_score,
                    'market_score', s.market_score,
                    'decision', s.decision,
                    'continuation', s.continuation,
                    'buy_model', s.buy_model,
                    'notes', s.notes,
                    'risks', s.risks,
                    'hard_rejects', s.hard_rejects,
                    'plan', s.plan,
                    'selection_price', s.selection_price,
                    'stop_loss_price', s.stop_loss_price,
                    'take_profit_price', s.take_profit_price,
                    'review', jsonb_build_object(
                        'status', coalesce(p.data_status, 'missing_review'),
                        'result_label', p.result_label,
                        'latest_price', p.latest_price,
                        'latest_price_date', p.latest_price_date,
                        'returns', jsonb_build_object(
                            'return_latest_pct', p.return_latest_pct,
                            'return_t1_close_pct', p.return_t1_close_pct,
                            'return_t2_close_pct', p.return_t2_close_pct,
                            'return_t3_close_pct', p.return_t3_close_pct
                        )
                    )
                )
                order by s.rank_in_run nulls last, s.stock_code
            )
            from public.stock_selection_results s
            left join public.stock_selection_performance p
              on p.run_id = s.run_id and p.stock_code = s.stock_code
            where s.run_id = r.run_id
        ), '[]'::jsonb)
    ) as payload
from public.stock_selection_runs r;

grant usage on schema public to anon, authenticated, service_role;

revoke all on table
    public.stock_selection_runs,
    public.stock_selection_results,
    public.stock_selection_prices,
    public.stock_selection_performance
from anon, authenticated;

grant select (
    run_id,
    selection_date,
    selection_time,
    strategy_version,
    market_env,
    total_selected_count,
    source_provider,
    generated_at,
    created_at,
    updated_at
) on table public.stock_selection_runs to anon, authenticated;

grant select (
    run_id,
    stock_code,
    symbol,
    stock_name,
    sector,
    rank_in_run,
    total_score,
    trend_score,
    startup_score,
    sector_score,
    market_score,
    decision,
    continuation,
    buy_model,
    notes,
    risks,
    hard_rejects,
    plan,
    selection_price,
    stop_loss_price,
    take_profit_price,
    created_at,
    updated_at
) on table public.stock_selection_results to anon, authenticated;

grant select (
    run_id,
    stock_code,
    stock_name,
    selection_date,
    trading_day_offset,
    price_date,
    open,
    high,
    low,
    close,
    volume,
    amount,
    turnover_rate,
    is_suspended,
    data_source,
    created_at,
    updated_at
) on table public.stock_selection_prices to anon, authenticated;

grant select (
    run_id,
    stock_code,
    stock_name,
    selection_date,
    sector,
    industry,
    concept,
    strategy_label,
    participation_level,
    total_score,
    rank_in_run,
    selection_price,
    latest_price,
    latest_price_date,
    return_latest_pct,
    return_t1_close_pct,
    return_t2_close_pct,
    return_t3_close_pct,
    return_t5_close_pct,
    return_t10_close_pct,
    max_high_3d,
    max_gain_3d_pct,
    min_low_3d,
    max_drawdown_3d_pct,
    max_high_5d,
    max_gain_5d_pct,
    min_low_5d,
    max_drawdown_5d_pct,
    hit_stop_loss,
    hit_take_profit,
    uncertain_intraday_order,
    is_profitable_latest,
    is_profitable_t1,
    is_profitable_t2,
    is_profitable_t3,
    is_profitable_t5,
    result_label,
    failure_reason,
    data_status,
    created_at,
    updated_at
) on table public.stock_selection_performance to anon, authenticated;

grant select, insert, update, delete on table
    public.stock_selection_runs,
    public.stock_selection_results,
    public.stock_selection_prices,
    public.stock_selection_performance
to service_role;

revoke all on table
    public.stock_selection_public_runs,
    public.stock_selection_public_results,
    public.stock_selection_public_performance_by_run,
    public.v_selection_runs_public,
    public.v_selection_results_public,
    public.v_selection_performance_public,
    public.v_selection_summary_by_run_public,
    public.v_selection_strategy_effectiveness_public,
    public.dashboard_runs_index,
    public.dashboard_runs
from anon, authenticated;

grant select on table
    public.stock_selection_public_runs,
    public.stock_selection_public_results,
    public.stock_selection_public_performance_by_run,
    public.v_selection_runs_public,
    public.v_selection_results_public,
    public.v_selection_performance_public,
    public.v_selection_summary_by_run_public,
    public.v_selection_strategy_effectiveness_public,
    public.dashboard_runs_index,
    public.dashboard_runs
to anon, authenticated, service_role;
