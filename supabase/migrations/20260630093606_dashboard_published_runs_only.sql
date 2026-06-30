-- Keep public dashboard views focused on published Supabase runs.
-- Local control-plane rows can exist in stock_selection_runs while a job is
-- still being tested or partially synced, but the Netlify page should not list
-- those internal batches.

create or replace view public.dashboard_runs_index
with (security_invoker = true)
as
select
    to_char(r.selection_date, 'YYYYMMDD') as date,
    r.selection_date,
    r.run_id,
    coalesce(nullif(r.market_env, ''), r.strategy_version, r.run_id) as label,
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
where exists (
    select 1
    from public.stock_selection_results published_results
    where published_results.run_id = r.run_id
)
and lower(coalesce(r.market_env, '')) not in ('local', 'stability_check', '稳定性检查', '用例文件')
and lower(coalesce(r.run_id, '')) not like '%stability_check%'
and lower(coalesce(r.run_id, '')) not like '%_local%'
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
                        ),
                        'price_points', coalesce((
                            select jsonb_agg(
                                jsonb_build_object(
                                    'trading_day_offset', pr.trading_day_offset,
                                    'price_date', pr.price_date,
                                    'close', pr.close,
                                    'return_pct', case
                                        when coalesce(p.selection_price, s.selection_price) is null
                                          or coalesce(p.selection_price, s.selection_price) = 0
                                          or pr.close is null
                                            then null
                                        else round((100.0 * (pr.close - coalesce(p.selection_price, s.selection_price)) / nullif(coalesce(p.selection_price, s.selection_price), 0))::numeric, 4)
                                    end
                                )
                                order by
                                    pr.price_date nulls last,
                                    case
                                        when upper(pr.trading_day_offset) = 'LATEST' then 999999
                                        else coalesce(nullif(regexp_replace(pr.trading_day_offset, '\D', '', 'g'), '')::integer, 999998)
                                    end
                            )
                            from public.stock_selection_prices pr
                            where pr.run_id = s.run_id
                              and pr.stock_code = s.stock_code
                              and upper(coalesce(pr.trading_day_offset, '')) not in ('T0', '0')
                        ), '[]'::jsonb)
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
from public.stock_selection_runs r
where exists (
    select 1
    from public.stock_selection_results published_results
    where published_results.run_id = r.run_id
)
and lower(coalesce(r.market_env, '')) not in ('local', 'stability_check', '稳定性检查', '用例文件')
and lower(coalesce(r.run_id, '')) not like '%stability_check%'
and lower(coalesce(r.run_id, '')) not like '%_local%';

revoke all on table public.dashboard_runs_index, public.dashboard_runs
from anon, authenticated;

grant select on table public.dashboard_runs_index, public.dashboard_runs
to anon, authenticated, service_role;
