"""GA4 Data API extractor (live mode).

Auth: Application Default Credentials. The identity needs Viewer access on the
GA4 property. NOT yet verified against a live property - see README.
"""

from __future__ import annotations

from datetime import date

from ..config import Settings
from ..contracts import GA4_SESSIONS
from ..exceptions import ConfigurationError, ExtractionError, TransientExtractionError
from ..logging_utils import get_logger
from ..retry import retry
from .base import Extractor, Record

log = get_logger("extract.ga4")

# API name -> raw column. Order matches the request.
DIMENSIONS = {
    "date": "date",
    "sessionSource": "session_source",
    "sessionMedium": "session_medium",
    "sessionCampaignName": "session_campaign_name",
    "deviceCategory": "device_category",
}
METRICS = {
    "sessions": "sessions",
    "totalUsers": "total_users",
    "newUsers": "new_users",
    "engagedSessions": "engaged_sessions",
    "keyEvents": "key_events",
    "transactions": "transactions",
    "purchaseRevenue": "purchase_revenue",
}
PAGE_SIZE = 100_000


class Ga4Extractor(Extractor):
    def __init__(self, settings: Settings) -> None:
        super().__init__(GA4_SESSIONS)
        self.property_id = settings.ga4_property_id

    def extract(self, start: date, end: date) -> list[Record]:
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
        except ImportError as exc:
            raise ConfigurationError("Install the 'live' extra: pip install -e '.[live]'") from exc

        client = BetaAnalyticsDataClient()
        records: list[Record] = []
        offset = 0
        while True:
            response = self._run_report(client, start, end, offset)
            for row in response.rows:
                values = [v.value for v in row.dimension_values]
                values += [v.value for v in row.metric_values]
                records.append(dict(zip([*DIMENSIONS.values(), *METRICS.values()], values,
                                        strict=True)))
            offset += PAGE_SIZE
            if offset >= response.row_count:
                break
        log.info("GA4 property %s returned %d rows", self.property_id, len(records))
        return records

    @retry()
    def _run_report(self, client, start: date, end: date, offset: int):
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Metric,
            RunReportRequest,
        )
        from google.api_core import exceptions as gexc

        request = RunReportRequest(
            property=f"properties/{self.property_id}",
            dimensions=[Dimension(name=n) for n in DIMENSIONS],
            metrics=[Metric(name=n) for n in METRICS],
            date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
            limit=PAGE_SIZE,
            offset=offset,
        )
        try:
            return client.run_report(request)
        except (gexc.ServiceUnavailable, gexc.DeadlineExceeded, gexc.ResourceExhausted,
                gexc.InternalServerError) as exc:
            raise TransientExtractionError(f"GA4 Data API temporary failure: {exc}") from exc
        except gexc.GoogleAPICallError as exc:
            raise ExtractionError(f"GA4 Data API request failed: {exc}") from exc
