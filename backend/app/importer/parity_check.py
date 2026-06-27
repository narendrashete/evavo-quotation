"""Parity test: prove the server-side engine reproduces the Excel numbers.

For every imported product, recompute unit cost (Excel P) and client unit price
(Excel R) with `pricing.compute_unit` and compare to the workbook's cached value.
This is the go/no-go gate for Phase 1 — before any cutover we want the new engine
to match the old spreadsheet to within rounding.

Run as a module:  python -m app.importer.parity_check
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.pricing import compute_unit
from app.importer.excel_import import import_all, ProductRecord, DEFAULT_SHEETS_DIR

# Absolute INR tolerance for "matches the spreadsheet".
TOLERANCE = 0.5


@dataclass
class RowDiff:
    rec: ProductRecord
    cost_diff: float
    client_diff: float

    @property
    def within(self) -> bool:
        return abs(self.cost_diff) <= TOLERANCE and abs(self.client_diff) <= TOLERANCE


def check(records: list[ProductRecord]) -> list[RowDiff]:
    diffs: list[RowDiff] = []
    for rec in records:
        u = compute_unit(rec.to_pricing_inputs())
        cost_diff = (u.final_c2e - (rec.migrated_final_c2e or 0.0)) \
            if rec.migrated_final_c2e is not None else 0.0
        client_diff = u.client_unit_price - (rec.migrated_client_unit or 0.0)
        diffs.append(RowDiff(rec, cost_diff, client_diff))
    return diffs


def report(sheets_dir: str = DEFAULT_SHEETS_DIR) -> dict:
    records = import_all(sheets_dir)
    diffs = check(records)

    by_cat: dict[str, int] = {}
    for r in records:
        by_cat[r.category] = by_cat.get(r.category, 0) + 1

    overrides = [r for r in records if r.is_manual_override]
    mismatches = [d for d in diffs if not d.within]
    max_cost = max((abs(d.cost_diff) for d in diffs), default=0.0)
    max_client = max((abs(d.client_diff) for d in diffs), default=0.0)

    print("=" * 72)
    print("EVAVO PRICING ENGINE — PARITY REPORT")
    print("=" * 72)
    print(f"Source dir         : {sheets_dir}")
    print(f"Products imported  : {len(records)}")
    for cat, n in sorted(by_cat.items()):
        print(f"    {cat:<22}: {n}")
    print(f"Manual overrides   : {len(overrides)} (kept as migrated values)")
    print(f"Max |cost diff|    : {max_cost:.6f} INR")
    print(f"Max |client diff|  : {max_client:.6f} INR")
    print(f"Rows out of tol.   : {len(mismatches)} (tolerance {TOLERANCE} INR)")
    print("-" * 72)

    if mismatches:
        print("MISMATCHES (engine != spreadsheet):")
        for d in mismatches[:40]:
            print(f"  [{d.rec.source_sheet} r{d.rec.source_row}] {d.rec.name[:34]:<34} "
                  f"cost {d.cost_diff:+.2f}  client {d.client_diff:+.2f}  "
                  f"{'OVERRIDE' if d.rec.is_manual_override else ''}")
    else:
        print("All rows reproduce the spreadsheet within tolerance.  PASS")

    if overrides:
        print("-" * 72)
        print("OVERRIDE ROWS (non-standard formulas — verify before go-live):")
        for r in overrides[:40]:
            print(f"  [{r.source_sheet} r{r.source_row}] {r.name[:30]:<30} "
                  f"-> {'; '.join(r.override_reasons)}")

    return {
        "products": len(records),
        "by_category": by_cat,
        "overrides": len(overrides),
        "max_cost_diff": max_cost,
        "max_client_diff": max_client,
        "mismatches": len(mismatches),
    }


if __name__ == "__main__":
    report()
