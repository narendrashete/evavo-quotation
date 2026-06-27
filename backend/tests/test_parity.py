"""Parity gate: the engine must reproduce every Excel row within tolerance.

Skipped automatically if the client workbooks aren't present (e.g. CI without
the source sheets), so the unit tests still run standalone.
"""

import glob
import os

import pytest

from app.importer.excel_import import import_all, DEFAULT_SHEETS_DIR
from app.importer.parity_check import check, TOLERANCE


def _have_sheets() -> bool:
    return bool(glob.glob(os.path.join(DEFAULT_SHEETS_DIR, "*.xlsx")))


pytestmark = pytest.mark.skipif(
    not _have_sheets(), reason="client Excel workbooks not available")


def test_all_rows_within_tolerance():
    records = import_all()
    assert len(records) > 150, "expected the full product master to import"
    diffs = check(records)
    bad = [d for d in diffs if not d.within]
    assert not bad, (
        f"{len(bad)} rows out of tolerance ({TOLERANCE} INR); "
        f"first: {bad[0].rec.name!r} cost {bad[0].cost_diff:+.2f} "
        f"client {bad[0].client_diff:+.2f}"
    )


def test_max_diff_is_essentially_zero():
    diffs = check(import_all())
    max_cost = max(abs(d.cost_diff) for d in diffs)
    max_client = max(abs(d.client_diff) for d in diffs)
    assert max_cost <= TOLERANCE and max_client <= TOLERANCE
