# Netlify + Render + Supabase Deployment

This project is now split into three deployment surfaces:

- `frontend/`: Vite static dashboard for Netlify. It reads Supabase public views with `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`.
- `backend/`: FastAPI wrapper for Render. It exposes health checks, protected manual triggers, and job status reads.
- `supabase/`: migrations for stock selection facts, dashboard views, and Render job status records.

## Environment Variables

Render keeps server-side variables in the `stock-selection-env` group from `render.yaml`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `ADMIN_TRIGGER_TOKEN`
- `APP_TIMEZONE=Asia/Shanghai`

Netlify only needs public read variables:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_DASHBOARD_RUNS_INDEX_VIEW=dashboard_runs_index`
- `VITE_DASHBOARD_RUN_DETAIL_VIEW=dashboard_runs`

Never put `SUPABASE_SERVICE_ROLE_KEY` in Netlify or frontend files.

## Render Jobs

The web service starts with:

```bash
uvicorn backend.api:app --host 0.0.0.0 --port $PORT
```

The cron job runs at `30 0 * * *` UTC, which is 08:30 in Beijing time. The wrapper computes the previous complete trading weekday, then calls the existing runner with `config/render_daily_selection.json`.

Manual trigger:

```bash
curl -X POST "$RENDER_API_URL/jobs/daily-selection" \
  -H "Authorization: Bearer $ADMIN_TRIGGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
```

Job status:

```bash
curl "$RENDER_API_URL/jobs/<job_id>" \
  -H "Authorization: Bearer $ADMIN_TRIGGER_TOKEN"
```

## Local Checks

```bash
python -m unittest discover -s tests -v
python -m backend.jobs.daily_selection --dry-run --trigger-source local
npm --prefix frontend run build
```

`config/local.env` is for local development only and is ignored by git.
