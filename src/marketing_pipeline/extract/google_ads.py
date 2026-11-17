"""Google Ads API extractor (live mode).

Auth: OAuth refresh token + developer token, resolved through ``get_secret``.
NOT yet verified against a live account - see README.
"""

from __future__ import annotations

from datetime import date

from ..config import Settings
from ..contracts import GOOGLE_ADS_CAMPAIGNS
from ..exceptions import ConfigurationError, ExtractionError, TransientExtractionError
from ..logging_utils import get_logger
from ..retry import retry
from ..secrets import get_secret
from .base import Extractor, Record

log = get_logger("extract.google_ads")

GAQL = """
SELECT
  segments.date, customer.id, campaign.id, campaign.name, campaign.status,
  campaign.advertising_channel_type,
  metrics.impressions, metrics.clicks, metrics.cost_micros,
  metrics.conversions, metrics.conversions_value
FROM campaign
WHERE segments.date BETWEEN '{start}' AND '{end}'
"""


class GoogleAdsExtractor(Extractor):
    def __init__(self, settings: Settings) -> None:
        super().__init__(GOOGLE_ADS_CAMPAIGNS)
        self.settings = settings

    def _client(self):
        try:
            from google.ads.googleads.client import GoogleAdsClient
        except ImportError as exc:
            raise ConfigurationError("Install the 'live' extra: pip install -e '.[live]'") from exc

        s = self.settings

        def secret(name: str) -> str:
            return get_secret(name, backend=s.secret_backend, project_id=s.gcp_project_id).reveal()

        config = {
            "developer_token": secret("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": secret("GOOGLE_ADS_CLIENT_ID"),
            "client_secret": secret("GOOGLE_ADS_CLIENT_SECRET"),
            "refresh_token": secret("GOOGLE_ADS_REFRESH_TOKEN"),
            "use_proto_plus": True,
        }
        if s.google_ads_login_customer_id:
            config["login_customer_id"] = s.google_ads_login_customer_id
        from google.auth import exceptions as auth_exc

        try:
            # Building the client exchanges the refresh token, so it can fail on its own.
            return GoogleAdsClient.load_from_dict(config)
        except auth_exc.RefreshError as exc:
            raise ExtractionError(
                "Google Ads OAuth refresh failed - check the client id/secret and refresh token"
            ) from exc
        except auth_exc.TransportError as exc:
            raise TransientExtractionError(f"Could not reach Google OAuth: {exc}") from exc

    @retry()
    def extract(self, start: date, end: date) -> list[Record]:
        from google.ads.googleads.errors import GoogleAdsException
        from google.api_core import exceptions as gexc

        service = self._client().get_service("GoogleAdsService")
        query = GAQL.format(start=start.isoformat(), end=end.isoformat())
        records: list[Record] = []
        try:
            stream = service.search_stream(
                customer_id=self.settings.google_ads_customer_id, query=query
            )
            for batch in stream:
                for row in batch.results:
                    records.append({
                        "segments_date": row.segments.date,
                        "customer_id": str(row.customer.id),
                        "campaign_id": str(row.campaign.id),
                        "campaign_name": row.campaign.name,
                        "campaign_status": row.campaign.status.name,
                        "advertising_channel_type": row.campaign.advertising_channel_type.name,
                        "impressions": str(row.metrics.impressions),
                        "clicks": str(row.metrics.clicks),
                        "cost_micros": str(row.metrics.cost_micros),
                        "conversions": str(row.metrics.conversions),
                        "conversions_value": str(row.metrics.conversions_value),
                    })
        except (gexc.ServiceUnavailable, gexc.DeadlineExceeded, gexc.ResourceExhausted,
                gexc.InternalServerError) as exc:
            raise TransientExtractionError(f"Google Ads API temporary failure: {exc}") from exc
        except GoogleAdsException as exc:
            errors = "; ".join(e.message for e in exc.failure.errors)
            raise ExtractionError(
                f"Google Ads API request {exc.request_id} failed: {errors}"
            ) from exc
        log.info("Google Ads customer %s returned %d rows",
                 self.settings.google_ads_customer_id, len(records))
        return records
