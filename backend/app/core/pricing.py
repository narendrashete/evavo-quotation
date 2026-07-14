"""Evavo pricing engine — the single, server-side source of truth.

This is the logic reverse-engineered from the client Excel master sheets
(Salon, Massage Beds, Loungers, Accessories). In the spreadsheets the cost
build-up, FX rates, markups and the client selling price all lived in one
workbook that got emailed to clients. Here that logic is promoted into a pure,
unit-tested module so it can be computed server-side and the cost/margin half
can be withheld from anyone in a "sales" role (and from the client PDF entirely).

The build-up, expressed once, matching the Excel columns:

    c2e_inr   = source_price * fx_rate * conversion_factor     # Excel N / O ("C2E")
    final_c2e = c2e_inr * loading_factor                       # Excel P ("Final C2E") -> true unit cost
    client    = markup_base * client_markup                    # Excel R ("Quote 2 Client") -> unit selling price
    list      = client * (1 + list_uplift)                     # Excel E ("Unit Price / Ex Works")

Where, per the spreadsheets:
  * source_price       — supplier price: EUR/USD "MRP FX", INR "MRP", or "OLD C2E".
  * fx_rate            — procurement FX (EUR 115 / USD 100 / INR 1), per the S/T columns.
  * conversion_factor  — supplier discount as (1 - disc), e.g. 0.80, or an uplift as
                         (1 + uplift), e.g. 1.20/1.30/1.90 — whichever the sheet used.
  * loading_factor     — landing/loading multiplier (typically 1.5; some rows 1.35).
  * client_markup      — markup to client (typically 2.0; some override rows 1.7/1.8).
  * markup_base        — what the client markup multiplies: the "final_c2e" (most
                         sheets) or the pre-loading "c2e_inr" (the Accessories sheet).

NOTE: procurement FX (100/115, used to *build* the INR cost) is deliberately
distinct from the *display* FX used to show a quote to a client in USD/EUR
(see convert_for_display). Do not conflate them.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional


# Default add-on / policy constants, ported from the prototype recalc().
DEFAULT_INSTALL_PCT = 0.105          # Installation ~= 10.5% of equipment value
DEFAULT_LIST_UPLIFT = 0.10           # List price = client price * 1.10 (shows a discount)
DEFAULT_LOADING_FACTOR = 1.5
DEFAULT_CLIENT_MARKUP = 2.0

# Approval guardrails (prototype: overall > 12% OR any single line > 15%).
APPROVAL_OVERALL_DISC_PCT = 12.0
APPROVAL_LINE_DISC_PCT = 15.0


class MarkupBase(str, Enum):
    FINAL_C2E = "final_c2e"   # client = final_c2e * markup  (most sheets)
    C2E_INR = "c2e_inr"       # client = c2e_inr   * markup  (Accessories sheet)


@dataclass(frozen=True)
class PricingInputs:
    """The stored, per-product parameters that drive the build-up.

    These replace the hand-typed Excel constants. They live on the product (or a
    category pricing-rule) so each product family keeps its own numbers, and FX
    is looked up from a dated rate table rather than typed per row.
    """
    source_price: float
    fx_rate: float = 1.0
    conversion_factor: float = 1.0
    loading_factor: float = DEFAULT_LOADING_FACTOR
    client_markup: float = DEFAULT_CLIENT_MARKUP
    list_uplift: float = DEFAULT_LIST_UPLIFT
    markup_base: MarkupBase = MarkupBase.FINAL_C2E


@dataclass(frozen=True)
class UnitPricing:
    """Per-unit results of the build-up. `final_c2e` is CONFIDENTIAL (cost)."""
    c2e_inr: float          # cost-to-Evavo in INR, before loading (Excel N/O)
    final_c2e: float        # true unit cost in INR (Excel P) — CONFIDENTIAL
    client_unit_price: float  # unit selling price in INR (Excel R)
    list_price: float       # inflated list price in INR (Excel E)


def compute_unit(inp: PricingInputs) -> UnitPricing:
    """Forward cost->price build-up for a single unit. Pure function."""
    c2e_inr = inp.source_price * inp.fx_rate * inp.conversion_factor
    final_c2e = c2e_inr * inp.loading_factor
    base = final_c2e if inp.markup_base == MarkupBase.FINAL_C2E else c2e_inr
    client_unit_price = base * inp.client_markup
    list_price = client_unit_price * (1.0 + inp.list_uplift)
    return UnitPricing(
        c2e_inr=c2e_inr,
        final_c2e=final_c2e,
        client_unit_price=client_unit_price,
        list_price=list_price,
    )


@dataclass(frozen=True)
class LineResult:
    qty: float
    line_disc: float            # 0..100 (percent)
    unit_price: float           # client unit selling price (INR)
    line_gross: float           # unit_price * qty
    line_net: float             # after line discount (INR)
    gst_pct: float              # GST rate applied to this line (client-safe)
    gst_amount: float           # line_net * gst_pct/100 (INR, client-safe)
    line_cost: float            # final_c2e * qty (INR) — CONFIDENTIAL
    line_margin: float          # line_net - line_cost — CONFIDENTIAL
    margin_pct: float           # CONFIDENTIAL


def compute_line(unit_price: float, final_c2e: float, qty: float,
                 line_disc: float = 0.0, gst_pct: float = 0.0) -> LineResult:
    """Line economics. Mirrors the prototype recalc() per-row math."""
    line_gross = unit_price * qty
    line_net = line_gross * (1.0 - line_disc / 100.0)
    gst_amount = line_net * gst_pct / 100.0
    line_cost = final_c2e * qty
    line_margin = line_net - line_cost
    margin_pct = (line_margin / line_net * 100.0) if line_net > 0 else 0.0
    return LineResult(
        qty=qty, line_disc=line_disc, unit_price=unit_price,
        line_gross=line_gross, line_net=line_net,
        gst_pct=gst_pct, gst_amount=gst_amount,
        line_cost=line_cost, line_margin=line_margin, margin_pct=margin_pct,
    )


@dataclass
class QuoteLineInput:
    unit_price: float       # client unit selling price (INR)
    final_c2e: float        # unit cost (INR) — CONFIDENTIAL
    qty: float = 1.0
    line_disc: float = 0.0  # percent
    gst_pct: float = 0.0    # GST rate for this line's goods


@dataclass(frozen=True)
class AddOns:
    install_enabled: bool = True
    install_pct: float = DEFAULT_INSTALL_PCT
    packaging: float = 0.0        # flat INR
    # Freight/import breakdown (all flat INR). `freight` (kept for back-compat)
    # is the local+intl+import sum, exposed on QuoteTotals for old readers.
    local_freight: float = 0.0
    intl_freight: float = 0.0
    import_charge: float = 0.0
    # When set, overrides `subtotal_net * install_pct` — supports an editable
    # flat installation *charge* rather than a percentage.
    install_amount: Optional[float] = None
    # GST rate applied to installation + freight + import (which carry no per-line
    # HSN of their own). Also the default used when a line has no rate.
    gst_default_pct: float = 0.0
    # Place-of-supply routing: intra-state (== home_state) -> CGST+SGST, else IGST.
    home_state: str = ""
    place_of_supply: str = ""


@dataclass(frozen=True)
class QuoteTotals:
    subtotal_net: float        # sum of line_net (INR)
    discount_given: float      # gross - net (INR)
    installation: float        # INR
    packaging: float
    freight: float             # local + intl + import (back-compat sum)
    local_freight: float
    intl_freight: float
    import_charge: float
    grand_total: float         # pre-tax total (subtotal + install + pack + freight)
    taxable_amount: float      # base GST is charged on (goods + install + freight)
    gst_total: float           # total GST (INR)
    cgst: float                # intra-state half
    sgst: float                # intra-state half
    igst: float                # inter-state full
    is_intra_state: bool
    final_payable: float       # taxable_amount + gst_total
    overall_disc_pct: float
    needs_approval: bool
    # Confidential block:
    total_cost: float          # sum line_cost (INR) — CONFIDENTIAL
    total_margin: float        # subtotal_net - total_cost — CONFIDENTIAL
    margin_pct: float          # CONFIDENTIAL


def compute_quote(lines: list[QuoteLineInput], addons: Optional[AddOns] = None,
                  overall_threshold: float = APPROVAL_OVERALL_DISC_PCT,
                  line_threshold: float = APPROVAL_LINE_DISC_PCT) -> tuple[list[LineResult], QuoteTotals]:
    """Whole-quote roll-up incl. add-ons, GST and the approval guardrail.

    Returns (per-line results, totals). The CONFIDENTIAL fields on the results
    must be stripped before any sales-role or client-facing serialization. GST
    is layered on top of the pre-tax `grand_total`; `final_payable` carries the
    tax-inclusive figure.
    """
    addons = addons or AddOns()
    results: list[LineResult] = []
    subtotal_net = 0.0
    gross = 0.0
    total_cost = 0.0
    goods_gst = 0.0
    any_line_over = False

    for ln in lines:
        r = compute_line(ln.unit_price, ln.final_c2e, ln.qty, ln.line_disc, ln.gst_pct)
        results.append(r)
        subtotal_net += r.line_net
        gross += r.line_gross
        total_cost += r.line_cost
        goods_gst += r.gst_amount
        if ln.line_disc > line_threshold:
            any_line_over = True

    discount_given = gross - subtotal_net
    if addons.install_amount is not None:
        installation = addons.install_amount
    else:
        installation = subtotal_net * addons.install_pct if addons.install_enabled else 0.0
    freight = addons.local_freight + addons.intl_freight + addons.import_charge
    grand_total = subtotal_net + installation + addons.packaging + freight

    # GST: per-line rate on goods; the default rate on install + freight + import
    # (packaging is treated as part of the freight/handling base for GST too).
    addon_taxable = installation + addons.packaging + freight
    taxable_amount = subtotal_net + addon_taxable
    gst_total = goods_gst + addon_taxable * addons.gst_default_pct / 100.0

    is_intra_state = bool(addons.home_state) and addons.place_of_supply == addons.home_state
    if is_intra_state:
        cgst = sgst = gst_total / 2.0
        igst = 0.0
    else:
        cgst = sgst = 0.0
        igst = gst_total
    final_payable = taxable_amount + gst_total

    overall_disc_pct = (discount_given / gross * 100.0) if gross > 0 else 0.0
    needs_approval = overall_disc_pct > overall_threshold or any_line_over
    total_margin = subtotal_net - total_cost
    margin_pct = (total_margin / subtotal_net * 100.0) if subtotal_net > 0 else 0.0

    totals = QuoteTotals(
        subtotal_net=subtotal_net,
        discount_given=discount_given,
        installation=installation,
        packaging=addons.packaging,
        freight=freight,
        local_freight=addons.local_freight,
        intl_freight=addons.intl_freight,
        import_charge=addons.import_charge,
        grand_total=grand_total,
        taxable_amount=taxable_amount,
        gst_total=gst_total,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        is_intra_state=is_intra_state,
        final_payable=final_payable,
        overall_disc_pct=overall_disc_pct,
        needs_approval=needs_approval,
        total_cost=total_cost,
        total_margin=total_margin,
        margin_pct=margin_pct,
    )
    return results, totals


# --- Display currency conversion (distinct from procurement FX) ---------------

def convert_for_display(amount_inr: float, display_rate_to_inr: float) -> float:
    """Convert an INR amount to a display currency.

    `display_rate_to_inr` is "how many INR per 1 unit of the target currency"
    (e.g. USD 83.50, EUR 90.00). INR uses 1.0. This is the client-facing rate,
    NOT the procurement FX (100/115) used to build cost.
    """
    if display_rate_to_inr <= 0:
        raise ValueError("display_rate_to_inr must be > 0")
    return amount_inr / display_rate_to_inr


# Fields that must NEVER reach a sales-role API response or a client document.
CONFIDENTIAL_FIELDS = frozenset({
    "c2e_inr", "final_c2e", "line_cost", "line_margin", "margin_pct",
    "total_cost", "total_margin", "cost", "margin",
})


def strip_confidential(d: dict) -> dict:
    """Remove cost/margin keys from a dict (defense-in-depth for serializers)."""
    return {k: v for k, v in d.items() if k not in CONFIDENTIAL_FIELDS}


def line_result_to_dict(r: LineResult, include_cost: bool) -> dict:
    d = asdict(r)
    return d if include_cost else strip_confidential(d)


def quote_totals_to_dict(t: QuoteTotals, include_cost: bool) -> dict:
    d = asdict(t)
    return d if include_cost else strip_confidential(d)
