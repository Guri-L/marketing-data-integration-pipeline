"""BigQuery backend.

Auth: Application Default Credentials only. The identity needs
roles/bigquery.dataEditor on the three datasets and roles/bigquery.jobUser on
the project. NOT yet verified against a live project - see README.
"""

from __future__ import annotations

from ..config import Settings
from ..contracts import LINEAGE_COLUMNS, SourceContract
from ..exceptions import ConfigurationError, LoadError, TransformError
from ..logging_utils import get_logger
from .warehouse import Warehouse

log = get_logger("load.bigquery")


class BigQueryWarehouse(Warehouse):
    dialect = "bigquery"

    def __init__(self, settings: Settings, client=None) -> None:
        self.project = settings.gcp_project_id
        self.location = settings.bq_location
        self.datasets = {
            "raw": settings.bq_dataset_raw,
            "staging": settings.bq_dataset_staging,
            "reporting": settings.bq_dataset_reporting,
        }
        self._client = client  # injectable for tests

    @property
    def client(self):
        if self._client is None:
            try:
                from google.cloud import bigquery
            except ImportError as exc:
                raise ConfigurationError(
                    "Install the 'bigquery' extra: pip install -e '.[bigquery]'"
                ) from exc
            self._client = bigquery.Client(project=self.project, location=self.location)
        return self._client

    def table_ref(self, layer: str, table: str) -> str:
        return f"`{self.project}.{self.datasets[layer]}.{table}`"

    def _table_id(self, layer: str, table: str) -> str:
        return self.table_ref(layer, table).strip("`")

    def ensure_layers(self) -> None:
        from google.cloud import bigquery

        for layer, dataset_id in self.datasets.items():
            dataset = bigquery.Dataset(f"{self.project}.{dataset_id}")
            dataset.location = self.location
            dataset.description = f"Marketing pipeline - {layer} layer"
            self.client.create_dataset(dataset, exists_ok=True)

    def load_raw(self, contract: SourceContract, records, run_id, ingested_at) -> int:
        from google.api_core.exceptions import GoogleAPICallError
        from google.cloud import bigquery

        if not records:
            return 0
        schema = [bigquery.SchemaField(c, "STRING") for c in contract.columns] + [
            bigquery.SchemaField("_run_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("_ingested_at", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("_source_system", "STRING", mode="REQUIRED"),
        ]
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            time_partitioning=bigquery.TimePartitioning(field="_ingested_at"),
            # Appending columns is allowed; anything else must fail loudly.
            schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
        )
        lineage = dict(zip(LINEAGE_COLUMNS, (run_id, ingested_at.isoformat(), contract.name),
                           strict=True))
        rows = [{**{c: r.get(c) for c in contract.columns}, **lineage} for r in records]
        table_id = self._table_id("raw", contract.raw_table)
        try:
            # A load job is atomic: either every row lands or none does.
            job = self.client.load_table_from_json(rows, table_id, job_config=job_config)
            job.result()
        except GoogleAPICallError as exc:
            raise LoadError(f"Raw load into {table_id} failed: {exc}") from exc
        log.info("Loaded %d rows into %s (job %s)", len(rows), table_id, job.job_id)
        return len(rows)

    def build_ddl(self, layer: str, table: str, select_sql: str,
                  options: dict[str, str] | None = None) -> str:
        options = options or {}
        clauses = ""
        if options.get("partition_by"):
            clauses += f"\nPARTITION BY {options['partition_by']}"
        if options.get("cluster_by"):
            clauses += f"\nCLUSTER BY {options['cluster_by']}"
        return f"CREATE OR REPLACE TABLE {self.table_ref(layer, table)}{clauses}\nAS\n{select_sql}"

    def create_table_as(self, layer, table, select_sql, options=None) -> None:
        from google.api_core.exceptions import GoogleAPICallError

        try:
            self.client.query(self.build_ddl(layer, table, select_sql, options)).result()
        except GoogleAPICallError as exc:
            raise TransformError(f"Model {layer}.{table} failed: {exc}") from exc

    def query(self, sql: str) -> list[dict]:
        return [dict(row.items()) for row in self.client.query(sql).result()]
