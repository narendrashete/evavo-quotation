"""Quotes router — engine computes totals server-side; lines snapshot prices."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import get_session
from app.core.security import get_current_user, can_see_cost
from app.core.serialize import quote_out, client_preview_out, product_engine_price
from app.core.pricing import compute_quote, QuoteLineInput, AddOns
from app.models import Quote, QuoteLine, Product, FxRate, TermsTemplate, EmailSetup
from app.schemas import QuoteCreate, QuoteStatusUpdate
from app.services.pdf import build_quote_pdf
from app.services.email import send_quote_email

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


def _display_rate(db: Session, currency: str) -> float:
    if currency == "INR":
        return 1.0
    r = db.execute(
        select(FxRate).where(FxRate.currency == currency, FxRate.kind == "display")
        .order_by(FxRate.effective_date.desc())).scalars().first()
    return r.rate_to_inr if r else 1.0


def _terms_body(db: Session, quote: Quote) -> str:
    if not quote.terms_template_id:
        return ""
    t = db.get(TermsTemplate, quote.terms_template_id)
    return (t.body + "\n\nEvavo Wellness & Solutions LLP") if t else ""


def _render_pdf(db: Session, quote: Quote) -> bytes:
    preview = client_preview_out(quote)
    return build_quote_pdf(
        preview, currency=quote.currency,
        rate_to_inr=_display_rate(db, quote.currency),
        terms_body=_terms_body(db, quote),
        bill_to_name=quote.customer_name, bill_to_email=quote.customer_email or "",
        bill_to_address=quote.customer_address or "",
    )


def _fy_code(today: date | None = None) -> str:
    """Indian financial year code, e.g. 25-26 for FY Apr-2025..Mar-2026."""
    today = today or date.today()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _next_quote_no(db: Session) -> str:
    fy = _fy_code()
    prefix = f"EVAVO/QTN/{fy}/"
    n = db.execute(select(func.count(Quote.id)).where(
        Quote.quote_no.like(prefix + "%"))).scalar_one()
    return f"{prefix}{n + 1:04d}"


def _build_lines(db: Session, body: QuoteCreate) -> list[QuoteLine]:
    lines: list[QuoteLine] = []
    for li in body.lines:
        product = db.get(Product, li.product_id) if li.product_id else None
        if product is not None:
            client_unit, final_c2e = product_engine_price(product)
            name = li.name or product.name
            model_no = li.model_no or product.model_no
        else:
            if li.unit_price is None or not li.name:
                raise HTTPException(422, "Free-form line needs name and unit_price")
            client_unit, final_c2e = li.unit_price, 0.0
            name, model_no = li.name, li.model_no
        unit_price = li.unit_price if li.unit_price is not None else client_unit
        lines.append(QuoteLine(
            product_id=li.product_id, name=name, model_no=model_no,
            qty=li.qty, line_disc=li.line_disc,
            unit_price=unit_price, unit_cost=final_c2e,
        ))
    return lines


@router.post("")
def create_quote(body: QuoteCreate, db: Session = Depends(get_session),
                 user=Depends(get_current_user)):
    lines = _build_lines(db, body)
    _, totals = compute_quote(
        [QuoteLineInput(l.unit_price, l.unit_cost, l.qty, l.line_disc) for l in lines],
        AddOns(body.install_enabled, body.install_pct, body.packaging, body.freight),
    )
    quote = Quote(
        quote_no=_next_quote_no(db), client_id=body.client_id,
        customer_name=body.customer_name, customer_email=body.customer_email,
        customer_address=body.customer_address,
        currency=body.currency, terms_template_id=body.terms_template_id,
        install_enabled=body.install_enabled, install_pct=body.install_pct,
        packaging=body.packaging, freight=body.freight,
        subtotal_net=totals.subtotal_net, grand_total=totals.grand_total,
        total_cost=totals.total_cost, needs_approval=totals.needs_approval,
        lines=lines,
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return quote_out(quote, can_see_cost(user.role))


@router.get("")
def list_quotes(db: Session = Depends(get_session), user=Depends(get_current_user)):
    rows = db.execute(select(Quote).order_by(Quote.id.desc())).scalars().all()
    include = can_see_cost(user.role)
    return [{
        "id": q.id, "quote_no": q.quote_no, "customer_name": q.customer_name,
        "status": q.status, "currency": q.currency,
        "grand_total": round(q.grand_total, 2), "needs_approval": q.needs_approval,
        **({"total_cost": round(q.total_cost, 2)} if include else {}),
    } for q in rows]


@router.get("/{quote_id}")
def get_quote(quote_id: int, db: Session = Depends(get_session),
              user=Depends(get_current_user)):
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    return quote_out(q, can_see_cost(user.role))


@router.get("/{quote_id}/preview")
def preview_quote(quote_id: int, db: Session = Depends(get_session),
                  user=Depends(get_current_user)):
    """Client-safe preview — selling prices only, no cost ever (any role)."""
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    return client_preview_out(q)


@router.patch("/{quote_id}/status")
def set_status(quote_id: int, body: QuoteStatusUpdate,
               db: Session = Depends(get_session), user=Depends(get_current_user)):
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    if body.status not in ("draft", "sent", "negotiation", "won"):
        raise HTTPException(422, "Invalid status")
    if q.needs_approval and body.status == "sent" and not can_see_cost(user.role):
        raise HTTPException(403, "Quote needs manager approval before it can be sent")
    q.status = body.status
    db.commit()
    return {"id": q.id, "status": q.status}


@router.get("/{quote_id}/pdf")
def quote_pdf(quote_id: int, db: Session = Depends(get_session),
              user=Depends(get_current_user)):
    """Branded, client-safe PDF (no cost — built from the preview payload)."""
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    pdf = _render_pdf(db, q)
    fname = q.quote_no.replace("/", "_") + ".pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.post("/{quote_id}/email")
def quote_email(quote_id: int, db: Session = Depends(get_session),
                user=Depends(get_current_user)):
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    if q.needs_approval and not can_see_cost(user.role):
        raise HTTPException(403, "Quote needs manager approval before it can be emailed")
    if not q.customer_email:
        raise HTTPException(422, "Quote has no client email address")
    pdf = _render_pdf(db, q)
    setup = db.execute(select(EmailSetup)).scalars().first()
    result = send_quote_email(
        setup, to_email=q.customer_email,
        subject=f"Quotation {q.quote_no} - Evavo Wellness & Solutions LLP",
        body=(f"Dear {q.customer_name},\n\nPlease find attached our quotation "
              f"{q.quote_no}.\n\nRegards,\nEvavo Wellness & Solutions LLP"),
        pdf_bytes=pdf, pdf_name=q.quote_no.replace("/", "_") + ".pdf")
    if result.get("sent") and q.status == "draft":
        q.status = "sent"
        db.commit()
    return result


@router.post("/{quote_id}/revise")
def revise_quote(quote_id: int, db: Session = Depends(get_session),
                 user=Depends(get_current_user)):
    """Create an editable draft revision of an existing quote (keeps history)."""
    src = db.get(Quote, quote_id)
    if not src:
        raise HTTPException(404, "Quote not found")
    rev = Quote(
        quote_no=_next_quote_no(db), client_id=src.client_id,
        customer_name=src.customer_name, customer_email=src.customer_email,
        customer_address=src.customer_address,
        currency=src.currency, terms_template_id=src.terms_template_id,
        install_enabled=src.install_enabled, install_pct=src.install_pct,
        packaging=src.packaging, freight=src.freight,
        subtotal_net=src.subtotal_net, grand_total=src.grand_total,
        total_cost=src.total_cost, needs_approval=src.needs_approval,
        revision_of=src.id, status="draft",
        lines=[QuoteLine(product_id=l.product_id, name=l.name, model_no=l.model_no,
                         qty=l.qty, line_disc=l.line_disc, unit_price=l.unit_price,
                         unit_cost=l.unit_cost) for l in src.lines],
    )
    db.add(rev)
    db.commit()
    db.refresh(rev)
    return quote_out(rev, can_see_cost(user.role))
