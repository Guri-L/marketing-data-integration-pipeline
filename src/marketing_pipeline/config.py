"""Runtime settings, read once from environment variables (optionally via .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from .exceptions import ConfigurationError

REPO_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = REPO_ROOT / "sql"
CONFIG_DIR = REPO_ROOT / "config"
SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"

# Fixed window covered by the committed synthetic datasets.
SYNTHETIC_START = date(2026, 8, 1)
SYNTHETIC_END = date(2026, 10, 31)

# Live runs re-fetch a trailing window because ad platforms restate recent days
# (late conversions, invalid-click credits). Staging keeps the latest version.
DEFAULT_LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class Settings:
    mode: str = "synthetic"
    warehouse: str = "duckdb"
    log_level: str = "INFO"
    log_format: str = "text"
    duckdb_path: str = "artifacts/warehouse.duckdb"
    landing_dir: str = "data/landing"
    artifacts_dir: str = "artifacts"
    gcp_project_id: str = ""
    bq_location: str = "EU"
    bq_dataset_raw: str = "marketing_raw"
    bq_dataset_staging: str = "marketing_staging"
    bq_dataset_reporting: str = "marketing_reporting"
    secret_backend: str = "env"  # noqa: S105 - backend name, not a secret
    ga4_property_id: str = ""
    google_ads_customer_id: str = ""
    google_ads_login_customer_id: str = ""
    meta_ad_account_id: str = ""
    meta_api_version: str = ""

    @classmethod
    def from_env(cls, env_file: str | os.PathLike[str] | None = None) -> Settings:
        load_dotenv(env_file or REPO_ROOT / ".env", override=False)

        def env(name: str, default: str = "") -> str:
            return os.environ.get(name, default).strip() or default

        settings = cls(
            mode=env("PIPELINE_MODE", "synthetic").lower(),
            warehouse=env("WAREHOUSE", "duckdb").lower(),
            log_level=env("LOG_LEVEL", "INFO").upper(),
            log_format=env("LOG_FORMAT", "text").lower(),
            duckdb_path=env("DUCKDB_PATH", "artifacts/warehouse.duckdb"),
            landing_dir=env("LANDING_DIR", "data/landing"),
            artifacts_dir=env("ARTIFACTS_DIR", "artifacts"),
            gcp_project_id=env("GCP_PROJECT_ID"),
            bq_location=env("BQ_LOCATION", "EU"),
            bq_dataset_raw=env("BQ_DATASET_RAW", "marketing_raw"),
            bq_dataset_staging=env("BQ_DATASET_STAGING", "marketing_staging"),
            bq_dataset_reporting=env("BQ_DATASET_REPORTING", "marketing_reporting"),
            secret_backend=env("SECRET_BACKEND", "env").lower(),
            ga4_property_id=env("GA4_PROPERTY_ID"),
            google_ads_customer_id=env("GOOGLE_ADS_CUSTOMER_ID").replace("-", ""),
            google_ads_login_customer_id=env("GOOGLE_ADS_LOGIN_CUSTOMER_ID").replace("-", ""),
            meta_ad_account_id=env("META_AD_ACCOUNT_ID").removeprefix("act_"),
            meta_api_version=env("META_API_VERSION"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Fail fast, before any network call, with every problem listed at once."""
        problems: list[str] = []
        if self.mode not in ("synthetic", "live"):
            problems.append(f"PIPELINE_MODE must be synthetic or live, got {self.mode!r}")
        if self.warehouse not in ("duckdb", "bigquery"):
            problems.append(f"WAREHOUSE must be duckdb or bigquery, got {self.warehouse!r}")
        if self.log_format not in ("text", "json"):
            problems.append(f"LOG_FORMAT must be text or json, got {self.log_format!r}")
        if self.warehouse == "bigquery" and not self.gcp_project_id:
            problems.append("GCP_PROJECT_ID is required when WAREHOUSE=bigquery")
        if self.mode == "live":
            required = {
                "GA4_PROPERTY_ID": self.ga4_property_id,
                "GOOGLE_ADS_CUSTOMER_ID": self.google_ads_customer_id,
                "META_AD_ACCOUNT_ID": self.meta_ad_account_id,
                "META_API_VERSION": self.meta_api_version,
            }
            problems += [
                f"{k} is required when PIPELINE_MODE=live" for k, v in required.items() if not v
            ]
        if problems:
            raise ConfigurationError("Invalid configuration:\n  - " + "\n  - ".join(problems))

    def default_window(self, today: date | None = None) -> tuple[date, date]:
        """Date range a run covers when none is given on the command line."""
        if self.mode == "synthetic":
            return SYNTHETIC_START, SYNTHETIC_END
        end = (today or date.today()) - timedelta(days=1)
        return end - timedelta(days=DEFAULT_LOOKBACK_DAYS - 1), end
