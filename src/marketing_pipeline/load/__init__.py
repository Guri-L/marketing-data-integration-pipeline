"""Warehouse backends."""

from __future__ import annotations

from ..config import Settings
from .warehouse import Warehouse

__all__ = ["Warehouse", "build_warehouse"]


def build_warehouse(settings: Settings) -> Warehouse:
    if settings.warehouse == "bigquery":
        from .bigquery_warehouse import BigQueryWarehouse

        return BigQueryWarehouse(settings)
    from .duckdb_warehouse import DuckDBWarehouse

    return DuckDBWarehouse(settings.duckdb_path)
