"""Static checks on the SQL models: they must be valid BigQuery SQL and build in order."""

import pytest
import sqlglot

from marketing_pipeline.config import CONFIG_DIR, SQL_DIR, Settings
from marketing_pipeline.exceptions import TransformError
from marketing_pipeline.load.bigquery_warehouse import BigQueryWarehouse
from marketing_pipeline.load.duckdb_warehouse import DuckDBWarehouse
from marketing_pipeline.quality.checks import compile_check, load_checks
from marketing_pipeline.transform.runner import discover_models


@pytest.fixture
def bigquery():
    # No client is created: rendering never touches the network.
    return BigQueryWarehouse(Settings(warehouse="bigquery", gcp_project_id="demo-project"))


def test_models_are_discovered_in_dependency_order():
    order = [m.name for m in discover_models(SQL_DIR)]
    assert len(order) == 6
    position = {name: i for i, name in enumerate(order)}
    assert position["stg_google_ads__campaign_daily"] < position["rpt_paid_media_campaign_daily"]
    assert position["stg_ga4__sessions"] < position["rpt_paid_media_campaign_daily"]
    assert position["rpt_paid_media_campaign_daily"] < position["rpt_channel_performance_daily"]
    assert position["rpt_paid_media_campaign_daily"] < position["rpt_platform_summary_monthly"]


def test_models_render_to_parseable_bigquery_sql(bigquery):
    for model in discover_models(SQL_DIR):
        rendered = bigquery.render(model.sql)
        assert "{{" not in rendered
        assert "`demo-project.marketing_" in rendered
        ddl = bigquery.build_ddl(model.layer, model.name, rendered, dict(model.options))
        sqlglot.parse_one(ddl, read="bigquery")  # raises on a syntax error


def test_bigquery_ddl_applies_partitioning_and_clustering(bigquery):
    model = next(m for m in discover_models(SQL_DIR) if m.name == "rpt_paid_media_campaign_daily")
    ddl = bigquery.build_ddl(model.layer, model.name, bigquery.render(model.sql),
                             dict(model.options))
    assert ddl.startswith(
        "CREATE OR REPLACE TABLE `demo-project.marketing_reporting.rpt_paid_media_campaign_daily`"
        "\nPARTITION BY date\nCLUSTER BY platform, campaign_name\nAS\n"
    )


def test_quality_checks_render_to_parseable_bigquery_sql(bigquery):
    specs = load_checks(CONFIG_DIR / "data_quality.yaml")
    assert len(specs) >= 20
    for spec in specs:
        rendered = bigquery.render(compile_check(spec), {"window_end": "2026-10-31"})
        sqlglot.parse_one(rendered, read="bigquery")


def test_unresolved_placeholder_is_rejected():
    with pytest.raises(TransformError, match="Unresolved placeholder"):
        DuckDBWarehouse().render("select * from {{ unknown_thing }}")


def test_unknown_model_reference_is_rejected(tmp_path):
    (tmp_path / "staging").mkdir()
    (tmp_path / "reporting").mkdir()
    (tmp_path / "reporting" / "rpt_x.sql").write_text("select * from {{ staging.missing }}")
    with pytest.raises(TransformError, match="unknown model"):
        discover_models(tmp_path)
