"""Command line entry point: ``python -m marketing_pipeline <command>``."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from .config import Settings
from .exceptions import ConfigurationError
from .logging_utils import configure_logging, get_logger

log = get_logger("cli")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marketing-pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="extract, load, transform and run quality checks")
    run.add_argument("--start", type=date.fromisoformat, help="window start, YYYY-MM-DD")
    run.add_argument("--end", type=date.fromisoformat, help="window end, YYYY-MM-DD")
    run.add_argument("--skip-ingest", action="store_true",
                     help="rebuild staging/reporting and re-run checks from existing raw data")

    sub.add_parser("generate-data", help="regenerate the synthetic datasets in data/synthetic/")
    sub.add_parser("check-config", help="validate settings without running anything")
    sub.add_parser("show-sql", help="print every model as BigQuery DDL for the configured project")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    configure_logging(settings.log_level, settings.log_format)

    if args.command == "generate-data":
        from .synthetic.generator import write_all

        for name, path in write_all().items():
            log.info("Wrote %s -> %s", name, path)
        return 0

    if args.command == "check-config":
        log.info("Configuration OK: mode=%s warehouse=%s", settings.mode, settings.warehouse)
        return 0

    if args.command == "show-sql":
        from dataclasses import replace

        from .config import SQL_DIR
        from .load.bigquery_warehouse import BigQueryWarehouse
        from .transform.runner import discover_models

        project = settings.gcp_project_id or "your-gcp-project"
        warehouse = BigQueryWarehouse(replace(settings, gcp_project_id=project))
        for model in discover_models(SQL_DIR):
            ddl = warehouse.build_ddl(model.layer, model.name, warehouse.render(model.sql),
                                      dict(model.options))
            print(f"{ddl};\n")
        return 0

    from .pipeline import run_pipeline

    summary = run_pipeline(settings, args.start, args.end, skip_ingest=args.skip_ingest)
    return 0 if summary.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
