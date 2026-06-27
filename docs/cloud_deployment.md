# Legacy Netlify + Render + Supabase Deployment

This document is retained only as a legacy reference. The active production path is now documented in `docs/local_automation_architecture.md`.

The previous architecture used:

- Netlify for `frontend/`
- Render Web Service for `backend.api:app`
- Render Cron for the daily stock-selection job
- Supabase as the database and public dashboard read source

That path has been downgraded because the current target architecture keeps execution and Supabase writes on the local machine, with Codex automations only waking and triggering local jobs.

Do not treat `render.yaml` or `config/render_daily_selection.json` as the primary production path for new work. They remain useful only for historical comparison or a future cloud redeployment.

## Legacy Commands

Historical Render web service start command:

```bash
uvicorn backend.api:app --host 0.0.0.0 --port $PORT
```

Historical Render cron command:

```bash
python -m backend.jobs.daily_selection --trigger-source cron
```

## Current Replacement

Use these local commands instead:

```powershell
python -m backend.jobs.daily_selection --trigger-source codex_automation
python -m backend.jobs.price_refresh --trigger-source codex_automation
```

For details, see `docs/local_automation_architecture.md`.
