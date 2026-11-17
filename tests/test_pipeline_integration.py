"""End-to-end runs on the synthetic data against an in-memory DuckDB warehouse."""

import csv
import json
from pathlib import Path

import pytest
from conftest import FailingExtractor, StaticExtractor

from marketing_pipeline.config import SYNTHETIC_DIR
from marketing_pipeline.contracts import CONTRACTS
from marketing_pipeline.exceptions import ExtractionError
from marketing_pipeline.pipeline import run_pipeline


def read_synthetic(name):
    path = SYNTHETIC_DIR / CONTRACTS[name].synthetic_file
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def scalar(warehouse, sql):
    return next(iter(warehouse.query(sql)[0].values()))


@pytest.fixture
def completed_run(settings, warehouse, extractors):
    summary = run_pipeline(settings, warehouse=warehouse, extractors=extractors)
    return summary, warehouse


def test_full_run_succeeds(completed_run):
    summary, _ = completed_run
    assert summary.status == "success", summary.errors
    assert {s["status"] for s in summary.sources.values()} == {"ok"}
    assert len(summary.models) == 6
    errors = [c for c in summary.quality_checks if not c["passed"] and c["severity"] == "error"]
    assert errors == []


def test_run_summary_and_landing_files_are_written(completed_run, settings):
    summary, _ = completed_run
    latest = json.loads((Path(settings.artifacts_dir) / "runs" / "latest.json").read_text())
    assert latest["run_id"] == summary.run_id and latest["status"] == "success"
    landed = Path(settings.landing_dir) / "meta_ads" / f"run_id={summary.run_id}" / "data.ndjson"
    assert len(landed.read_text().splitlines()) == summary.sources["meta_ads"]["loaded"]


def test_raw_layer_keeps_source_values_untouched(completed_run):
    _, wh = completed_run
    source = read_synthetic("google_ads")
    assert scalar(wh, "select count(*) from raw.google_ads_campaign_performance") == len(source)
    types = wh.query("select typeof(cost_micros) as t, typeof(_ingested_at) as i "
                     "from raw.google_ads_campaign_performance limit 1")[0]
    assert types == {"t": "VARCHAR", "i": "TIMESTAMP"}


def test_staging_removes_duplicates(completed_run):
    _, wh = completed_run
    for name, table in (("google_ads", "stg_google_ads__campaign_daily"),
                        ("meta_ads", "stg_meta_ads__campaign_daily")):
        source = read_synthetic(name)
        distinct = {tuple(r[k] for k in CONTRACTS[name].key) for r in source}
        assert len(distinct) < len(source)
        assert scalar(wh, f"select count(*) from staging.{table}") == len(distinct)


def test_spend_matches_source_files_through_every_layer(completed_run):
    _, wh = completed_run
    google = {tuple(r[k] for k in CONTRACTS["google_ads"].key): int(r["cost_micros"]) / 1e6
              for r in read_synthetic("google_ads")}
    meta = {tuple(r[k] for k in CONTRACTS["meta_ads"].key): float(r["spend"])
            for r in read_synthetic("meta_ads")}
    expected = sum(google.values()) + sum(meta.values())
    for table in ("reporting.rpt_paid_media_campaign_daily",
                  "reporting.rpt_channel_performance_daily",
                  "reporting.rpt_platform_summary_monthly"):
        # Staging rounds each row to cents, so allow half a cent per source row.
        assert scalar(wh, f"select sum(spend) from {table}") == pytest.approx(
            expected, abs=0.005 * (len(google) + len(meta)))


def test_ga4_sessions_survive_cleaning(completed_run):
    _, wh = completed_run
    expected = sum(int(r["sessions"]) for r in read_synthetic("ga4"))
    assert scalar(wh, "select sum(sessions) from staging.stg_ga4__sessions") == expected
    assert scalar(wh, "select sum(sessions) from reporting.rpt_channel_performance_daily") \
        == expected


def test_source_casing_is_normalised(completed_run):
    _, wh = completed_run
    assert any(r["session_source"] == "Facebook" for r in read_synthetic("ga4"))
    assert scalar(wh, "select count(*) from staging.stg_ga4__sessions "
                      "where source != lower(source)") == 0


def test_untracked_sessions_are_reported_not_lost(completed_run):
    _, wh = completed_run
    not_set = sum(int(r["sessions"]) for r in read_synthetic("ga4")
                  if r["session_campaign_name"] == "(not set)")
    assert not_set > 0
    assert scalar(wh, "select sum(ga4_untracked_sessions) "
                      "from reporting.rpt_platform_summary_monthly") == not_set


def test_rerun_is_idempotent(completed_run, settings, extractors):
    _, wh = completed_run
    query = ("select count(*) as n, round(sum(spend), 2) as spend, sum(ga4_sessions) as s "
             "from reporting.rpt_paid_media_campaign_daily")
    before = wh.query(query)
    raw_before = scalar(wh, "select count(*) from raw.meta_ads_campaign_insights")

    second = run_pipeline(settings, warehouse=wh, extractors=extractors)

    assert second.status == "success"
    assert scalar(wh, "select count(*) from raw.meta_ads_campaign_insights") == 2 * raw_before
    assert wh.query(query) == before


def test_restated_figures_replace_earlier_ones(completed_run, settings, extractors):
    _, wh = completed_run
    restated = read_synthetic("meta_ads")
    target = restated[0]
    key_filter = (f"date = date '{target['date_start']}' "
                  f"and campaign_id = '{target['campaign_id']}'")
    for row in restated:
        if (row["date_start"], row["campaign_id"]) == (target["date_start"],
                                                       target["campaign_id"]):
            row["spend"] = "999.99"
    extractors["meta_ads"] = StaticExtractor(CONTRACTS["meta_ads"], restated)

    assert run_pipeline(settings, warehouse=wh, extractors=extractors).status == "success"
    assert scalar(wh, f"select spend from staging.stg_meta_ads__campaign_daily "
                      f"where {key_filter}") == 999.99


def test_failed_source_fails_run_without_rebuilding_reporting(settings, warehouse, extractors):
    extractors["meta_ads"] = FailingExtractor(CONTRACTS["meta_ads"],
                                              ExtractionError("HTTP 400, code 190: token expired"))
    summary = run_pipeline(settings, warehouse=warehouse, extractors=extractors)

    assert summary.status == "failed"
    assert summary.sources["meta_ads"]["status"] == "failed"
    assert "token expired" in summary.sources["meta_ads"]["error"]
    # The healthy sources still loaded, but no model was built from partial data.
    assert summary.sources["ga4"]["status"] == "ok"
    assert scalar(warehouse, "select count(*) from raw.ga4_sessions") > 0
    assert summary.models == []


def test_schema_drift_fails_the_source(settings, warehouse, extractors):
    drifted = [{k: v for k, v in r.items() if k != "spend"} for r in read_synthetic("meta_ads")]
    extractors["meta_ads"] = StaticExtractor(CONTRACTS["meta_ads"], drifted)
    summary = run_pipeline(settings, warehouse=warehouse, extractors=extractors)
    assert summary.status == "failed"
    assert "schema drift" in summary.sources["meta_ads"]["error"]


def test_bad_values_are_caught_by_quality_checks(settings, warehouse, extractors):
    rows = read_synthetic("google_ads")
    rows[0]["cost_micros"] = "-5000000"        # negative spend
    rows[1]["clicks"] = "not-a-number"         # becomes NULL in staging
    extractors["google_ads"] = StaticExtractor(CONTRACTS["google_ads"], rows)

    summary = run_pipeline(settings, warehouse=warehouse, extractors=extractors)

    assert summary.status == "failed"
    failed = {c["name"] for c in summary.quality_checks if not c["passed"]}
    assert "stg_google_ads_metrics_non_negative" in failed
    assert "stg_google_ads_keys_not_null" in failed
    assert "data quality check(s) failed" in summary.errors[0]


def test_unexpected_errors_are_recorded_not_raised(settings, warehouse, extractors):
    extractors["ga4"] = FailingExtractor(CONTRACTS["ga4"], RuntimeError("boom"))
    summary = run_pipeline(settings, warehouse=warehouse, extractors=extractors)
    assert summary.status == "failed"
    assert "Unexpected RuntimeError: boom" in summary.errors[0]
