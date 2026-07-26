"""Role-gated serializers — the single place cost/margin can leak, so guard here.

`include_cost` is derived from the caller's role (see security.can_see_cost).
The client-preview/PDF path always passes include_cost=False, so confidential
fields are structurally impossible to emit there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.pricing import (
    PricingInputs, MarkupBase, compute_unit, compute_quote, QuoteLineInput, AddOns,
    DEFAULT_LINE_DISC_PCT,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def product_engine_price(product) -> tuple[float, float]:
    """Return (client_unit_price, final_c2e) for a product via the engine.

    Override rows keep their migrated values verbatim; everything else is the
    live engine computation (identical to the migrated value at import time).
    """
    if product.is_manual_override and product.migrated_client_unit is not None:
        return product.migrated_client_unit, (product.migrated_final_c2e or 0.0)
    u = compute_unit(PricingInputs(
        source_price=product.source_price_inr,
        loading_factor=product.loading_factor,
        client_markup=product.client_markup,
        list_uplift=product.list_uplift,
        markup_base=MarkupBase(product.markup_base),
    ))
    return u.client_unit_price, u.final_c2e


def root_quote_no(quote_no: str) -> str:
    """The original quotation number a revision belongs to.

    Revisions are numbered "<original>-R1", "-R2", ... so the original reads
    straight off the number — no extra query to resolve `root_quote_id`.
    """
    base, sep, suffix = (quote_no or "").rpartition("-R")
    return base if sep and suffix.isdigit() else quote_no


def product_out(product, include_cost: bool) -> dict:
    """Client-safe product row.

    `unit_price` is the list price a quote line starts from, and
    `discounted_unit_price` is that less the standard discount — the two figures
    the Product master and the Quote Builder both display. `list_price` is kept
    as an alias of `unit_price` for older readers.
    """
    client_unit, final_c2e = product_engine_price(product)
    unit_price = client_unit * (1 + product.list_uplift)
    out = {
        "id": product.id,
        "name": product.name,
        "model_no": product.model_no,
        "category": product.category,
        "area_category": product.area_category,
        "description": product.description,
        "product_link": product.product_link,
        "image": product.image,
        "hsn_code": product.hsn_code,
        "gst_pct": product.gst_pct,
        "client_unit_price": round(client_unit, 2),
        "unit_price": round(unit_price, 2),
        "discounted_unit_price": round(unit_price * (1 - DEFAULT_LINE_DISC_PCT / 100.0), 2),
        "default_disc_pct": DEFAULT_LINE_DISC_PCT,
        "list_price": round(unit_price, 2),
        "is_manual_override": product.is_manual_override,
    }
    if include_cost:
        out["final_c2e"] = round(final_c2e, 2)        # CONFIDENTIAL
        out["margin"] = round(client_unit - final_c2e, 2)
        out["margin_pct"] = round(
            (client_unit - final_c2e) / client_unit * 100, 1) if client_unit else 0.0
        out["source_price_inr"] = product.source_price_inr
    return out


def quote_out(quote, include_cost: bool, db: "Session | None" = None) -> dict:
    """Serialize a stored quote, recomputing totals from line snapshots.

    Add-on and GST parameters come from the quote's snapshot columns, so the
    recomputed totals reproduce exactly what was saved. Tax fields (HSN, GST,
    CGST/SGST/IGST, taxable/final payable) are client-safe — emitted for every
    role; only cost/margin stay behind `include_cost`.

    `db`, if given, is used to batch-fetch each line's current `Product.image`
    and `Product.description` (the specification — neither is snapshotted on
    `QuoteLine`) for callers that need them, e.g. PDF rendering. Omitted by
    default so existing JSON callers are unaffected.
    """
    images_by_product: dict[int, str | None] = {}
    specs_by_product: dict[int, str | None] = {}
    if db is not None:
        from app.models import Product  # local import: avoid a serialize<->models cycle
        product_ids = {l.product_id for l in quote.lines if l.product_id is not None}
        if product_ids:
            rows = db.execute(
                select(Product.id, Product.image, Product.description)
                .where(Product.id.in_(product_ids))
            ).all()
            images_by_product = {pid: image for pid, image, _ in rows}
            specs_by_product = {pid: spec for pid, _, spec in rows}

    line_inputs = [
        QuoteLineInput(unit_price=l.unit_price, final_c2e=l.unit_cost,
                       qty=l.qty, line_disc=l.line_disc, gst_pct=l.gst_pct,
                       area_category=l.area_category or "")
        for l in quote.lines
    ]
    results, totals = compute_quote(
        line_inputs,
        AddOns(install_enabled=quote.install_enabled, install_pct=quote.install_pct,
               install_dry_pct=quote.install_dry_pct, install_wet_pct=quote.install_wet_pct,
               install_amount=quote.install_amount, packaging=quote.packaging,
               local_freight=quote.local_freight, intl_freight=quote.intl_freight,
               import_charge=quote.import_charge, gst_default_pct=quote.gst_default_pct,
               overall_disc_pct=quote.overall_disc_pct,
               overall_disc_amount=quote.overall_disc_amount,
               home_state=quote.home_state or "", place_of_supply=quote.place_of_supply or ""),
    )

    lines = []
    for l, r in zip(quote.lines, results):
        item = {
            "id": l.id, "product_id": l.product_id, "name": l.name,
            "model_no": l.model_no, "qty": l.qty, "line_disc": l.line_disc,
            "hsn_code": l.hsn_code, "gst_pct": r.gst_pct,
            "gst_amount": round(r.gst_amount, 2),
            "area_category": l.area_category,
            "unit_price": round(l.unit_price, 2),
            "discounted_unit_price": round(l.unit_price * (1 - l.line_disc / 100.0), 2),
            "line_net": round(r.line_net, 2),
            "image": images_by_product.get(l.product_id),
            "specification": specs_by_product.get(l.product_id),
        }
        if include_cost:
            item["unit_cost"] = round(l.unit_cost, 2)        # CONFIDENTIAL
            item["line_margin"] = round(r.line_margin, 2)
            item["margin_pct"] = round(r.margin_pct, 1)
        lines.append(item)

    out = {
        "id": quote.id, "quote_no": quote.quote_no, "status": quote.status,
        "approved": quote.approved,
        "customer_name": quote.customer_name, "customer_email": quote.customer_email,
        "customer_address": quote.customer_address, "customer_mobile": quote.customer_mobile,
        "currency": quote.currency, "terms_template_id": quote.terms_template_id,
        "install_enabled": quote.install_enabled, "install_pct": quote.install_pct,
        "install_dry_pct": quote.install_dry_pct, "install_wet_pct": quote.install_wet_pct,
        "install_amount": quote.install_amount, "packaging": quote.packaging,
        "freight": round(totals.freight, 2),
        "local_freight": quote.local_freight, "intl_freight": quote.intl_freight,
        "import_charge": quote.import_charge,
        "overall_disc_pct": quote.overall_disc_pct,
        "overall_disc_amount": quote.overall_disc_amount,
        "place_of_supply": quote.place_of_supply, "home_state": quote.home_state,
        "gst_default_pct": quote.gst_default_pct,
        # Revision chain — see Quote.revision_no/root_quote_id in models.py.
        "revision_no": quote.revision_no, "revision_of": quote.revision_of,
        "root_quote_id": quote.root_quote_id or quote.id,
        "root_quote_no": root_quote_no(quote.quote_no),
        "created_at": quote.created_at.isoformat() if quote.created_at else None,
        "lines": lines,
        "totals": {
            "subtotal_net": round(totals.subtotal_net, 2),
            "discount_given": round(totals.discount_given, 2),
            "overall_discount": round(totals.overall_discount, 2),
            "goods_net": round(totals.goods_net, 2),
            "installation": round(totals.installation, 2),
            "install_dry": round(totals.install_dry, 2),
            "install_wet": round(totals.install_wet, 2),
            "install_other": round(totals.install_other, 2),
            "grand_total": round(totals.grand_total, 2),
            "taxable_amount": round(totals.taxable_amount, 2),
            "gst_total": round(totals.gst_total, 2),
            "cgst": round(totals.cgst, 2),
            "sgst": round(totals.sgst, 2),
            "igst": round(totals.igst, 2),
            "is_intra_state": totals.is_intra_state,
            "final_payable": round(totals.final_payable, 2),
            "needs_approval": totals.needs_approval,
        },
    }
    if include_cost:
        out["totals"]["total_cost"] = round(totals.total_cost, 2)     # CONFIDENTIAL
        out["totals"]["total_margin"] = round(totals.total_margin, 2)
        out["totals"]["margin_pct"] = round(totals.margin_pct, 1)
    return out


def client_preview_out(quote, db: "Session | None" = None) -> dict:
    """Client-safe payload — selling prices only, cost structurally excluded."""
    return quote_out(quote, include_cost=False, db=db)
