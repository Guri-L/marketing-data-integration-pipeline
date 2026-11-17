"""Extractor interface and the synthetic (file-backed) implementation."""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from ..contracts import SourceContract
from ..exceptions import ExtractionError

Record = dict[str, str]


class Extractor(ABC):
    """Returns raw records for a date window, shaped like the source contract."""

    def __init__(self, contract: SourceContract) -> None:
        self.contract = contract

    @abstractmethod
    def extract(self, start: date, end: date) -> list[Record]:
        """All rows with ``start <= date <= end``. Values are strings as delivered."""


class SyntheticExtractor(Extractor):
    """Reads the committed synthetic export instead of calling the API."""

    def __init__(self, contract: SourceContract, data_dir: Path) -> None:
        super().__init__(contract)
        self.path = data_dir / contract.synthetic_file

    def extract(self, start: date, end: date) -> list[Record]:
        if not self.path.exists():
            raise ExtractionError(
                f"Synthetic file not found: {self.path}. Run `marketing-pipeline generate-data`."
            )
        with self.path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        selected = []
        for row in rows:
            try:
                in_window = start <= self.contract.parse_date(row[self.contract.date_column]) <= end
            except (KeyError, ValueError):
                in_window = True  # keep malformed rows so validation can report them
            if in_window:
                selected.append(row)
        return selected
