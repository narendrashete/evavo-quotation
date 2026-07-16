"""Branded, client-safe quote PDFs.

Two documents: the **Detailed** quote is a multi-page *Proposal* — a cover page
(logo + spa hero image + "Proposal for" block + address footer), box-bordered
body page(s) with the full line-item table + totals and no footer, then a Terms
& Conditions page with dynamic `# Heading` sections. The **Summary** quote keeps
the compact single-page legacy layout (name + qty + amount).

CRITICAL: these builders receive only the cost-free client-preview payload
(`serialize.client_preview_out`) plus display data — no access to cost or
margin, so a confidential figure cannot appear on either client document.

Written to the classic FPDF API so it works with both `fpdf` and `fpdf2`.
Amounts are shown with the ISO currency code (e.g. "INR 1,23,456") rather than
symbols, to stay within the core-font character set.
"""

from __future__ import annotations

import os
from datetime import date

from fpdf import FPDF

NAVY = (11, 37, 69)
RED = (226, 59, 46)
MUTED = (106, 120, 136)
LINE = (210, 220, 235)
HEADBG = (222, 233, 246)
ZEBRA_BG = (241, 245, 250)   # totals-box alternate-row shading
FINAL_BG = (224, 232, 243)   # totals-box "Final Payable" row highlight

COMPANY = "Evavo Wellness & Solutions LLP"
TAGLINE = "Spa Consulting - Spa & Salon Equipment"

# Company footer details for the Proposal cover / terms pages, verbatim from the
# client's letterhead. If these ever need to be admin-editable, move them into
# AppSettings — for now they're fixed, like COMPANY above.
ADDRESS = "Shop N.5, Opp Lady Ratan Tower, Gandhi Nagar, Worli, Mumbai 400018 MAHARASHTRA"
PHONE = "022 6660 6636 / 35"
EMAIL = "info@evavo.com"
WEB = "www.evavo.com"

# `Product.image` is stored as a relative path like "/static/product_images/x.jpg"
# (served by the StaticFiles mount in main.py), not an absolute URL — resolve it
# to a real file on disk rather than fetching over HTTP.
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")


def _resolve_image_path(image: str | None) -> str | None:
    if not image:
        return None
    rel = image[len("/static/"):] if image.startswith("/static/") else image.lstrip("/")
    path = os.path.join(_STATIC_DIR, rel)
    return path if os.path.isfile(path) else None


def _brand_path(name: str) -> str | None:
    """Resolve a swappable branding asset under static/branding/ (logo, cover).

    Returns None if the file is absent so the proposal still renders (just
    without that image) when an admin removes or renames it.
    """
    path = os.path.join(_STATIC_DIR, "branding", name)
    return path if os.path.isfile(path) else None


def _money(amount_inr: float, rate_to_inr: float, code: str) -> str:
    v = amount_inr / (rate_to_inr or 1.0)
    return f"{code} {v:,.0f}"


def _item_text(ln: dict, max_len: int) -> str:
    """Item name + model, collapsed to a single logical line and length-capped.

    Product names in this catalog can contain embedded newlines and long
    model numbers (e.g. multi-variant products); capping length keeps the
    text within its allotted table cell instead of overflowing into the row
    below.
    """
    name = (ln.get("name") or "").replace("\n", " ")
    model = ln.get("model_no") or ""
    item = " ".join((name + (f" ({model})" if model else "")).split())
    if len(item) > max_len:
        item = item[: max_len - 3] + "..."
    return item


def _draw_header_and_billto(pdf: FPDF, preview: dict, *, currency: str,
                            quote_date: str | None, bill_to_name: str,
                            bill_to_email: str, bill_to_address: str) -> int:
    """Draws the navy header band + Bill To / currency block shared by both
    quote documents. Returns the number of address lines drawn, so callers can
    compute where the line-items table should start."""
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
    address = bill_to_address or preview.get("customer_address") or ""
    address_lines = [ln for ln in address.splitlines() if ln.strip()][:2]
    for ln in address_lines:
        pdf.cell(120, 5, ln, 0, 2, "L")
    pdf.set_xy(pdf.w - 90, 42)
    pdf.set_text_color(*MUTED)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(80, 5, "CURRENCY", 0, 2, "R")
    pdf.set_text_color(*NAVY)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(80, 6, currency, 0, 0, "R")
    return len(address_lines)


def _draw_totals(pdf: FPDF, preview: dict, *, rate_to_inr: float, currency: str) -> None:
    """Totals as a shaded, gridded box — an outer border + fill, a thin grid
    line under each row, light zebra shading, and a highlighted Final Payable
    band — so the numbers read as one unit instead of loose floating cells.
    Shared by both the Detailed (Proposal) and Summary PDFs.
    """
    t = preview.get("totals", {})
    pdf.ln(3)

    rows: list[tuple[str, float, bool]] = [
        ("Subtotal", t.get("subtotal_net", 0), False),
        ("Installation", t.get("installation", 0), False),
    ]
    if preview.get("packaging"):
        rows.append(("Packaging", preview.get("packaging", 0), False))
    if preview.get("freight"):
        rows.append(("Freight & import", preview.get("freight", 0), False))
    rows.append(("Taxable Amount", t.get("taxable_amount", 0), False))
    if t.get("is_intra_state"):
        rows.append(("CGST", t.get("cgst", 0), False))
        rows.append(("SGST", t.get("sgst", 0), False))
    elif t.get("gst_total", 0):
        rows.append(("IGST", t.get("igst", 0), False))
    rows.append(("Final Payable", t.get("final_payable", 0), True))

    label_w, amt_w = 45, 30
    pad = 3.5
    row_h, final_h = 7.2, 9.5
    tot_x = pdf.w - pdf.r_margin - (label_w + amt_w)
    box_x = tot_x - pad
    box_w = label_w + amt_w + pad * 2
    box_y = pdf.get_y()
    box_h = row_h * (len(rows) - 1) + final_h + pad * 2

    pdf.set_fill_color(250, 252, 254)
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.3)
    pdf.rect(box_x, box_y, box_w, box_h, "DF")

    y = box_y + pad
    for i, (label, amount_inr, bold) in enumerate(rows):
        is_final = i == len(rows) - 1
        h = final_h if is_final else row_h
        if is_final:
            pdf.set_fill_color(*FINAL_BG)
            pdf.rect(box_x, y, box_w, h, "F")
            pdf.set_draw_color(*NAVY)
            pdf.set_line_width(0.35)
            pdf.line(box_x, y, box_x + box_w, y)
        else:
            if i % 2 == 1:
                pdf.set_fill_color(*ZEBRA_BG)
                pdf.rect(box_x, y, box_w, h, "F")
            pdf.set_draw_color(*LINE)
            pdf.set_line_width(0.15)
            pdf.line(box_x, y + h, box_x + box_w, y + h)
        pdf.set_xy(tot_x, y)
        pdf.set_font("Helvetica", "B" if bold else "", 11 if is_final else 9)
        pdf.set_text_color(*(NAVY if bold else (70, 88, 106)))
        pdf.cell(label_w, h, label, 0, 0, "L")
        pdf.cell(amt_w, h, _money(amount_inr, rate_to_inr, currency), 0, 0, "R")
        y += h

    pdf.set_xy(pdf.l_margin, box_y + box_h + 4)


def _draw_terms(pdf: FPDF, terms_body: str) -> None:
    if not terms_body:
        return
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


def _new_pdf() -> tuple[FPDF, float]:
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_left_margin(10)
    pdf.set_right_margin(10)
    return pdf, pdf.w - 20


# --- Proposal (Detailed) document --------------------------------------------

_PROP_MARGIN = 12       # left/right text margin on body/terms pages
_BORDER_INSET = 7       # box-border inset from the page edge
_LOGO_W = 13             # top-left logo width on body/terms pages
_LOGO_ASPECT = 113 / 78  # extracted logo.png's natural h/w — used only to
                        # estimate chrome layout spacing if it's ever swapped
                        # for an image with a different aspect, the running
                        # header just gets a little tighter/looser, not broken


def _parse_terms_sections(body: str) -> list[tuple[str, str]]:
    """Split a terms body into (heading, text) sections.

    Convention: a line beginning with "# " opens a new section whose heading is
    the text after the hash; following lines accumulate as that section's body
    until the next heading. Text before the first heading becomes a leading
    section with an empty heading. A body with no "# " renders as one block, so
    legacy plain templates still print correctly.
    """
    sections: list[tuple[str, list[str]]] = []
    for raw in (body or "").splitlines():
        if raw.lstrip().startswith("# "):
            sections.append((raw.lstrip()[2:].strip(), []))
        else:
            if not sections:
                sections.append(("", []))
            sections[-1][1].append(raw)
    out: list[tuple[str, str]] = []
    for heading, lines in sections:
        text = "\n".join(lines).strip("\n")
        if heading or text.strip():
            out.append((heading, text))
    return out


class ProposalPDF(FPDF):
    """Multi-part proposal: a cover page, box-bordered body pages (line items +
    totals) with no footer, and a terms page — logo + address footer on the
    cover/terms pages only.

    `header()`/`footer()` fire automatically on every page (including on
    auto-page-break overflow), so the box border, top-left logo and footer are
    re-applied without the callers tracking pages. The page's mode is promoted
    from `_pending_mode` inside `header()` so that the *previous* page's
    `footer()` — which fpdf runs at the start of the next `add_page()` — still
    sees the previous page's mode.

    Every page after the cover also carries the Quotation No/Date and Bill To
    name/contact as running "chrome": the full two-block layout on the first
    body page (page 2 — the one right after the cover), and a compact
    one-line version on every page after that (further body pages plus the
    Terms page), to save vertical space. `set_info()` must be called before
    any page is added, since `header()` reads it while drawing page 2+.
    """

    def __init__(self) -> None:
        super().__init__(unit="mm", format="A4")
        self.mode = "cover"
        self._pending_mode: str | None = "cover"
        self.set_auto_page_break(auto=True, margin=22)
        self.set_left_margin(_PROP_MARGIN)
        self.set_right_margin(_PROP_MARGIN)
        self.set_top_margin(38)  # body overflow rows resume below the logo
        self.alias_nb_pages()   # "{nb}" -> total page count, resolved at output()
        self._content_top = 30.0  # overwritten by header() before any content draws
        self._quote_no = self._quote_date = self._bill_to_name = ""
        self._bill_to_email = self._bill_to_mobile = self._bill_to_address = ""

    def add_mode_page(self, mode: str) -> None:
        self._pending_mode = mode
        self.add_page()

    def set_info(self, *, quote_no: str, quote_date: str, bill_to_name: str,
                bill_to_email: str, bill_to_mobile: str, bill_to_address: str) -> None:
        """Quotation No/Date + Bill To details for the running chrome drawn on
        every page after the cover. Call before add_mode_page("cover")."""
        self._quote_no = quote_no
        self._quote_date = quote_date
        self._bill_to_name = bill_to_name
        self._bill_to_email = bill_to_email
        self._bill_to_mobile = bill_to_mobile  # also the client's WhatsApp number
        self._bill_to_address = bill_to_address

    def _draw_logo(self, x: float, y: float, w: float) -> None:
        logo = _brand_path("logo.png")
        if logo:
            self.image(logo, x=x, y=y, w=w)  # h=0 keeps aspect ratio

    def _draw_chrome_full(self) -> None:
        """Full Quotation + Bill To block — first body page (page 2) only."""
        x = self.w - 90
        w = self.w - _PROP_MARGIN - x
        y = _BORDER_INSET + 4
        self.set_xy(x, y)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*NAVY)
        self.cell(w, 6, "QUOTATION", 0, 2, "R")
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(*MUTED)
        self.cell(w, 5, f"No: {self._quote_no}", 0, 2, "R")
        self.cell(w, 5, f"Date: {self._quote_date}", 0, 2, "R")
        self.cell(w, 5, "Valid: 2 weeks", 0, 0, "R")

        logo_bottom = _BORDER_INSET + 4 + _LOGO_W * _LOGO_ASPECT
        meta_bottom = y + 6 + 5 + 5 + 5
        y2 = max(logo_bottom, meta_bottom) + 4
        self.set_xy(_PROP_MARGIN, y2)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, "BILL TO", 0, 1, "L")
        self.set_x(_PROP_MARGIN)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*NAVY)
        self.cell(0, 6, self._bill_to_name, 0, 1, "L")

        self.set_font("Helvetica", "", 9)
        self.set_text_color(70, 88, 106)
        for ln in [l for l in (self._bill_to_address or "").splitlines() if l.strip()][:2]:
            self.set_x(_PROP_MARGIN)
            self.cell(0, 5, ln, 0, 1, "L")

        contact_bits = []
        if self._bill_to_email:
            contact_bits.append(self._bill_to_email)
        if self._bill_to_mobile:
            contact_bits.append(f"WhatsApp: {self._bill_to_mobile}")
        if contact_bits:
            self.set_x(_PROP_MARGIN)
            self.cell(0, 5, "   |   ".join(contact_bits), 0, 1, "L")
        self._content_top = self.get_y() + 6

    def _draw_chrome_compact(self) -> None:
        """One-line Quotation/Bill To/Date summary — every page after page 2."""
        logo_bottom = _BORDER_INSET + 4 + _LOGO_W * _LOGO_ASPECT
        y = logo_bottom + 3
        self.set_xy(_PROP_MARGIN, y)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        line = (f"Quotation No: {self._quote_no}    |    "
                f"Bill To: {self._bill_to_name}    |    Date: {self._quote_date}")
        self.cell(0, 5, line, 0, 1, "L")
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        yy = self.get_y() + 1
        self.line(_PROP_MARGIN, yy, self.w - _PROP_MARGIN, yy)
        self._content_top = yy + 5

    def header(self) -> None:  # noqa: D401 - fpdf callback
        if self._pending_mode is not None:
            self.mode = self._pending_mode
            self._pending_mode = None
        if self.mode == "cover":
            return
        # box border around the whole page
        self.set_draw_color(*NAVY)
        self.set_line_width(0.4)
        self.rect(_BORDER_INSET, _BORDER_INSET,
                  self.w - 2 * _BORDER_INSET, self.h - 2 * _BORDER_INSET)
        self.set_line_width(0.2)
        self._draw_logo(_PROP_MARGIN, _BORDER_INSET + 4, _LOGO_W)
        if self.mode == "body" and self.page_no() == 2:
            self._draw_chrome_full()
        else:
            self._draw_chrome_compact()

    def _draw_page_number(self) -> None:
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*MUTED)
        self.set_xy(0, self.h - 6)
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", 0, 0, "C")

    def footer(self) -> None:  # noqa: D401 - fpdf callback
        self._draw_page_number()
        if self.mode == "body":
            return  # in-between pages carry no address footer, to save print space
        y = self.h - 22
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.line(_PROP_MARGIN, y, self.w - _PROP_MARGIN, y)
        self.set_xy(0, y + 2)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 4.5, ADDRESS, 0, 2, "C")
        self.cell(0, 4.5, f"Phone: {PHONE}    Email: {EMAIL}    {WEB}", 0, 0, "C")


def _draw_cover(pdf: ProposalPDF, preview: dict, *, quote_date: str | None,
                bill_to_name: str) -> None:
    """Proposal cover: centered logo, spa hero image, 'Proposal for' block and
    (via the page footer) the company address/contact."""
    W = pdf.w
    # centered logo near the top
    logo = _brand_path("logo.png")
    logo_w = 20
    if logo:
        pdf.image(logo, x=(W - logo_w) / 2, y=14, w=logo_w)

    # spa hero image, full content width (aspect preserved by fpdf)
    cover = _brand_path("cover.jpg")
    img_w = W - 2 * 18
    img_y = 48
    if cover:
        pdf.image(cover, x=18, y=img_y, w=img_w)
        img_h = img_w * 466 / 700  # extracted cover is 700x466
    else:
        img_h = 0

    y = img_y + img_h + 22
    pdf.set_xy(0, y)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 8, "Proposal for:", 0, 2, "C")
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 11, bill_to_name or preview.get("customer_name", ""), 0, 2, "C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(70, 88, 106)
    pdf.cell(0, 7, f"Prepared by {COMPANY}", 0, 2, "C")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, f"Date: {quote_date or date.today().strftime('%d-%b-%Y')}", 0, 2, "C")


_ROW_H = 18


def _draw_line_items(pdf: ProposalPDF, preview: dict, *, rate_to_inr: float,
                     currency: str) -> None:
    """Line-item table (image + HSN + GST columns) on the box-bordered body
    pages. Starts below the top-left logo; overflows to further body pages.

    Auto page-break is turned off here and rows are paginated manually: fpdf's
    mid-cell auto break would invalidate the per-row `y0` bookkeeping (the image
    and item text are positioned by absolute y), so instead we start a fresh
    body page whenever the next row/totals block would cross the bottom margin.
    """
    W = pdf.w - 2 * _PROP_MARGIN
    cols = [(10, "#", "C"), (W - 10 - 22 - 34 - 14 - 16 - 34, "ITEM", "L"),
            (22, "HSN", "L"), (34, "UNIT PRICE", "R"), (14, "QTY", "R"),
            (16, "GST%", "R"), (34, "AMOUNT", "R")]
    bottom = pdf.h - 22

    def draw_col_header() -> None:
        pdf.set_xy(_PROP_MARGIN, pdf._content_top)
        pdf.set_fill_color(*HEADBG)
        pdf.set_text_color(*MUTED)
        pdf.set_font("Helvetica", "B", 8)
        for w, label, align in cols:
            pdf.cell(w, 8, label, 0, 0, align, True)
        pdf.ln(8)

    pdf.set_auto_page_break(False)
    draw_col_header()

    ROW_H = _ROW_H
    IMG_SIZE = 14
    PAD = 1.5
    pdf.set_text_color(*NAVY)
    pdf.set_draw_color(*LINE)
    for i, ln in enumerate(preview.get("lines", []), start=1):
        if pdf.get_y() + ROW_H > bottom:
            pdf.add_mode_page("body")
            draw_col_header()
        # reset per row: draw_col_header leaves MUTED text, and header() (on a
        # new body page) leaves the draw color NAVY from the box border.
        pdf.set_text_color(*NAVY)
        pdf.set_draw_color(*LINE)
        y0 = pdf.get_y()
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(cols[0][0], ROW_H, str(i), "B", 0, "C")
        x_item = pdf.get_x()
        pdf.cell(cols[1][0], ROW_H, "", "B", 0, "L")
        pdf.cell(cols[2][0], ROW_H, str(ln.get("hsn_code") or "-"), "B", 0, "L")
        pdf.cell(cols[3][0], ROW_H, _money(ln["unit_price"], rate_to_inr, currency), "B", 0, "R")
        pdf.cell(cols[4][0], ROW_H, str(int(ln["qty"]) if float(ln["qty"]).is_integer() else ln["qty"]), "B", 0, "R")
        pdf.cell(cols[5][0], ROW_H, f"{ln.get('gst_pct', 0):g}%", "B", 0, "R")
        pdf.cell(cols[6][0], ROW_H, _money(ln["line_net"], rate_to_inr, currency), "B", 1, "R")

        img_path = _resolve_image_path(ln.get("image"))
        if img_path:
            pdf.image(img_path, x=x_item + PAD, y=y0 + PAD, w=IMG_SIZE, h=IMG_SIZE)
        else:
            pdf.set_draw_color(*LINE)
            pdf.rect(x_item + PAD, y0 + PAD, IMG_SIZE, IMG_SIZE)
            pdf.set_xy(x_item + PAD, y0 + PAD + IMG_SIZE / 2 - 2)
            pdf.set_font("Helvetica", "", 5.5)
            pdf.set_text_color(*MUTED)
            pdf.multi_cell(IMG_SIZE, 3, "No image", 0, "C")

        text_x = x_item + IMG_SIZE + PAD * 2
        text_w = cols[1][0] - IMG_SIZE - PAD * 3
        pdf.set_xy(text_x, y0 + PAD)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*NAVY)
        pdf.multi_cell(text_w, 4.2, _item_text(ln, max_len=46), 0, "L")
        pdf.set_xy(_PROP_MARGIN, y0 + ROW_H)

    # keep the whole totals block together — new body page if it won't fit
    if pdf.get_y() + 72 > bottom:
        pdf.add_mode_page("body")
        pdf.set_xy(_PROP_MARGIN, pdf._content_top)
    _draw_totals(pdf, preview, rate_to_inr=rate_to_inr, currency=currency)
    pdf.set_auto_page_break(True, margin=22)


def _draw_terms_page(pdf: ProposalPDF, terms_body: str) -> None:
    """Terms & Conditions page: centered title, then each `# Heading` section as
    a bold + underlined headline over its body (matching the reference)."""
    sections = _parse_terms_sections(terms_body)
    pdf.set_xy(_PROP_MARGIN, pdf._content_top)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, "Terms And Conditions", 0, 1, "C")
    pdf.ln(4)
    for heading, text in sections:
        if heading:
            pdf.set_x(_PROP_MARGIN)
            pdf.set_font("Helvetica", "BU", 9.5)
            pdf.set_text_color(*NAVY)
            pdf.cell(0, 6, heading, 0, 1, "L")
        if text.strip():
            pdf.set_x(_PROP_MARGIN)
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(91, 107, 123)
            pdf.multi_cell(pdf.w - 2 * _PROP_MARGIN, 4.6, text, 0, "L")
        pdf.ln(3)


def build_quote_pdf(preview: dict, *, currency: str = "INR",
                    rate_to_inr: float = 1.0, terms_body: str = "",
                    quote_date: str | None = None,
                    bill_to_name: str = "", bill_to_email: str = "",
                    bill_to_address: str = "") -> bytes:
    """Detailed quote as a branded Proposal: a cover page, box-bordered body
    page(s) with the full line-item table + totals, and a Terms & Conditions
    page. `preview` is the dict from serialize.client_preview_out (no cost
    fields). `bill_to_email`/`bill_to_address` are not printed on the cover,
    but do appear in the Bill To block on page 2 (the first body page)."""
    pdf = ProposalPDF()
    qdate = quote_date or date.today().strftime("%d-%b-%Y")
    pdf.set_info(
        quote_no=preview.get("quote_no", "-"), quote_date=qdate,
        bill_to_name=bill_to_name or preview.get("customer_name", ""),
        bill_to_email=bill_to_email or preview.get("customer_email") or "",
        bill_to_mobile=preview.get("customer_mobile") or "",
        bill_to_address=bill_to_address or preview.get("customer_address") or "",
    )

    pdf.add_mode_page("cover")
    _draw_cover(pdf, preview, quote_date=quote_date, bill_to_name=bill_to_name)

    pdf.add_mode_page("body")
    _draw_line_items(pdf, preview, rate_to_inr=rate_to_inr, currency=currency)

    if _parse_terms_sections(terms_body):
        pdf.add_mode_page("terms")
        _draw_terms_page(pdf, terms_body)

    out = pdf.output(dest="S")
    return out.encode("latin-1") if isinstance(out, str) else bytes(out)


def build_quote_summary_pdf(preview: dict, *, currency: str = "INR",
                            rate_to_inr: float = 1.0, terms_body: str = "",
                            quote_date: str | None = None,
                            bill_to_name: str = "", bill_to_email: str = "",
                            bill_to_address: str = "") -> bytes:
    """Condensed quote: item name + qty + amount only (no HSN/GST/unit-price
    columns, no photos). Shares the exact same totals block as the Detailed
    quote (build_quote_pdf) so the two documents can never disagree on the
    final amount payable."""
    pdf, W = _new_pdf()
    address_lines = _draw_header_and_billto(
        pdf, preview, currency=currency, quote_date=quote_date,
        bill_to_name=bill_to_name, bill_to_email=bill_to_email,
        bill_to_address=bill_to_address)

    pdf.set_xy(10, 66 + 5 * address_lines)
    cols = [(10, "#", "C"), (W - 10 - 24 - 34, "ITEM", "L"),
            (24, "QTY", "R"), (34, "AMOUNT", "R")]
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
        pdf.cell(cols[0][0], 7, str(i), "B", 0, "C")
        pdf.cell(cols[1][0], 7, _item_text(ln, max_len=60), "B", 0, "L")
        pdf.cell(cols[2][0], 7, str(int(ln["qty"]) if float(ln["qty"]).is_integer() else ln["qty"]), "B", 0, "R")
        pdf.cell(cols[3][0], 7, _money(ln["line_net"], rate_to_inr, currency), "B", 1, "R")

    _draw_totals(pdf, preview, rate_to_inr=rate_to_inr, currency=currency)
    _draw_terms(pdf, terms_body)

    out = pdf.output(dest="S")
    return out.encode("latin-1") if isinstance(out, str) else bytes(out)
