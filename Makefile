.PHONY: install data run test lint sql clean

install:
	pip install -e ".[dev]"

data:            ## regenerate the synthetic datasets
	python -m marketing_pipeline generate-data

run:             ## full pipeline on synthetic data, local DuckDB warehouse
	python -m marketing_pipeline run

test:
	pytest -q

lint:
	ruff check .

sql:             ## print the BigQuery DDL for every model
	python -m marketing_pipeline show-sql

clean:
	rm -rf artifacts data/landing .pytest_cache .ruff_cache
