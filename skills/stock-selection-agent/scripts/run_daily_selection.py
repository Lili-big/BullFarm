from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = Path("config/daily_selection.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "paths": {
        "snapshot_root": "data/snapshots",
        "daily_output_root": "outputs/daily",
        "latest_name": "latest",
    },
    "strategy": {
        "id": "v1_trend_startup",
        "version": "v1_0",
    },
    "live_fetch": {
        "enabled": True,
        "script": "skills/stock-selection-agent/scripts/fetch_live_candidates.py",
        "provider": "tencent_range",
        "mode": "prefilter",
        "eastmoney_route": "auto",
        "top": 100,
        "max_history": 500,
        "history_days": 150,
        "min_amount_billion": 0.5,
        "workers": 4,
        "quote_batch_size": 800,
        "include_bj": False,
        "candidate_name": "candidates.csv",
        "meta_name": "fetch_meta.json",
        "skip_live_fetch_sources": [
            "data/snapshots/{run_date}/candidates.csv",
            "data/snapshots/{run_date}_candidates.csv",
            "data/snapshots/{run_date}_tencent_range_candidates.csv",
            "data/sample_candidates.csv",
        ],
    },
    "scoring": {
        "script": "skills/stock-selection-agent/scripts/score_candidates.py",
        "config": "config/scoring_rules.json",
        "report_name": "selection_report.md",
        "scores_name": "selection_scores.csv",
    },
    "validation_snapshot": {"enabled": False, "commands": []},
    "price_update": {"enabled": False, "command": []},
    "dashboard": {"enabled": False, "command": []},
    "supabase": {"enabled": False, "command": []},
}


class DailySelectionError(RuntimeError):
    pass


class PendingSupabaseWrite(DailySelectionError):
    pass


def deep_update(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path.exists():
        with path.open("r", encoding="utf-8-sig") as handle:
            deep_update(config, json.load(handle))
    return config


def parse_date(value: str) -> str:
    text = value.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"Expected YYYYMMDD or YYYY-MM-DD, got {value!r}.")


def previous_weekday(value: datetime) -> datetime:
    current = value - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def latest_complete_market_date(run_date: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    run_dt = datetime.strptime(run_date, "%Y%m%d")
    if run_dt.weekday() >= 5:
        return previous_weekday(run_dt).strftime("%Y%m%d")
    if run_dt.date() >= now.date() and (now.hour, now.minute) < (15, 10):
        return previous_weekday(run_dt).strftime("%Y%m%d")
    return run_dt.strftime("%Y%m%d")


def resolve_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root / path


def format_template(value: str, run_date: str, as_of_date: str) -> str:
    return value.format(run_date=run_date, as_of_date=as_of_date)


def json_path(path: Path) -> str:
    return str(path)


def tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dst.resolve():
        return
    shutil.copy2(src, dst)


def replace_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    shutil.copytree(src, dst)


def stage_record(name: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": status, **extra}


def run_command(command: list[str], cwd: Path, stage: dict[str, Any]) -> None:
    stage["command"] = command
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    stage["returncode"] = result.returncode
    stage["stdout_tail"] = tail(result.stdout)
    stage["stderr_tail"] = tail(result.stderr)
    if result.returncode != 0:
        stage["status"] = "failed"
        raise DailySelectionError(f"{stage['name']} failed with exit code {result.returncode}.")
    stage["status"] = "success"


def build_live_fetch_command(
    project_root: Path,
    config: dict[str, Any],
    candidate_csv: Path,
    fetch_meta_path: Path,
    as_of_date: str,
) -> list[str]:
    live = config["live_fetch"]
    command = [
        sys.executable,
        json_path(resolve_path(project_root, live["script"])),
        "--provider",
        str(live.get("provider", live.get("source", "akshare"))),
        "--mode",
        str(live.get("mode", "prefilter")),
        "--eastmoney-route",
        str(live.get("eastmoney_route", "auto")),
        "--top",
        str(live.get("top", 100)),
        "--max-history",
        str(live.get("max_history", 500)),
        "--history-days",
        str(live.get("history_days", 150)),
        "--min-amount-billion",
        str(live.get("min_amount_billion", 0.5)),
        "--workers",
        str(live.get("workers", 1)),
        "--quote-batch-size",
        str(live.get("quote_batch_size", 800)),
    ]
    if live.get("include_bj"):
        command.append("--include-bj")
    command.extend(
        [
            "--end-date",
            as_of_date,
            "--output-csv",
            json_path(candidate_csv),
            "--meta-output",
            json_path(fetch_meta_path),
            "--overwrite",
        ]
    )
    return command


def build_score_command(
    project_root: Path,
    config: dict[str, Any],
    candidate_csv: Path,
    report_path: Path,
    scores_path: Path,
) -> list[str]:
    scoring = config["scoring"]
    return [
        sys.executable,
        json_path(resolve_path(project_root, scoring["script"])),
        "--input",
        json_path(candidate_csv),
        "--config",
        json_path(resolve_path(project_root, scoring["config"])),
        "--output",
        json_path(report_path),
        "--csv-output",
        json_path(scores_path),
        "--strategy-version",
        str(config.get("strategy", {}).get("version", "v1_0")),
    ]


def find_skip_live_fetch_source(
    project_root: Path,
    config: dict[str, Any],
    run_date: str,
    as_of_date: str,
) -> Path:
    for raw in config["live_fetch"].get("skip_live_fetch_sources", []):
        candidate = resolve_path(project_root, format_template(str(raw), run_date, as_of_date))
        if candidate.exists():
            return candidate
    raise DailySelectionError("No candidate CSV found for --skip-live-fetch.")


def handle_live_fetch(
    args: argparse.Namespace,
    project_root: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    candidate_csv: Path,
    fetch_meta_path: Path,
) -> None:
    if args.skip_live_fetch:
        stage = stage_record("live_fetch", "skipped", reason="--skip-live-fetch")
        source = find_skip_live_fetch_source(project_root, config, args.run_date, args.as_of_date)
        copy_file(source, candidate_csv)
        write_json(
            fetch_meta_path,
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "source": "skip_live_fetch",
                "copied_from": json_path(source),
                "output_csv": json_path(candidate_csv),
                "run_date": args.run_date,
                "as_of_date": args.as_of_date,
            },
        )
        stage["source_csv"] = json_path(source)
        stage["candidate_csv"] = json_path(candidate_csv)
        manifest["stages"].append(stage)
        return

    if not config["live_fetch"].get("enabled", True):
        raise DailySelectionError("Live fetch is disabled and --skip-live-fetch was not provided.")

    stage = stage_record("live_fetch", "running")
    manifest["stages"].append(stage)
    command = build_live_fetch_command(project_root, config, candidate_csv, fetch_meta_path, args.as_of_date)
    run_command(command, project_root, stage)
    stage["candidate_csv"] = json_path(candidate_csv)
    stage["fetch_meta"] = json_path(fetch_meta_path)


def handle_scoring(
    project_root: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    candidate_csv: Path,
    report_path: Path,
    scores_path: Path,
) -> None:
    stage = stage_record("score_candidates", "running")
    manifest["stages"].append(stage)
    command = build_score_command(project_root, config, candidate_csv, report_path, scores_path)
    run_command(command, project_root, stage)
    stage["report"] = json_path(report_path)
    stage["scores"] = json_path(scores_path)


def expand_command(
    raw_command: list[Any],
    project_root: Path,
    run_date: str,
    as_of_date: str,
    manifest: dict[str, Any],
) -> list[str]:
    context = {
        "python": sys.executable,
        "project_root": json_path(project_root),
        "run_date": run_date,
        "as_of_date": as_of_date,
        "run_id": str(manifest.get("run_id", "")),
        "strategy_version": str(manifest.get("strategy_version", "")),
        **manifest["paths"],
    }
    return [str(part).format(**context) for part in raw_command]


def handle_optional_command(
    name: str,
    section: dict[str, Any],
    skip: bool,
    project_root: Path,
    args: argparse.Namespace,
    manifest: dict[str, Any],
) -> None:
    if skip:
        manifest["stages"].append(stage_record(name, "skipped", reason=f"--skip-{name.replace('_', '-')}"))
        return
    if not section.get("enabled", False):
        manifest["stages"].append(stage_record(name, "skipped", reason="disabled_in_config"))
        return
    raw_commands = section.get("commands") or []
    if not raw_commands and section.get("command"):
        raw_commands = [section.get("command")]
    if not raw_commands:
        raise DailySelectionError(f"{name} is enabled but no command is configured.")
    stage = stage_record(name, "running")
    manifest["stages"].append(stage)
    stage["commands"] = []
    for raw_command in raw_commands:
        command_stage = stage_record(f"{name}:{len(stage['commands']) + 1}", "running")
        stage["commands"].append(command_stage)
        command = expand_command(raw_command, project_root, args.run_date, args.as_of_date, manifest)
        run_command(command, project_root, command_stage)
    stage["status"] = "success"


def parse_command_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def handle_supabase(
    section: dict[str, Any],
    skip: bool,
    project_root: Path,
    args: argparse.Namespace,
    manifest: dict[str, Any],
) -> None:
    name = "supabase"
    if skip:
        manifest["stages"].append(stage_record(name, "skipped", reason="--skip-supabase"))
        return
    if not section.get("enabled", False):
        manifest["stages"].append(stage_record(name, "skipped", reason="disabled_in_config"))
        return
    raw_commands = section.get("commands") or []
    if not raw_commands and section.get("command"):
        raw_commands = [section.get("command")]
    if not raw_commands:
        raise DailySelectionError("supabase is enabled but no command is configured.")

    stage = stage_record(name, "running")
    manifest["stages"].append(stage)
    stage["commands"] = []
    summaries: list[dict[str, Any]] = []
    for raw_command in raw_commands:
        command_stage = stage_record(f"{name}:{len(stage['commands']) + 1}", "running")
        stage["commands"].append(command_stage)
        command = expand_command(raw_command, project_root, args.run_date, args.as_of_date, manifest)
        command_stage["command"] = command
        result = subprocess.run(command, cwd=project_root, capture_output=True, text=True, check=False)
        command_stage["returncode"] = result.returncode
        command_stage["stdout_tail"] = tail(result.stdout)
        command_stage["stderr_tail"] = tail(result.stderr)
        summary = parse_command_json(result.stdout)
        if summary:
            command_stage["summary"] = summary
            summaries.append(summary)
        if result.returncode != 0:
            command_stage["status"] = "failed"
            raise DailySelectionError(f"{command_stage['name']} failed with exit code {result.returncode}.")
        command_stage["status"] = "success"

    stage["summaries"] = summaries
    skipped = [summary for summary in summaries if summary.get("status") == "skipped"]
    if skipped and section.get("plugin_handoff", False):
        stage["status"] = "pending_plugin_write"
        stage["reason"] = skipped[-1].get("reason")
        latest_bundle = next((summary.get("sql_bundle") for summary in reversed(summaries) if summary.get("sql_bundle")), None)
        if latest_bundle:
            stage["sql_bundle"] = latest_bundle
            manifest["supabase_sql_bundle"] = latest_bundle
        raise PendingSupabaseWrite(stage.get("reason") or "Supabase write requires plugin execution.")
    if skipped and section.get("require_write", False):
        stage["status"] = "failed"
        raise DailySelectionError(skipped[-1].get("reason") or "Supabase sync skipped.")
    stage["status"] = "success"


def planned_manifest(args: argparse.Namespace, project_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    paths = build_paths(project_root, config, args.run_date)
    manifest = base_manifest(args, paths, config)
    manifest["status"] = "planned"
    manifest["stages"] = [
        stage_record("live_fetch", "planned", skipped=args.skip_live_fetch),
        stage_record("score_candidates", "planned"),
        stage_record("validation_snapshot", "planned"),
        stage_record("price_update", "planned", skipped=args.skip_price_update),
        stage_record("dashboard", "planned"),
        stage_record("supabase", "planned", skipped=args.skip_supabase),
        stage_record("publish_latest", "planned"),
    ]
    manifest["planned_commands"] = {
        "live_fetch": build_live_fetch_command(
            project_root,
            config,
            paths["candidate_csv"],
            paths["fetch_meta"],
            args.as_of_date,
        ),
        "score_candidates": build_score_command(
            project_root,
            config,
            paths["candidate_csv"],
            paths["report"],
            paths["scores"],
        ),
    }
    return manifest


def build_paths(project_root: Path, config: dict[str, Any], run_date: str) -> dict[str, Path]:
    live = config["live_fetch"]
    scoring = config["scoring"]
    paths = config["paths"]
    snapshot_root = resolve_path(project_root, paths["snapshot_root"])
    output_root = resolve_path(project_root, paths["daily_output_root"])
    latest_name = str(paths.get("latest_name", "latest"))
    snapshot_dir = snapshot_root / run_date
    output_dir = output_root / run_date
    candidate_csv = snapshot_dir / str(live.get("candidate_name", "candidates.csv"))
    fetch_meta = snapshot_dir / str(live.get("meta_name", "fetch_meta.json"))
    report = output_dir / str(scoring.get("report_name", "selection_report.md"))
    scores = output_dir / str(scoring.get("scores_name", "selection_scores.csv"))
    manifest = output_dir / "run_manifest.json"
    return {
        "snapshot_root": snapshot_root,
        "daily_output_root": output_root,
        "snapshot_dir": snapshot_dir,
        "output_dir": output_dir,
        "candidate_csv": candidate_csv,
        "fetch_meta": fetch_meta,
        "report": report,
        "scores": scores,
        "manifest": manifest,
        "snapshot_latest": snapshot_root / latest_name,
        "output_latest": output_root / latest_name,
        "legacy_scores": project_root / "outputs" / "selection_scores.csv",
        "legacy_report": project_root / "outputs" / "selection_report.md",
        "supabase_sql_dir": output_dir / "supabase_sql",
    }


def base_manifest(args: argparse.Namespace, paths: dict[str, Path], config: dict[str, Any] | None = None) -> dict[str, Any]:
    strategy = (config or {}).get("strategy", {})
    strategy_version = str(strategy.get("version") or "v1_0")
    timestamp = datetime.now().strftime("%H%M%S")
    run_id_template = str((config or {}).get("run_id_template") or "")
    if getattr(args, "run_id", None):
        run_id = str(args.run_id)
    elif run_id_template:
        run_id = run_id_template.format(
            run_date=args.run_date,
            as_of_date=args.as_of_date,
            strategy_version=strategy_version,
            timestamp=timestamp,
        )
    else:
        run_id = f"{args.run_date}_{timestamp}_{strategy_version}"
    return {
        "status": "running",
        "run_id": run_id,
        "strategy_version": strategy_version,
        "strategy_id": str(strategy.get("id") or "v1_trend_startup"),
        "run_date": args.run_date,
        "as_of_date": args.as_of_date,
        "dry_run": bool(args.dry_run),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "flags": {
            "skip_live_fetch": bool(args.skip_live_fetch),
            "skip_supabase": bool(args.skip_supabase),
            "skip_price_update": bool(args.skip_price_update),
        },
        "paths": {key: json_path(value) for key, value in paths.items()},
        "stages": [],
    }


def publish_latest(paths: dict[str, Path], manifest: dict[str, Any]) -> None:
    stage = stage_record("publish_latest", "running")
    manifest["stages"].append(stage)
    replace_tree(paths["snapshot_dir"], paths["snapshot_latest"])
    replace_tree(paths["output_dir"], paths["output_latest"])
    copy_file(paths["scores"], paths["legacy_scores"])
    copy_file(paths["report"], paths["legacy_report"])
    stage["status"] = "success"
    stage["snapshot_latest"] = json_path(paths["snapshot_latest"])
    stage["output_latest"] = json_path(paths["output_latest"])
    stage["legacy_scores"] = json_path(paths["legacy_scores"])
    stage["legacy_report"] = json_path(paths["legacy_report"])


def run_daily_selection(args: argparse.Namespace) -> int:
    project_root = args.project_root.resolve()
    config_path = resolve_path(project_root, args.config)
    config = load_config(config_path)
    paths = build_paths(project_root, config, args.run_date)

    if args.dry_run:
        print(json.dumps(planned_manifest(args, project_root, config), ensure_ascii=False, indent=2))
        return 0

    paths["snapshot_dir"].mkdir(parents=True, exist_ok=True)
    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    manifest = base_manifest(args, paths, config)

    return_code = 1
    try:
        handle_live_fetch(args, project_root, config, manifest, paths["candidate_csv"], paths["fetch_meta"])
        handle_scoring(project_root, config, manifest, paths["candidate_csv"], paths["report"], paths["scores"])
        handle_optional_command(
            "validation_snapshot",
            config.get("validation_snapshot", {}),
            False,
            project_root,
            args,
            manifest,
        )
        handle_optional_command(
            "price_update",
            config.get("price_update", {}),
            args.skip_price_update,
            project_root,
            args,
            manifest,
        )
        handle_optional_command(
            "dashboard",
            config.get("dashboard", {}),
            False,
            project_root,
            args,
            manifest,
        )
        write_json(paths["manifest"], manifest)
        handle_supabase(config.get("supabase", {}), args.skip_supabase, project_root, args, manifest)
        manifest["status"] = "success"
        publish_latest(paths, manifest)
        return_code = 0
    except PendingSupabaseWrite as exc:
        manifest["status"] = "pending_supabase"
        manifest["pending"] = {
            "type": "supabase_plugin_write",
            "message": str(exc),
            "next_step": "Execute the SQL files listed in supabase_sql_bundle, verify public views, then run --finalize-run.",
        }
        return_code = 2
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        return_code = 1
    finally:
        manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(paths["manifest"], manifest)
        if return_code == 0 and paths["output_latest"].exists():
            copy_file(paths["manifest"], paths["output_latest"] / "run_manifest.json")

    return return_code


def finalize_run(args: argparse.Namespace) -> int:
    project_root = args.project_root.resolve()
    config_path = resolve_path(project_root, args.config)
    config = load_config(config_path)
    paths = build_paths(project_root, config, args.finalize_run)
    if not paths["manifest"].exists():
        raise DailySelectionError(f"Manifest not found: {paths['manifest']}")
    manifest = read_json(paths["manifest"])
    if args.verified_run_id and str(manifest.get("run_id")) != args.verified_run_id:
        raise DailySelectionError(
            f"Verified run_id {args.verified_run_id!r} does not match manifest run_id {manifest.get('run_id')!r}."
        )
    manifest["status"] = "success"
    manifest["supabase_verified_at"] = datetime.now().isoformat(timespec="seconds")
    manifest["stages"].append(
        stage_record(
            "supabase_plugin_verify",
            "success",
            verified_run_id=args.verified_run_id or manifest.get("run_id"),
        )
    )
    publish_latest(paths, manifest)
    manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(paths["manifest"], manifest)
    if paths["output_latest"].exists():
        copy_file(paths["manifest"], paths["output_latest"] / "run_manifest.json")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the daily stock-selection orchestration job.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Daily selection config JSON path.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT, help="Project root for relative paths.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned run without writing outputs.")
    parser.add_argument("--run-date", type=parse_date, default=datetime.now().strftime("%Y%m%d"), help="Archive date.")
    parser.add_argument("--run-id", help="Override the generated run id.")
    parser.add_argument(
        "--as-of-date",
        type=parse_date,
        help="Market data date passed to live fetch; defaults to --run-date.",
    )
    parser.add_argument("--skip-live-fetch", action="store_true", help="Use an existing or fixture candidate CSV.")
    parser.add_argument("--skip-supabase", action="store_true", help="Skip Supabase upload/publish stage.")
    parser.add_argument("--skip-price-update", action="store_true", help="Skip validation price-update stage.")
    parser.add_argument("--finalize-run", type=parse_date, help="Publish latest for a run after Supabase plugin verification.")
    parser.add_argument("--verified-run-id", help="Run id verified in Supabase before finalizing.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.finalize_run:
        return finalize_run(args)
    if args.as_of_date is None:
        args.as_of_date = latest_complete_market_date(args.run_date)
    return run_daily_selection(args)


if __name__ == "__main__":
    raise SystemExit(main())
