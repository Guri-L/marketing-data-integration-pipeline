"""Raw-layer contracts: the exact shape each source must deliver.

Raw tables store every source field as STRING, exactly as the API returned it,
plus three lineage columns. Typing and cleaning happen in the staging SQL, so a
malformed value can never make a raw load fail or be silently coerced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

LINEAGE_COLUMNS = ("_run_id", "_ingested_at", "_source_system")


@dataclass(frozen=True)
class SourceContract:
    name: str                       # short source name used in logs and CLI
    raw_table: str                  # table name in the raw layer
    columns: tuple[str, ...]        # source fields, in order
    required: tuple[str, ...]       # must be present and non-empty in every row
    key: tuple[str, ...]            # natural key (one row per key per extract)
    date_column: str
    date_format: str
    synthetic_file: str

    def parse_date(self, value: str) -> date:
        return datetime.strptime(value, self.date_format).date()


GA4_SESSIONS = SourceContract(
    name="ga4",
    raw_table="ga4_sessions",
    columns=(
        "date", "session_source", "session_medium", "session_campaign_name",
        "device_category", "sessions", "total_users", "new_users",
        "engaged_sessions", "key_events", "transactions", "purchase_revenue",
    ),
    required=("date", "session_source", "session_medium", "device_category", "sessions"),
    key=("date", "session_source", "session_medium", "session_campaign_name", "device_category"),
    date_column="date",
    date_format="%Y%m%d",           # GA4 Data API returns dates as YYYYMMDD
    synthetic_file="ga4_sessions.csv",
)

GOOGLE_ADS_CAMPAIGNS = SourceContract(
    name="google_ads",
    raw_table="google_ads_campaign_performance",
    columns=(
        "segments_date", "customer_id", "campaign_id", "campaign_name", "campaign_status",
        "advertising_channel_type", "impressions", "clicks", "cost_micros",
        "conversions", "conversions_value",
    ),
    required=("segments_date", "customer_id", "campaign_id", "campaign_name", "cost_micros"),
    key=("segments_date", "customer_id", "campaign_id"),
    date_column="segments_date",
    date_format="%Y-%m-%d",
    synthetic_file="google_ads_campaign_performance.csv",
)

META_ADS_CAMPAIGNS = SourceContract(
    name="meta_ads",
    raw_table="meta_ads_campaign_insights",
    columns=(
        "date_start", "date_stop", "account_id", "campaign_id", "campaign_name", "objective",
        "impressions", "reach", "clicks", "spend", "purchases", "purchase_value",
    ),
    required=("date_start", "account_id", "campaign_id", "campaign_name", "spend"),
    key=("date_start", "account_id", "campaign_id"),
    date_column="date_start",
    date_format="%Y-%m-%d",
    synthetic_file="meta_ads_campaign_insights.csv",
)

CONTRACTS: dict[str, SourceContract] = {
    c.name: c for c in (GA4_SESSIONS, GOOGLE_ADS_CAMPAIGNS, META_ADS_CAMPAIGNS)
}
