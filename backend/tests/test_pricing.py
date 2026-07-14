"""Unit tests for the pricing engine (no DB, no Excel needed)."""

import math

from app.core.pricing import (
    PricingInputs, MarkupBase, compute_unit, compute_line, compute_quote,
    QuoteLineInput, AddOns, convert_for_display, strip_confidential,
    CONFIDENTIAL_FIELDS,
)


def test_unit_buildup_matches_ghareni_row():
    # Ghareni "Salon Equipments" row 4 (MANICURE TABLE MANO):
    # c2e_inr (N) = 280264.2, loading 1.5, markup 2, list uplift 0.10
    inp = PricingInputs(
        source_price=280264.2, fx_rate=1.0, conversion_factor=1.0,
        loading_factor=1.5, client_markup=2.0, list_uplift=0.10,
        markup_base=MarkupBase.FINAL_C2E,
    )
    u = compute_unit(inp)
    assert math.isclose(u.final_c2e, 420396.3, abs_tol=0.01)
    assert math.isclose(u.client_unit_price, 840792.6, abs_tol=0.01)
    assert math.isclose(u.list_price, 924871.86, abs_tol=0.01)


def test_accessories_markup_base_is_pre_loading():
    # Accessories: client = c2e_inr * 2 (NOT final_c2e * 2)
    inp = PricingInputs(
        source_price=1000.0, loading_factor=1.5, client_markup=2.0,
        markup_base=MarkupBase.C2E_INR,
    )
    u = compute_unit(inp)
    assert u.final_c2e == 1500.0          # 1000 * 1.5
    assert u.client_unit_price == 2000.0  # 1000 * 2  (pre-loading base)


def test_line_margin_and_discount():
    r = compute_line(unit_price=1000.0, final_c2e=400.0, qty=2, line_disc=10.0)
    assert r.line_gross == 2000.0
    assert r.line_net == 1800.0            # 2000 * 0.9
    assert r.line_cost == 800.0            # 400 * 2
    assert r.line_margin == 1000.0         # 1800 - 800
    assert math.isclose(r.margin_pct, 1000.0 / 1800.0 * 100.0)


def test_quote_installation_and_grand_total():
    lines = [QuoteLineInput(unit_price=1000.0, final_c2e=400.0, qty=1, line_disc=0.0)]
    _, totals = compute_quote(lines, AddOns(install_enabled=True, install_pct=0.105,
                                            packaging=500.0))
    assert totals.subtotal_net == 1000.0
    assert math.isclose(totals.installation, 105.0)        # 10.5%
    assert math.isclose(totals.grand_total, 1605.0)        # 1000 + 105 + 500 (pre-tax)
    # No GST configured -> no tax, final payable == grand total.
    assert totals.gst_total == 0.0
    assert math.isclose(totals.final_payable, 1605.0)


def test_editable_installation_charge_overrides_pct():
    lines = [QuoteLineInput(unit_price=1000.0, final_c2e=400.0, qty=1)]
    # install_amount overrides the 10.5% computation entirely.
    _, totals = compute_quote(lines, AddOns(install_amount=250.0, install_pct=0.105))
    assert totals.installation == 250.0
    assert math.isclose(totals.grand_total, 1250.0)        # 1000 + 250


def test_freight_breakdown_sums_into_grand_total():
    lines = [QuoteLineInput(unit_price=1000.0, final_c2e=400.0, qty=1)]
    _, totals = compute_quote(lines, AddOns(install_enabled=False, local_freight=100.0,
                                            intl_freight=200.0, import_charge=50.0))
    assert totals.freight == 350.0                          # 100 + 200 + 50
    assert math.isclose(totals.grand_total, 1350.0)         # 1000 + 0 install + 350


def test_gst_intra_state_splits_cgst_sgst():
    # Home state 27, POS 27 -> intra-state -> CGST=SGST=half.
    lines = [QuoteLineInput(unit_price=1000.0, final_c2e=400.0, qty=1, gst_pct=18.0)]
    _, totals = compute_quote(lines, AddOns(install_enabled=False, gst_default_pct=18.0,
                                            home_state="27", place_of_supply="27"))
    assert totals.is_intra_state is True
    assert math.isclose(totals.taxable_amount, 1000.0)      # goods only, no install/freight
    assert math.isclose(totals.gst_total, 180.0)            # 18% of 1000
    assert math.isclose(totals.cgst, 90.0)
    assert math.isclose(totals.sgst, 90.0)
    assert totals.igst == 0.0
    assert math.isclose(totals.final_payable, 1180.0)


def test_gst_inter_state_uses_igst():
    lines = [QuoteLineInput(unit_price=1000.0, final_c2e=400.0, qty=1, gst_pct=18.0)]
    _, totals = compute_quote(lines, AddOns(install_enabled=False, gst_default_pct=18.0,
                                            home_state="27", place_of_supply="29"))
    assert totals.is_intra_state is False
    assert math.isclose(totals.igst, 180.0)
    assert totals.cgst == 0.0 and totals.sgst == 0.0
    assert math.isclose(totals.final_payable, 1180.0)


def test_gst_composite_taxable_includes_installation_and_freight():
    # GST applies to goods + installation + freight (composite supply).
    lines = [QuoteLineInput(unit_price=1000.0, final_c2e=400.0, qty=1, gst_pct=18.0)]
    _, totals = compute_quote(lines, AddOns(install_amount=200.0, local_freight=100.0,
                                            gst_default_pct=18.0,
                                            home_state="27", place_of_supply="27"))
    # taxable = 1000 goods + 200 install + 100 freight = 1300
    assert math.isclose(totals.taxable_amount, 1300.0)
    # gst = 18% of goods (180) + 18% of (200+100) addons (54) = 234
    assert math.isclose(totals.gst_total, 234.0)
    assert math.isclose(totals.final_payable, 1534.0)       # 1300 + 234


def test_quote_approval_triggers_on_overall_discount():
    # 20% line discount -> overall > 12% threshold AND line > 15% threshold.
    lines = [QuoteLineInput(unit_price=1000.0, final_c2e=400.0, qty=1, line_disc=20.0)]
    _, totals = compute_quote(lines)
    assert totals.needs_approval is True


def test_quote_no_approval_under_threshold():
    lines = [QuoteLineInput(unit_price=1000.0, final_c2e=400.0, qty=1, line_disc=9.0)]
    _, totals = compute_quote(lines)
    assert totals.needs_approval is False


def test_display_conversion():
    assert math.isclose(convert_for_display(83500.0, 83.5), 1000.0)
    assert convert_for_display(900.0, 1.0) == 900.0  # INR -> INR


def test_strip_confidential_removes_cost_fields():
    d = {"client_unit_price": 100, "final_c2e": 40, "margin": 60, "name": "x"}
    out = strip_confidential(d)
    assert "final_c2e" not in out and "margin" not in out
    assert out["client_unit_price"] == 100 and out["name"] == "x"
    # every confidential key is genuinely excluded
    assert not (set(out) & CONFIDENTIAL_FIELDS)
