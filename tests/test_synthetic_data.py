import csv

from marketing_pipeline.config import SYNTHETIC_DIR, SYNTHETIC_END, SYNTHETIC_START
from marketing_pipeline.contracts import CONTRACTS
from marketing_pipeline.synthetic.generator import generate


def test_generation_is_deterministic():
    assert generate() == generate()


def test_committed_files_match_generator():
    """The CSVs in data/synthetic must be exactly what the generator produces."""
    data = generate()
    for name, contract in CONTRACTS.items():
        with (SYNTHETIC_DIR / contract.synthetic_file).open(newline="", encoding="utf-8") as fh:
            assert list(csv.DictReader(fh)) == data[name], name


def test_rows_follow_contract_and_window():
    for name, rows in generate().items():
        contract = CONTRACTS[name]
        assert rows, name
        dates = set()
        for row in rows:
            assert tuple(row) == contract.columns
            dates.add(contract.parse_date(row[contract.date_column]))
        assert min(dates) == SYNTHETIC_START and max(dates) == SYNTHETIC_END


def test_ad_exports_contain_duplicates_to_clean():
    for name in ("google_ads", "meta_ads"):
        rows = generate()[name]
        keys = [tuple(r[k] for k in CONTRACTS[name].key) for r in rows]
        assert len(keys) > len(set(keys))


def test_ga4_has_one_row_per_dimension_combination():
    rows = generate()["ga4"]
    keys = [tuple(r[k] for k in CONTRACTS["ga4"].key) for r in rows]
    assert len(keys) == len(set(keys))
