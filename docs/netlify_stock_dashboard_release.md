# Netlify stock dashboard release check

This project builds the stock dashboard from `frontend/` and reads Supabase through browser-safe public configuration in `netlify.toml`.

## Current target status

- The only Netlify project currently visible through the connector is `gorgeous-piroshki-b7058e`.
- Its live page title is `施工计划排程平台`, not `牧牛记`.
- Do not deploy this repository to that site unless the user confirms that the scheduling page should be replaced by the stock dashboard.

## Required publish checks

Before a Netlify production deploy:

1. Confirm the target Netlify site ID or URL.
2. Verify `netlify.toml` has these public build variables:
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`
   - `VITE_DASHBOARD_RUNS_INDEX_VIEW`
   - `VITE_DASHBOARD_RUN_DETAIL_VIEW`
3. Build with `npm.cmd run build` from `frontend/`.
4. Confirm the production bundle contains `stock_selection_prices` and `price_points`, and does not contain `SUPABASE_SERVICE_ROLE_KEY`.

After deploy:

1. Open the Netlify URL.
2. Confirm the source pill shows `Supabase`.
3. Select `20260623` and confirm columns:
   - `T1价格 2026-06-24`
   - `T2价格 2026-06-25`
   - `T3价格 2026-06-26`
4. Confirm the first row for `601869.SH` shows `580`, `575`, and `543`.
5. Select `20260625` and confirm `T1价格 2026-06-26` is visible.
