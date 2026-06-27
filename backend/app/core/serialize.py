"""Role-gated serializers — the single place cost/margin can leak, so guard here.

`include_cost` is derived from the caller's role (see security.can_see_cost).
The client-preview/PDF path always passes include_cost=False, so confidential
fields are structurally impossible to emit there.
"""

from __future__ import annotations

from app.core.pricing import (
    PricingInputs, MarkupBase, compute_unit, compute_quote, QuoteLineInput, AddOns,
)


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


def product_out(product, include_cost: bool) -> dict:
    client_unit, final_c2e = product_engine_price(product)
    out = {
        "id": product.id,
        "name": product.name,
        "model_no": product.model_no,
        "category": product.category,
        "description": product.description,
        "product_link": product.product_link,
        "image": product.image,
        "client_unit_price": round(client_unit, 2),
        "list_price": round(client_unit * (1 + product.list_uplift), 2),
        "is_manual_override": product.is_manual_override,
    }
    if include_cost:
        out["final_c2e"] = round(final_c2e, 2)        # CONFIDENTIAL
        out["margin"] = round(client_unit - final_c2e, 2)
        out["margin_pct"] = round(
            (client_unit - final_c2e) / client_unit * 100, 1) if client_unit else 0.0
        out["source_price_inr"] = product.source_price_inr
    return out


def quote_out(quote, include_cost: bool) -> dict:
    """Serialize a stored quote, recomputing totals from line snapshots."""
    line_inputs = [
        QuoteLineInput(unit_price=l.unit_price, final_c2e=l.unit_cost,
                       qty=l.qty, line_disc=l.line_disc)
        for l in quote.lines
    ]
    results, totals = compute_quote(
        line_inputs,
        AddOns(install_enabled=quote.install_enabled, install_pct=quote.install_pct,
               packaging=quote.packaging, freight=quote.freight),
    )

    lines = []
    for l, r in zip(quote.lines, results):
        item = {
            "id": l.id, "product_id": l.product_id, "name": l.name,
            "model_no": l.model_no, "qty": l.qty, "line_disc": l.line_disc,
            "unit_price": round(l.unit_price, 2), "line_net": round(r.line_net, 2),
        }
        if include_cost:
            item["unit_cost"] = round(l.unit_cost, 2)        # CONFIDENTIAL
            item["line_margin"] = round(r.line_margin, 2)
            item["margin_pct"] = round(r.margin_pct, 1)
        lines.append(item)

    out = {
        "id": quote.id, "quote_no": quote.quote_no, "status": quote.status,
        "customer_name": quote.customer_name, "customer_email": quote.customer_email,
        "currency": quote.currency, "terms_template_id": quote.terms_template_id,
        "install_enabled": quote.install_enabled, "install_pct": quote.install_pct,
        "packaging": quote.packaging, "freight": quote.freight,
        "lines": lines,
        "totals": {
            "subtotal_net": round(totals.subtotal_net, 2),
            "discount_given": round(totals.discount_given, 2),
            "installation": round(totals.installation, 2),
            "grand_total": round(totals.grand_total, 2),
            "needs_approval": totals.needs_approval,
        },
    }
    if include_cost:
        out["totals"]["total_cost"] = round(totals.total_cost, 2)     # CONFIDENTIAL
        out["totals"]["total_margin"] = round(totals.total_margin, 2)
        out["totals"]["margin_pct"] = round(totals.margin_pct, 1)
    return out


def client_preview_out(quote) -> dict:
    """Client-safe payload — selling prices only, cost structurally excluded."""
    return quote_out(quote, include_cost=False)
