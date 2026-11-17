"""Builds the staging and reporting layers from the SQL model files.

Each file in sql/<layer>/ holds one SELECT. The file name is the table name and
the directory is the layer. Dependencies are read from the ``{{ layer.table }}``
references, so models build in a valid order without a hand-kept list.

Optional header comments set BigQuery table options:
    -- partition_by: date
    -- cluster_by: platform, campaign_name
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

from ..exceptions import TransformError
from ..load.warehouse import REF_PATTERN, Warehouse
from ..logging_utils import get_logger

log = get_logger("transform")
MODEL_LAYERS = ("staging", "reporting")
OPTION_PATTERN = re.compile(r"^--\s*(partition_by|cluster_by)\s*:\s*(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Model:
    layer: str
    name: str
    sql: str
    depends_on: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    options: tuple[tuple[str, str], ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return (self.layer, self.name)


def discover_models(sql_dir: Path) -> list[Model]:
    """Load every model and return them in dependency order."""
    models: dict[tuple[str, str], Model] = {}
    for layer in MODEL_LAYERS:
        for path in sorted((sql_dir / layer).glob("*.sql")):
            sql = path.read_text(encoding="utf-8").strip().rstrip(";")
            refs = frozenset(REF_PATTERN.findall(sql))
            model = Model(layer, path.stem, sql, refs, tuple(OPTION_PATTERN.findall(sql)))
            models[model.key] = model
    if not models:
        raise TransformError(f"No SQL models found under {sql_dir}")

    graph = {
        key: {dep for dep in model.depends_on if dep[0] != "raw"}
        for key, model in models.items()
    }
    for key, deps in graph.items():
        unknown = deps - models.keys()
        if unknown:
            raise TransformError(f"Model {key[0]}.{key[1]} references unknown model(s): {unknown}")
    try:
        order = list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise TransformError(f"Circular model dependency: {exc.args[1]}") from exc
    return [models[key] for key in order]


def run_models(warehouse: Warehouse, sql_dir: Path) -> list[dict]:
    """Build every model. Stops at the first failure: later models depend on it."""
    results = []
    for model in discover_models(sql_dir):
        started = time.perf_counter()
        warehouse.create_table_as(
            model.layer, model.name, warehouse.render(model.sql), dict(model.options)
        )
        rows = warehouse.query(
            f"SELECT COUNT(*) AS n FROM {warehouse.table_ref(model.layer, model.name)}"
        )[0]["n"]
        seconds = round(time.perf_counter() - started, 3)
        log.info("Built %s.%s (%d rows, %.2fs)", model.layer, model.name, rows, seconds)
        results.append({"model": f"{model.layer}.{model.name}", "rows": rows, "seconds": seconds})
    return results
