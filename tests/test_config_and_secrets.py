import logging

import pytest

from marketing_pipeline.config import Settings
from marketing_pipeline.exceptions import ConfigurationError
from marketing_pipeline.logging_utils import configure_logging, redact
from marketing_pipeline.secrets import Secret, get_secret


def test_defaults_run_offline():
    settings = Settings()
    settings.validate()
    assert (settings.mode, settings.warehouse) == ("synthetic", "duckdb")


def test_bigquery_requires_project():
    with pytest.raises(ConfigurationError, match="GCP_PROJECT_ID"):
        Settings(warehouse="bigquery").validate()


def test_live_mode_lists_every_missing_setting():
    with pytest.raises(ConfigurationError) as exc:
        Settings(mode="live").validate()
    for name in ("GA4_PROPERTY_ID", "GOOGLE_ADS_CUSTOMER_ID", "META_AD_ACCOUNT_ID",
                 "META_API_VERSION"):
        assert name in str(exc.value)


def test_from_env_normalises_ids(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_ADS_CUSTOMER_ID", "123-456-7890")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "act_555")
    settings = Settings.from_env(env_file=tmp_path / "missing.env")
    assert settings.google_ads_customer_id == "1234567890"
    assert settings.meta_ad_account_id == "555"


def test_secret_never_prints_its_value():
    secret = Secret("EAAB-super-secret-token")
    assert "super-secret" not in repr(secret)
    assert "super-secret" not in f"{secret}"
    assert secret.reveal() == "EAAB-super-secret-token"


def test_missing_secret_raises_without_leaking(monkeypatch):
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    with pytest.raises(ConfigurationError, match="META_ACCESS_TOKEN"):
        get_secret("META_ACCESS_TOKEN")


def test_redact_masks_registered_and_pattern_secrets(monkeypatch):
    monkeypatch.setenv("META_ACCESS_TOKEN", "EAAB1234567890abcdef")
    get_secret("META_ACCESS_TOKEN")
    assert "EAAB1234567890abcdef" not in redact("token was EAAB1234567890abcdef")
    assert "zzz999" not in redact("GET /insights?access_token=zzz999&level=campaign")
    assert "abcdefgh12345" not in redact("Authorization: Bearer abcdefgh12345")


def test_log_output_is_redacted(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "1//refresh-token-value")
    get_secret("GOOGLE_ADS_REFRESH_TOKEN")
    configure_logging("INFO", "json")
    try:
        raise RuntimeError("auth failed for 1//refresh-token-value")
    except RuntimeError:
        logging.getLogger("marketing_pipeline.test").exception("request failed: %s",
                                                               "1//refresh-token-value")
    err = capsys.readouterr().err
    assert "1//refresh-token-value" not in err
    assert "********" in err
