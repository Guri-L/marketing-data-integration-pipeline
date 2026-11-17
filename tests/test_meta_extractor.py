"""Meta extractor logic against a fake HTTP session (no network, no real token)."""

from datetime import date

import pytest

from marketing_pipeline.config import Settings
from marketing_pipeline.contracts import META_ADS_CAMPAIGNS
from marketing_pipeline.exceptions import ExtractionError, TransientExtractionError
from marketing_pipeline.extract.meta_ads import MetaAdsExtractor, flatten_insight

TOKEN = "EAAB-fake-token-for-tests"  # noqa: S105 - obviously fake
INSIGHT = {
    "date_start": "2026-08-01", "date_stop": "2026-08-01", "account_id": "1",
    "campaign_id": "10", "campaign_name": "prospecting", "objective": "OUTCOME_SALES",
    "impressions": "1000", "reach": "800", "clicks": "20", "spend": "12.50",
    "actions": [{"action_type": "link_click", "value": "18"},
                {"action_type": "purchase", "value": "3"},
                {"action_type": "omni_purchase", "value": "4"}],
    "action_values": [{"action_type": "omni_purchase", "value": "210.40"}],
}


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, headers, timeout):
        self.calls.append({"url": url, "params": dict(params), "headers": dict(headers)})
        return self.responses.pop(0)


@pytest.fixture
def live_settings(monkeypatch):
    monkeypatch.setenv("META_ACCESS_TOKEN", TOKEN)
    return Settings(mode="live", ga4_property_id="1", google_ads_customer_id="1",
                    meta_ad_account_id="555", meta_api_version="v24.0")


def test_flatten_matches_raw_contract_and_prefers_omni_purchase():
    record = flatten_insight(INSIGHT)
    assert tuple(record) == META_ADS_CAMPAIGNS.columns
    assert record["purchases"] == "4"
    assert record["purchase_value"] == "210.40"


def test_flatten_defaults_when_no_purchases():
    record = flatten_insight({k: v for k, v in INSIGHT.items() if "action" not in k})
    assert (record["purchases"], record["purchase_value"]) == ("0", "0")


def test_pages_with_cursor_and_keeps_token_out_of_the_url(live_settings):
    session = FakeSession([
        FakeResponse(200, {"data": [INSIGHT], "paging": {"cursors": {"after": "abc"},
                                                         "next": "https://next?access_token=x"}}),
        FakeResponse(200, {"data": [INSIGHT], "paging": {"cursors": {"after": "def"}}}),
    ])
    records = MetaAdsExtractor(live_settings, session).extract(date(2026, 8, 1), date(2026, 8, 2))

    assert len(records) == 2
    first, second = session.calls
    assert first["url"] == "https://graph.facebook.com/v24.0/act_555/insights"
    assert second["params"]["after"] == "abc"
    for call in session.calls:
        assert TOKEN not in call["url"] and TOKEN not in str(call["params"])
        assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_rate_limit_is_retried(live_settings):
    session = FakeSession([
        FakeResponse(400, {"error": {"code": 17, "message": "User request limit reached"}}),
        FakeResponse(200, {"data": [INSIGHT]}),
    ])
    records = MetaAdsExtractor(live_settings, session).extract(date(2026, 8, 1), date(2026, 8, 1))
    assert len(records) == 1 and len(session.calls) == 2


def test_persistent_outage_surfaces_as_transient_error(live_settings):
    session = FakeSession([FakeResponse(503, {})] * 4)
    with pytest.raises(TransientExtractionError):
        MetaAdsExtractor(live_settings, session).extract(date(2026, 8, 1), date(2026, 8, 1))
    assert len(session.calls) == 4


def test_auth_error_is_not_retried_and_does_not_leak_token(live_settings):
    session = FakeSession([
        FakeResponse(400, {"error": {"code": 190, "message": "Invalid OAuth access token"}}),
    ])
    with pytest.raises(ExtractionError) as exc:
        MetaAdsExtractor(live_settings, session).extract(date(2026, 8, 1), date(2026, 8, 1))
    assert not isinstance(exc.value, TransientExtractionError)
    assert len(session.calls) == 1
    assert "code 190" in str(exc.value) and TOKEN not in str(exc.value)
