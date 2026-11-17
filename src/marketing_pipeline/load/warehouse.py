"""Warehouse interface shared by the BigQuery and local DuckDB backends.

All SQL in this repository is written in BigQuery Standard SQL. Table
references use ``{{ layer.table }}`` placeholders. ``render`` resolves the
placeholders and, for non-BigQuery backends, transpiles the statement with
sqlglot, so the same model files run locally and in BigQuery.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime

import sqlglot

from ..contracts import SourceContract
from ..exceptions import TransformError

LAYERS = ("raw", "staging", "reporting")
REF_PATTERN = re.compile(r"\{\{\s*(raw|staging|reporting)\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
PARAM_PATTERN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


class Warehouse(ABC):
    dialect: str

    @abstractmethod
    def table_ref(self, layer: str, table: str) -> str:
        """Fully qualified, quoted table name for this backend."""

    @abstractmethod
    def ensure_layers(self) -> None:
        """Create the raw / staging / reporting datasets if missing."""

    @abstractmethod
    def load_raw(self, contract: SourceContract, records: list[dict[str, str]],
                 run_id: str, ingested_at: datetime) -> int:
        """Append records to the raw table, adding lineage columns. Returns rows loaded."""

    @abstractmethod
    def create_table_as(self, layer: str, table: str, select_sql: str,
                        options: dict[str, str] | None = None) -> None:
        """CREATE OR REPLACE ``layer.table`` from an already-rendered SELECT."""

    @abstractmethod
    def query(self, sql: str) -> list[dict]:
        """Run an already-rendered query and return rows as dicts."""

    def close(self) -> None:  # noqa: B027 - optional hook
        pass

    def render(self, sql: str, params: dict[str, str] | None = None) -> str:
        """Resolve placeholders and translate to this backend's dialect."""
        rendered = REF_PATTERN.sub(lambda m: self.table_ref(m.group(1), m.group(2)), sql)
        for key, value in (params or {}).items():
            rendered = re.sub(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", value, rendered)
        leftover = PARAM_PATTERN.search(rendered)
        if leftover:
            raise TransformError(f"Unresolved placeholder in SQL: {leftover.group(0)}")
        if self.dialect == "bigquery":
            return rendered
        try:
            statements = sqlglot.transpile(rendered, read="bigquery", write=self.dialect)
        except sqlglot.errors.SqlglotError as exc:
            raise TransformError(f"Could not transpile SQL to {self.dialect}: {exc}") from exc
        if len(statements) != 1:
            raise TransformError("Each SQL file must contain exactly one statement")
        return statements[0]
