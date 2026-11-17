"""Pipeline orchestration: extract -> validate -> land -> load raw -> transform -> check.

Failure policy
* One source failing does not stop the others from loading, but the run is
  marked failed and transforms are skipped, so reporting tables are never
  rebuilt from a partial set of sources.
* A transform failure stops the run: later models depend on earlier ones.
* Error-severity data quality failures fail the run after all checks have run.
* A run summary is always written, including on failure.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from .config import CONFIG_DIR, SQL_DIR, Settings
from .contracts import CONTRACTS
from .exceptions import DataQualityError, PipelineError
from .extract import Extractor, build_extractors
from .load import Warehouse, build_warehouse
from .logging_utils import get_logger, set_run_context
from .quality.checks import blocking_failures, load_checks, results_as_dicts, run_checks
from .quality.validation import validate_records
from .transform.runner import run_models

log = get_logger("pipeline")


@dataclass
class RunSummary:
    run_id: str
    mode: str
    warehouse: str
    window_start: str
    window_end: str
    started_at: str
    status: str = "running"
    finished_at: str | None = None
    duration_seconds: float | None = None
    sources: dict[str, dict] = field(default_factory=dict)
    models: list[dict] = field(default_factory=list)
    quality_checks: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _write_ndjson(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def ingest_source(name: str, extractor: Extractor, warehouse: Warehouse, settings: Settings,
                  run_id: str, start: date, end: date) -> dict:
    """Extract, validate, land and load one source. Raises PipelineError on failure."""
    contract = CONTRACTS[name]
    records = extractor.extract(start, end)
    result = validate_records(contract, records)

    # Landing zone: an immutable copy of exactly what was loaded, per run.
    landing = Path(settings.landing_dir) / name / f"run_id={run_id}"
    _write_ndjson(landing / "data.ndjson", result.valid)
    if result.rejected:
        _write_ndjson(landing / "rejected.ndjson", result.rejected)
        log.warning("%s: quarantined %d invalid row(s) in %s",
                    name, len(result.rejected), landing / "rejected.ndjson")

    loaded = warehouse.load_raw(contract, result.valid, run_id, datetime.now(timezone.utc))
    log.info("%s: extracted %d, loaded %d, rejected %d",
             name, len(records), loaded, len(result.rejected))
    return {"status": "ok", "extracted": len(records), "loaded": loaded,
            "rejected": len(result.rejected)}


def run_pipeline(
    settings: Settings,
    start: date | None = None,
    end: date | None = None,
    *,
    warehouse: Warehouse | None = None,
    extractors: dict[str, Extractor] | None = None,
    skip_ingest: bool = False,
) -> RunSummary:
    default_start, default_end = settings.default_window()
    start, end = start or default_start, end or default_end
    if start > end:
        raise PipelineError(f"Window start {start} is after end {end}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    set_run_context(run_id=run_id)
    summary = RunSummary(run_id, settings.mode, settings.warehouse, start.isoformat(),
                         end.isoformat(), datetime.now(timezone.utc).isoformat())
    started = time.perf_counter()
    owns_warehouse = warehouse is None
    log.info("Run started: mode=%s warehouse=%s window=%s..%s",
             settings.mode, settings.warehouse, start, end)

    try:
        warehouse = warehouse or build_warehouse(settings)
        warehouse.ensure_layers()

        if not skip_ingest:
            for name, extractor in (extractors or build_extractors(settings)).items():
                try:
                    summary.sources[name] = ingest_source(
                        name, extractor, warehouse, settings, run_id, start, end
                    )
                except PipelineError as exc:
                    log.error("%s: ingestion failed: %s", name, exc)
                    summary.sources[name] = {"status": "failed", "error": str(exc)}
                    summary.errors.append(f"{name}: {exc}")
            if summary.errors:
                raise PipelineError(
                    "Ingestion failed for: "
                    + ", ".join(n for n, s in summary.sources.items() if s["status"] == "failed")
                    + ". Transforms skipped so reporting is not rebuilt from partial data."
                )

        summary.models = run_models(warehouse, SQL_DIR)

        checks = run_checks(warehouse, load_checks(CONFIG_DIR / "data_quality.yaml"),
                            {"window_end": end.isoformat()})
        summary.quality_checks = results_as_dicts(checks)
        failures = blocking_failures(checks)
        if failures:
            raise DataQualityError(
                f"{len(failures)} data quality check(s) failed: "
                + ", ".join(f.name for f in failures)
            )
        summary.status = "success"
    except PipelineError as exc:
        summary.status = "failed"
        if str(exc) not in summary.errors:
            summary.errors.append(str(exc))
        log.error("Run failed: %s", exc)
    except Exception as exc:  # unexpected: keep the traceback, still write the summary
        summary.status = "failed"
        summary.errors.append(f"Unexpected {type(exc).__name__}: {exc}")
        log.exception("Run failed with an unexpected error")
    finally:
        if owns_warehouse and warehouse is not None:
            warehouse.close()
        summary.finished_at = datetime.now(timezone.utc).isoformat()
        summary.duration_seconds = round(time.perf_counter() - started, 2)
        _write_summary(summary, settings)

    passed = sum(c["passed"] for c in summary.quality_checks)
    log.info("Run %s in %.1fs: %d source(s), %d model(s), %d/%d checks passed",
             summary.status, summary.duration_seconds, len(summary.sources),
             len(summary.models), passed, len(summary.quality_checks))
    return summary


def _write_summary(summary: RunSummary, settings: Settings) -> None:
    from dataclasses import asdict

    from .logging_utils import redact

    out_dir = Path(settings.artifacts_dir) / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    text = redact(json.dumps(asdict(summary), indent=2, default=str))
    (out_dir / f"{summary.run_id}.json").write_text(text, encoding="utf-8")
    (out_dir / "latest.json").write_text(text, encoding="utf-8")
