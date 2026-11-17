from __future__ import annotations

import pytest

from marketing_pipeline.config import SYNTHETIC_DIR, Settings
from marketing_pipeline.contracts import CONTRACTS
from marketing_pipeline.extract import SyntheticExtractor
from marketing_pipeline.load.duckdb_warehouse import DuckDBWarehouse


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Retries must not slow the suite down."""
    monkeypatch.setattr("marketing_pipeline.retry.time.sleep", lambda _: None)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        duckdb_path=":memory:",
        landing_dir=str(tmp_path / "landing"),
        artifacts_dir=str(tmp_path / "artifacts"),
    )


@pytest.fixture
def warehouse():
    wh = DuckDBWarehouse(":memory:")
    yield wh
    wh.close()


@pytest.fixture
def extractors():
    return {name: SyntheticExtractor(c, SYNTHETIC_DIR) for name, c in CONTRACTS.items()}


class StaticExtractor:
    """Returns fixed records; used to simulate restatements and bad data."""

    def __init__(self, contract, records):
        self.contract = contract
        self.records = records

    def extract(self, start, end):
        return [dict(r) for r in self.records]


class FailingExtractor:
    def __init__(self, contract, error):
        self.contract = contract
        self.error = error

    def extract(self, start, end):
        raise self.error
