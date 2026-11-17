"""Post-transform data quality checks, declared in config/data_quality.yaml.

Every check compiles to one query that returns ``failed_rows``. Zero means pass.
Checks with severity ``error`` fail the run; ``warn`` checks are only reported.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from ..exceptions import ConfigurationError
from ..load.warehouse import Warehouse
from ..logging_utils import get_logger

log = get_logger("quality")


@dataclass
class CheckResult:
    name: str
    table: str
    check_type: str
    severity: str
    failed_rows: int
    passed: bool
    error: str | None = None


def _table(spec: dict) -> str:
    return "{{ " + spec["table"] + " }}"


def compile_check(spec: dict) -> str:
    """Translate a check spec into BigQuery SQL returning a single ``failed_rows``."""
    kind = spec["type"]
    if kind == "sql":
        return spec["sql"]
    table = _table(spec)
    cols = spec.get("columns", [])
    if kind == "not_null":
        condition = " OR ".join(f"{c} IS NULL" for c in cols)
        return f"SELECT COUNT(*) AS failed_rows FROM {table} WHERE {condition}"
    if kind == "unique":
        keys = ", ".join(cols)
        return (
            "SELECT COUNT(*) AS failed_rows FROM ("
            f"SELECT {keys} FROM {table} GROUP BY {keys} HAVING COUNT(*) > 1) AS d"
        )
    if kind == "non_negative":
        condition = " OR ".join(f"{c} < 0" for c in cols)
        return f"SELECT COUNT(*) AS failed_rows FROM {table} WHERE {condition}"
    if kind == "accepted_values":
        values = ", ".join("'" + str(v).replace("'", "\\'") + "'" for v in spec["values"])
        col = spec["column"]
        return (f"SELECT COUNT(*) AS failed_rows FROM {table} "
                f"WHERE {col} IS NULL OR {col} NOT IN ({values})")
    if kind == "expression":
        # Rows where the expression is not true (NULL counts as a failure).
        return (f"SELECT COUNT(*) AS failed_rows FROM {table} "
                f"WHERE NOT COALESCE(({spec['expression']}), FALSE)")
    if kind == "row_count_min":
        return (f"SELECT CASE WHEN COUNT(*) >= {int(spec['min'])} THEN 0 ELSE 1 END "
                f"AS failed_rows FROM {table}")
    if kind == "freshness":
        # The newest date must be within max_lag_days of the end of the run window.
        return (
            f"SELECT CASE WHEN DATE_DIFF(DATE '{{{{ window_end }}}}', MAX({spec['column']}), DAY) "
            f"<= {int(spec['max_lag_days'])} THEN 0 ELSE 1 END AS failed_rows FROM {table}"
        )
    raise ConfigurationError(f"Unknown data quality check type: {kind!r}")


def load_checks(path: Path) -> list[dict]:
    specs = yaml.safe_load(path.read_text(encoding="utf-8"))["checks"]
    for spec in specs:
        for required in ("name", "table", "type"):
            if required not in spec:
                raise ConfigurationError(f"Data quality check missing {required!r}: {spec}")
        spec.setdefault("severity", "error")
        if spec["severity"] not in ("error", "warn"):
            raise ConfigurationError(f"Check {spec['name']}: severity must be error or warn")
        compile_check(spec)  # fail on bad specs before anything runs
    return specs


def run_checks(
    warehouse: Warehouse, specs: list[dict], params: dict[str, str]
) -> list[CheckResult]:
    results = []
    for spec in specs:
        try:
            row = warehouse.query(warehouse.render(compile_check(spec), params))[0]
            failed = int(row["failed_rows"] or 0)
            result = CheckResult(spec["name"], spec["table"], spec["type"], spec["severity"],
                                 failed, failed == 0)
        except Exception as exc:  # noqa: BLE001 - a broken check must not hide the others
            result = CheckResult(spec["name"], spec["table"], spec["type"], spec["severity"],
                                 -1, False, error=str(exc))
        if result.passed:
            log.info("PASS %s", result.name)
        else:
            detail = result.error or f"{result.failed_rows} failing row(s)"
            level = log.error if result.severity == "error" else log.warning
            level("FAIL [%s] %s on %s: %s", result.severity, result.name, result.table, detail)
        results.append(result)
    return results


def blocking_failures(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if not r.passed and r.severity == "error"]


def results_as_dicts(results: list[CheckResult]) -> list[dict]:
    return [asdict(r) for r in results]
