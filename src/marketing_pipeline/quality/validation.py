"""Pre-load validation of extracted records against the source contract.

Structural problems (wrong columns, empty extract) fail the source. Row-level
problems quarantine the row; the source fails only if too many rows are bad.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import SourceContract
from ..exceptions import ValidationError

MAX_REJECT_RATE = 0.05


@dataclass
class ValidationResult:
    valid: list[dict[str, str]]
    rejected: list[dict[str, str]] = field(default_factory=list)  # row + _reject_reason

    @property
    def reject_rate(self) -> float:
        total = len(self.valid) + len(self.rejected)
        return len(self.rejected) / total if total else 0.0


def _row_problem(contract: SourceContract, row: dict[str, str]) -> str | None:
    empty = [c for c in contract.required if not str(row.get(c) or "").strip()]
    if empty:
        return f"empty required field(s): {', '.join(empty)}"
    try:
        contract.parse_date(row[contract.date_column])
    except ValueError:
        return f"unparseable {contract.date_column}: {row[contract.date_column]!r}"
    return None


def validate_records(
    contract: SourceContract,
    records: list[dict[str, str]],
    *,
    allow_empty: bool = False,
    max_reject_rate: float = MAX_REJECT_RATE,
) -> ValidationResult:
    if not records:
        if allow_empty:
            return ValidationResult(valid=[])
        raise ValidationError(f"{contract.name}: extract returned no rows")

    expected = set(contract.columns)
    actual = set(records[0])
    if actual != expected:
        missing, extra = sorted(expected - actual), sorted(actual - expected)
        raise ValidationError(
            f"{contract.name}: schema drift - missing columns {missing}, unexpected columns {extra}"
        )

    result = ValidationResult(valid=[])
    for row in records:
        problem = _row_problem(contract, row)
        if problem:
            result.rejected.append({**row, "_reject_reason": problem})
        else:
            result.valid.append(row)

    if result.reject_rate > max_reject_rate:
        raise ValidationError(
            f"{contract.name}: {len(result.rejected)} of {len(records)} rows rejected "
            f"({result.reject_rate:.1%} > {max_reject_rate:.0%} allowed); "
            f"first reason: {result.rejected[0]['_reject_reason']}"
        )
    return result
