"""Meta Marketing API extractor (live mode): campaign-level daily insights.

Auth: a system-user access token with ads_read, resolved through ``get_secret``
and sent in the Authorization header (never in the URL, so it cannot end up in
request logs). NOT yet verified against a live ad account - see README.
"""

from __future__ import annotations

import json
from datetime import date

from ..config import Settings
from ..contracts import META_ADS_CAMPAIGNS
from ..exceptions import ConfigurationError, ExtractionError, TransientExtractionError
from ..logging_utils import get_logger
from ..retry import retry
from ..secrets import get_secret
from .base import Extractor, Record

log = get_logger("extract.meta_ads")

FIELDS = ("account_id,campaign_id,campaign_name,objective,impressions,reach,clicks,spend,"
          "actions,action_values")
# Rate-limit / temporary error codes documented for the Marketing API.
TRANSIENT_CODES = {1, 2, 4, 17, 32, 341, 613, 80000, 80004}
# Preferred purchase action types, first match wins.
PURCHASE_ACTIONS = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")
TIMEOUT_SECONDS = 60


def _purchase_metric(actions: list[dict] | None) -> str:
    by_type = {a.get("action_type"): a.get("value", "0") for a in actions or []}
    for action_type in PURCHASE_ACTIONS:
        if action_type in by_type:
            return str(by_type[action_type])
    return "0"


def flatten_insight(row: dict) -> Record:
    """Turn one API insight object into a raw record (pure function, unit tested)."""
    return {
        "date_start": row.get("date_start", ""),
        "date_stop": row.get("date_stop", ""),
        "account_id": row.get("account_id", ""),
        "campaign_id": row.get("campaign_id", ""),
        "campaign_name": row.get("campaign_name", ""),
        "objective": row.get("objective", ""),
        "impressions": row.get("impressions", "0"),
        "reach": row.get("reach", "0"),
        "clicks": row.get("clicks", "0"),
        "spend": row.get("spend", "0"),
        "purchases": _purchase_metric(row.get("actions")),
        "purchase_value": _purchase_metric(row.get("action_values")),
    }


class MetaAdsExtractor(Extractor):
    def __init__(self, settings: Settings, session=None) -> None:
        super().__init__(META_ADS_CAMPAIGNS)
        self.settings = settings
        self._session = session  # injectable for tests

    def extract(self, start: date, end: date) -> list[Record]:
        s = self.settings
        token = get_secret("META_ACCESS_TOKEN", backend=s.secret_backend,
                           project_id=s.gcp_project_id)
        url = (f"https://graph.facebook.com/{s.meta_api_version}"
               f"/act_{s.meta_ad_account_id}/insights")
        params = {
            "level": "campaign",
            "time_increment": "1",
            "time_range": json.dumps({"since": start.isoformat(), "until": end.isoformat()}),
            "fields": FIELDS,
            "limit": "500",
        }
        headers = {"Authorization": f"Bearer {token.reveal()}"}

        records: list[Record] = []
        while True:
            payload = self._get(url, params, headers)
            records.extend(flatten_insight(row) for row in payload.get("data", []))
            paging = payload.get("paging", {})
            after = paging.get("cursors", {}).get("after")
            # Page with the cursor rather than paging.next: the next URL embeds the token.
            if not after or "next" not in paging:
                break
            params = {**params, "after": after}
        log.info("Meta ad account %s returned %d rows", s.meta_ad_account_id, len(records))
        return records

    @retry()
    def _get(self, url: str, params: dict, headers: dict) -> dict:
        try:
            import requests
        except ImportError as exc:
            raise ConfigurationError("Install the 'live' extra: pip install -e '.[live]'") from exc

        session = self._session or requests
        try:
            response = session.get(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientExtractionError(f"Meta API connection problem: {exc}") from exc

        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 200 and "error" not in body:
            return body

        error = body.get("error", {})
        detail = (f"HTTP {response.status_code}, code {error.get('code')}: "
                  f"{error.get('message', 'no message')}")
        if (response.status_code in (429, 500, 502, 503, 504)
                or error.get("code") in TRANSIENT_CODES):
            raise TransientExtractionError(f"Meta API temporary failure ({detail})")
        raise ExtractionError(f"Meta API request failed ({detail})")
