"""Local DuckDB backend: lets the whole pipeline run offline with no credentials."""

from __future__ import annotations

from pathlib import Path

import duckdb

from ..contracts import LINEAGE_COLUMNS, SourceContract
from ..exceptions import LoadError, TransformError
from .warehouse import LAYERS, Warehouse

BATCH_ROWS = 500


class DuckDBWarehouse(Warehouse):
    dialect = "duckdb"

    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(path)

    def table_ref(self, layer: str, table: str) -> str:
        return f"{layer}.{table}"

    def ensure_layers(self) -> None:
        for layer in LAYERS:
            self.con.execute(f"CREATE SCHEMA IF NOT EXISTS {layer}")

    def load_raw(self, contract, records, run_id, ingested_at) -> int:
        self._create_raw_table(contract)
        if not records:
            return 0
        columns = [*contract.columns, *LINEAGE_COLUMNS]
        rows = [
            [*(record.get(c) for c in contract.columns), run_id, ingested_at, contract.name]
            for record in records
        ]
        target = self.table_ref("raw", contract.raw_table)
        row_sql = "(" + ", ".join("?" for _ in columns) + ")"
        try:
            self.con.execute("BEGIN")
            for i in range(0, len(rows), BATCH_ROWS):
                batch = rows[i:i + BATCH_ROWS]
                self.con.execute(
                    f"INSERT INTO {target} ({', '.join(columns)}) VALUES "
                    + ", ".join(row_sql for _ in batch),
                    [value for row in batch for value in row],
                )
            self.con.execute("COMMIT")
        except duckdb.Error as exc:
            self.con.execute("ROLLBACK")
            raise LoadError(f"Raw load into {target} failed: {exc}") from exc
        return len(rows)

    def _create_raw_table(self, contract: SourceContract) -> None:
        cols = ", ".join(f"{c} VARCHAR" for c in contract.columns)
        self.con.execute(
            f"CREATE TABLE IF NOT EXISTS {self.table_ref('raw', contract.raw_table)} "
            f"({cols}, _run_id VARCHAR, _ingested_at TIMESTAMP, _source_system VARCHAR)"
        )

    def create_table_as(self, layer, table, select_sql, options=None) -> None:
        # Partitioning / clustering options only apply to BigQuery.
        try:
            self.con.execute(
                f"CREATE OR REPLACE TABLE {self.table_ref(layer, table)} AS {select_sql}"
            )
        except duckdb.Error as exc:
            raise TransformError(f"Model {layer}.{table} failed: {exc}") from exc

    def query(self, sql: str) -> list[dict]:
        cursor = self.con.execute(sql)
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def close(self) -> None:
        self.con.close()

