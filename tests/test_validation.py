import pytest

from marketing_pipeline.contracts import GOOGLE_ADS_CAMPAIGNS as C
from marketing_pipeline.exceptions import ValidationError
from marketing_pipeline.quality.validation import validate_records


def row(**overrides):
    base = dict.fromkeys(C.columns, "1")
    base.update({"segments_date": "2026-08-01", "campaign_name": "brand", **overrides})
    return base


def test_valid_rows_pass():
    result = validate_records(C, [row(), row()])
    assert len(result.valid) == 2 and not result.rejected


def test_empty_extract_fails():
    with pytest.raises(ValidationError, match="no rows"):
        validate_records(C, [])


def test_schema_drift_fails_and_names_columns():
    drifted = row()
    del drifted["cost_micros"]
    drifted["cost"] = "1"
    with pytest.raises(ValidationError, match=r"missing columns \['cost_micros'\].*\['cost'\]"):
        validate_records(C, [drifted])


def test_bad_rows_are_quarantined_with_reason():
    rows = [row() for _ in range(40)] + [row(campaign_id=""), row(segments_date="01/08/2026")]
    result = validate_records(C, rows)
    assert len(result.valid) == 40
    reasons = [r["_reject_reason"] for r in result.rejected]
    assert "campaign_id" in reasons[0] and "unparseable" in reasons[1]


def test_too_many_bad_rows_fail_the_source():
    rows = [row(), row(campaign_id="")]
    with pytest.raises(ValidationError, match="1 of 2 rows rejected"):
        validate_records(C, rows)
