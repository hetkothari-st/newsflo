"""Parsing an Input-Output Transaction Table into direct input coefficients.

THE SOURCE. India's Supply-Use Tables / Input-Output Transaction Tables
(MOSPI; RBI KLEMS for the industry-level series). Published as spreadsheets:
one row and one column per industry, the cell being the value of the row
industry's output consumed as an input by the column industry, plus a total
row. No such file is in this repo, and none is generated here -- DATA_GAPS §7
names the acquisition work and its owner.

THE NORMALISATION. `a(A->B)` is A's cell in B's column divided by B's TOTAL
INPUT. That denominator has to come from the table; computing it as the
column sum would quietly redefine the coefficient as a share of
INTERMEDIATE input only, which is a different (and larger) number. So the
parser demands an explicit total row and refuses a column without one.

PROVENANCE IS MANDATORY. `table_year` and `source_url` are required
arguments and are refused when empty: an input-output table without its year
and its URL is a matrix of numbers with no claim attached, and the master
context does not allow one of those into this system.
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# The row carrying each column industry's total input. Named explicitly
# rather than inferred, so a table that spells it differently fails loudly
# and gets a mapping rather than a wrong denominator.
TOTAL_INPUT_LABELS = ("TOTAL_INPUT", "TOTAL INPUT", "Total input",
                      "Total Input", "TOTAL_INPUTS")
INDUSTRY_COLUMN_LABELS = ("industry", "Industry", "INDUSTRY", "code", "Code")


class IOTableError(ValueError):
    """The table is not a usable input-output transaction table."""


@dataclass(frozen=True)
class IOTable:
    industries: tuple[str, ...]
    direct_coefficients: np.ndarray
    table_year: int
    source_url: str


def _read(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt"):
        return pd.read_csv(path)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    raise IOTableError(f"unsupported input-output table format: {suffix!r}")


def parse_transaction_table(path: Path | str, *, table_year: int,
                            source_url: str) -> IOTable:
    """One published transaction table to direct input coefficients."""
    if not source_url:
        raise IOTableError(
            "an input-output table needs its source URL: a coefficient with "
            "no published origin is not evidence of anything")
    if not table_year:
        raise IOTableError(
            "an input-output table needs its year: coefficients age, and an "
            "undated matrix cannot be compared with a newer one")

    frame = _read(path)
    label_column = next((c for c in frame.columns
                         if str(c) in INDUSTRY_COLUMN_LABELS), None)
    if label_column is None:
        raise IOTableError(
            f"no industry label column; expected one of {INDUSTRY_COLUMN_LABELS}")

    frame = frame.set_index(label_column)
    totals_label = next((label for label in frame.index
                         if str(label) in TOTAL_INPUT_LABELS), None)
    if totals_label is None:
        raise IOTableError(
            "the table has no total-input row, so a(A->B) has no denominator; "
            f"expected one of {TOTAL_INPUT_LABELS}")

    totals = frame.loc[totals_label]
    matrix = frame.drop(index=totals_label)

    industries = tuple(str(name) for name in matrix.index)
    columns = tuple(str(name) for name in matrix.columns)
    if industries != columns:
        raise IOTableError(
            "the transaction matrix is not square in its labels: rows "
            f"{industries} vs columns {columns}")

    values = matrix.to_numpy(dtype=float)
    denominators = totals.to_numpy(dtype=float)
    if not np.isfinite(denominators).all() or (denominators <= 0).any():
        bad = [industries[i] for i, total in enumerate(denominators)
               if not np.isfinite(total) or total <= 0]
        raise IOTableError(
            f"total input is missing or non-positive for {bad}; a(A->B) "
            "cannot be computed for those industries and is NOT defaulted")

    return IOTable(industries=industries,
                   direct_coefficients=values / denominators,
                   table_year=int(table_year), source_url=str(source_url))
