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

revoke all on table public.v_selection_strategy_effectiveness_public
from anon, authenticated;

grant select on table public.v_selection_strategy_effectiveness_public
to anon, authenticated, service_role;
