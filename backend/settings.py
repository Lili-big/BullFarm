from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_ENV = PROJECT_ROOT / "config" / "local.env"


def parse_env_file(path: Path = DEFAULT_LOCAL_ENV) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_env(local_env: Path = DEFAULT_LOCAL_ENV) -> dict[str, str]:
    merged = dict(os.environ)
    for key, value in parse_env_file(local_env).items():
        merged.setdefault(key, value)
    return merged


@dataclass(frozen=True)
class AppSettings:
    project_root: Path
    app_timezone: str
    admin_trigger_token: str
    job_store_path: Path

    @property
    def has_admin_token(self) -> bool:
        return bool(self.admin_trigger_token)


def get_settings() -> AppSettings:
    env = load_env()
    job_store_path = Path(env.get("JOB_STORE_PATH", PROJECT_ROOT / "outputs" / "jobs" / "job_runs.json"))
    if not job_store_path.is_absolute():
        job_store_path = PROJECT_ROOT / job_store_path
    return AppSettings(
        project_root=PROJECT_ROOT,
        app_timezone=env.get("APP_TIMEZONE", "Asia/Shanghai"),
        admin_trigger_token=env.get("ADMIN_TRIGGER_TOKEN", ""),
        job_store_path=job_store_path,
    )
