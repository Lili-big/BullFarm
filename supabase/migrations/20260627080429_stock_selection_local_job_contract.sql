alter table public.stock_selection_job_runs
    add column if not exists job_type text not null default 'daily_selection',
    add column if not exists attempt_no integer not null default 1,
    add column if not exists pipeline_version text not null default 'local_v1',
    add column if not exists triggered_by text,
    add column if not exists log_excerpt text;

update public.stock_selection_job_runs
set job_type = coalesce(job_type, 'daily_selection'),
    attempt_no = coalesce(attempt_no, 1),
    pipeline_version = coalesce(pipeline_version, 'local_v1');

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'stock_selection_job_runs_job_type_check'
    ) then
        alter table public.stock_selection_job_runs
            add constraint stock_selection_job_runs_job_type_check
            check (job_type in ('daily_selection', 'price_refresh'));
    end if;
end
$$;

create index if not exists stock_selection_job_runs_type_status_idx
    on public.stock_selection_job_runs (job_type, status, created_at desc);

revoke all on table public.stock_selection_job_runs from anon;
revoke all on table public.stock_selection_job_runs from authenticated;
grant select, insert, update, delete on table public.stock_selection_job_runs to service_role;
