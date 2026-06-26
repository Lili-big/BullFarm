create table if not exists public.stock_selection_job_runs (
    job_id uuid primary key default gen_random_uuid(),
    trigger_source text not null default 'manual',
    target_date date,
    run_id text,
    status text not null default 'queued',
    dry_run boolean not null default false,
    request_payload jsonb not null default '{}'::jsonb,
    result_payload jsonb not null default '{}'::jsonb,
    error_message text,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint stock_selection_job_runs_status_check
        check (status in ('queued', 'running', 'success', 'pending_supabase', 'failed'))
);

create index if not exists stock_selection_job_runs_created_idx
    on public.stock_selection_job_runs (created_at desc);

create index if not exists stock_selection_job_runs_status_idx
    on public.stock_selection_job_runs (status, created_at desc);

alter table public.stock_selection_job_runs enable row level security;

drop policy if exists "Service role can manage stock selection jobs" on public.stock_selection_job_runs;
create policy "Service role can manage stock selection jobs"
    on public.stock_selection_job_runs
    for all
    to service_role
    using (true)
    with check (true);

revoke all on table public.stock_selection_job_runs from anon;
revoke all on table public.stock_selection_job_runs from authenticated;
grant select, insert, update, delete on table public.stock_selection_job_runs to service_role;
