"""Branded, client-safe quote PDF.

CRITICAL: this builder receives only the cost-free client-preview payload
(`serialize.client_preview_out`) plus display data — it has no access to cost or
margin, so a confidential figure cannot appear on the client document.

Written to the classic FPDF API so it works with both `fpdf` and `fpdf2`.
Amounts are shown with the ISO currency code (e.g. "INR 1,23,456") rather than
symbols, to stay within the core-font character set.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

from fpdf import FPDF

NAVY = (11, 37, 69)
RED = (226, 59, 46)
MUTED = (106, 120, 136)
LINE = (210, 220, 235)
HEADBG = (243, 248, 252)

COMPANY = "Evavo Wellness & Solutions LLP"
TAGLINE = "Spa Consulting - Spa & Salon Equipment"


def _money(amount_inr: float, rate_to_inr: float, code: str) -> str:
    v = amount_inr / (rate_to_inr or 1.0)
    return f"{code} {v:,.0f}"


def build_quote_pdf(preview: dict, *, currency: str = "INR",
                    rate_to_inr: float = 1.0, terms_body: str = "",
                    quote_date: str | None = None,
                    bill_to_name: str = "", bill_to_email: str = "") -> bytes:
    """`preview` is the dict from serialize.client_preview_out (no cost fields)."""
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    W = pdf.w - 20  # content width with 10mm margins
    pdf.set_left_margin(10)
    pdf.set_right_margin(10)

    # --- Header band ---
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, pdf.w, 34, "F")
    pdf.set_fill_color(*RED)
    pdf.rect(10, 9, 14, 14, "F")
    pdf.set_xy(10, 9)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(14, 14, "EV", 0, 0, "C")
    pdf.set_xy(28, 9)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(100, 6, COMPANY, 0, 2, "L")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(174, 203, 230)
    pdf.cell(100, 5, TAGLINE, 0, 0, "L")
    # meta (right)
    pdf.set_xy(pdf.w - 90, 8)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(80, 6, "QUOTATION", 0, 2, "R")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(174, 203, 230)
    pdf.cell(80, 5, f"No: {preview.get('quote_no', '-')}", 0, 2, "R")
    pdf.cell(80, 5, f"Date: {quote_date or date.today().strftime('%d-%b-%Y')}", 0, 2, "R")
    pdf.cell(80, 5, "Valid: 2 weeks", 0, 0, "R")

    # --- Bill To / currency ---
    pdf.set_xy(10, 42)
    pdf.set_text_color(*MUTED)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(120, 5, "BILL TO", 0, 2, "L")
    pdf.set_text_color(*NAVY)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(120, 6, bill_to_name or preview.get("customer_name", ""), 0, 2, "L")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(70, 88, 106)
    if bill_to_email or preview.get("customer_email"):
        pdf.cell(120, 5, bill_to_email or preview.get("customer_email", ""), 0, 2, "L")
    pdf.set_xy(pdf.w - 90, 42)
    pdf.set_text_color(*MUTED)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(80, 5, "CURRENCY", 0, 2, "R")
    pdf.set_text_color(*NAVY)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(80, 6, currency, 0, 0, "R")

    # --- Line items table ---
    pdf.set_xy(10, 66)
    cols = [(12, "#", "C"), (W - 12 - 38 - 18 - 38, "ITEM", "L"),
            (38, "UNIT PRICE", "R"), (18, "QTY", "R"), (38, "AMOUNT", "R")]
    pdf.set_fill_color(*HEADBG)
    pdf.set_text_color(*MUTED)
    pdf.set_font("Helvetica", "B", 8)
    for w, label, align in cols:
        pdf.cell(w, 8, label, 0, 0, align, True)
    pdf.ln(8)

    pdf.set_text_color(*NAVY)
    pdf.set_draw_color(*LINE)
    for i, ln in enumerate(preview.get("lines", []), start=1):
        pdf.set_font("Helvetica", "", 9)
        y0 = pdf.get_y()
        pdf.cell(cols[0][0], 7, str(i), "B", 0, "C")
        name = ln.get("name", "")
        model = ln.get("model_no") or ""
        item = name + (f"  ({model})" if model else "")
        if len(item) > 60:
            item = item[:57] + "..."
        pdf.cell(cols[1][0], 7, item, "B", 0, "L")
        pdf.cell(cols[2][0], 7, _money(ln["unit_price"], rate_to_inr, currency), "B", 0, "R")
        pdf.cell(cols[3][0], 7, str(int(ln["qty"]) if float(ln["qty"]).is_integer() else ln["qty"]), "B", 0, "R")
        pdf.cell(cols[4][0], 7, _money(ln["line_net"], rate_to_inr, currency), "B", 1, "R")

    # --- Totals (right aligned block) ---
    t = preview.get("totals", {})
    pdf.ln(3)
    tot_x = pdf.w - 10 - 75
    def total_row(label, amount_inr, bold=False, big=False):
        pdf.set_x(tot_x)
        pdf.set_font("Helvetica", "B" if bold else "", 11 if big else 9)
        pdf.set_text_color(*(NAVY if bold else (70, 88, 106)))
        pdf.cell(45, 7 if not big else 9, label, 0, 0, "L")
        pdf.cell(30, 7 if not big else 9, _money(amount_inr, rate_to_inr, currency),
                 "T" if big else 0, 1, "R")
    total_row("Subtotal", t.get("subtotal_net", 0))
    total_row("Installation", t.get("installation", 0))
    total_row("Packaging", preview.get("packaging", 0))
    if preview.get("freight"):
        total_row("Freight / import", preview.get("freight", 0))
    total_row("Grand Total", t.get("grand_total", 0), bold=True, big=True)

    # --- Terms ---
    if terms_body:
        pdf.ln(6)
        pdf.set_x(10)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 6, "Terms & Conditions", 0, 1, "L")
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(91, 107, 123)
        pdf.multi_cell(0, 5, terms_body)
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 5, COMPANY, 0, 1, "L")

    out = pdf.output(dest="S")
    return out.encode("latin-1") if isinstance(out, str) else bytes(out)
