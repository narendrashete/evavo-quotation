"""Quotes router — engine computes totals server-side; lines snapshot prices."""

from __future__ import annotations

import dataclasses
import logging
import re
import secrets
from datetime import date, datetime
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_session
from app.core.security import get_current_user, can_see_cost, require_role
from app.core.serialize import quote_out, client_preview_out, product_engine_price
from app.core.pricing import compute_quote, QuoteLineInput, AddOns
from app.models import Quote, QuoteLine, Product, FxRate, TermsTemplate, EmailSetup, AppSettings
from app.schemas import QuoteCreate, QuoteStatusUpdate
from app.services.pdf import build_quote_pdf, build_quote_summary_pdf
from app.services.email import send_quote_email

router = APIRouter(prefix="/api/quotes", tags=["quotes"])
logger = logging.getLogger(__name__)


def _display_rate(db: Session, currency: str) -> float:
    if currency == "INR":
        return 1.0
    r = db.execute(
        select(FxRate).where(FxRate.currency == currency, FxRate.kind == "display")
        # id DESC as a tiebreaker: multiple rates can now be added on the same
        # calendar day (e.g. clicking "Refresh Live Rates" more than once),
        # and effective_date alone doesn't disambiguate which is newest.
        .order_by(FxRate.effective_date.desc(), FxRate.id.desc())).scalars().first()
    return r.rate_to_inr if r else 1.0


def _terms_body(db: Session, quote: Quote, *, append_company: bool = True) -> str:
    if not quote.terms_template_id:
        return ""
    t = db.get(TermsTemplate, quote.terms_template_id)
    if not t:
        return ""
    # The legacy Summary PDF footer expects the company name appended to the
    # body; the Proposal's own address footer already carries it, so callers
    # for the Proposal pass append_company=False.
    return t.body + "\n\nEvavo Wellness & Solutions LLP" if append_company else t.body


def _quote_date(quote: Quote) -> str:
    return (quote.created_at or datetime.utcnow()).strftime("%d-%b-%Y")


def _render_pdf(db: Session, quote: Quote) -> bytes:
    preview = client_preview_out(quote, db=db)
    return build_quote_pdf(
        preview, currency=quote.currency,
        rate_to_inr=_display_rate(db, quote.currency),
        terms_body=_terms_body(db, quote, append_company=False),
        quote_date=_quote_date(quote),
        bill_to_name=quote.customer_name, bill_to_email=quote.customer_email or "",
        bill_to_address=quote.customer_address or "",
    )


def _render_summary_pdf(db: Session, quote: Quote) -> bytes:
    preview = client_preview_out(quote)
    return build_quote_summary_pdf(
        preview, currency=quote.currency,
        rate_to_inr=_display_rate(db, quote.currency),
        terms_body=_terms_body(db, quote),
        bill_to_name=quote.customer_name, bill_to_email=quote.customer_email or "",
        bill_to_address=quote.customer_address or "",
    )


def _share_base(quote: Quote, request: Request) -> str:
    base = settings.app_public_url.rstrip("/") if settings.app_public_url else str(request.base_url).rstrip("/")
    return f"{base}/api/quotes/share/{quote.share_token}"


def _share_link_detail(quote: Quote, request: Request) -> str:
    return f"{_share_base(quote, request)}/pdf"


def _share_link_summary(quote: Quote, request: Request) -> str:
    return f"{_share_base(quote, request)}/summary"


def _quote_message(quote: Quote, request: Request) -> str:
    return (
        f"Dear {quote.customer_name},\n\n"
        f"Please find your quotation {quote.quote_no} "
        f"({quote.created_at.strftime('%d %b %Y')}).\n\n"
        f"Final Payable: {quote.currency} {quote.final_payable:,.2f}\n\n"
        f"Summary quotation: {_share_link_summary(quote, request)}\n"
        f"Detailed quotation (with product images): {_share_link_detail(quote, request)}\n\n"
        f"For queries or to proceed, reply to this message.\n\n"
        f"Regards,\nEvavo Wellness & Solutions LLP"
    )


def _wa_digits(phone: str) -> str:
    """Best-effort E.164-ish digits for a wa.me link. Defaults bare 10-digit
    numbers to India (+91) since that's this app's only market today."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return "91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "91" + digits[1:]
    return digits


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


def _get_settings(db: Session) -> AppSettings:
    s = db.execute(select(AppSettings)).scalars().first()
    return s or AppSettings()  # transient defaults if never seeded


def _build_lines(db: Session, body: QuoteCreate, default_gst_pct: float) -> list[QuoteLine]:
    lines: list[QuoteLine] = []
    for li in body.lines:
        product = db.get(Product, li.product_id) if li.product_id else None
        if product is not None:
            client_unit, final_c2e = product_engine_price(product)
            name = li.name or product.name
            model_no = li.model_no or product.model_no
            hsn_code = product.hsn_code
            gst_pct = product.gst_pct if product.gst_pct is not None else default_gst_pct
        else:
            if li.unit_price is None or not li.name:
                raise HTTPException(422, "Free-form line needs name and unit_price")
            client_unit, final_c2e = li.unit_price, 0.0
            name, model_no = li.name, li.model_no
            hsn_code, gst_pct = None, default_gst_pct
        unit_price = li.unit_price if li.unit_price is not None else client_unit
        line_net = unit_price * li.qty * (1.0 - li.line_disc / 100.0)
        lines.append(QuoteLine(
            product_id=li.product_id, name=name, model_no=model_no,
            qty=li.qty, line_disc=li.line_disc,
            hsn_code=hsn_code, gst_pct=gst_pct,
            gst_amount=line_net * gst_pct / 100.0,
            unit_price=unit_price, unit_cost=final_c2e,
        ))
    return lines


def _resolve_addons(body: QuoteCreate, s: AppSettings) -> AddOns:
    """Merge the request with the AppSettings defaults into engine AddOns."""
    def pick(val, default):
        return val if val is not None else default
    local = pick(body.local_freight, body.freight or s.local_freight)
    intl = pick(body.intl_freight, s.intl_freight)
    imp = pick(body.import_charge, s.import_charge)
    return AddOns(
        install_enabled=body.install_enabled,
        install_pct=body.install_pct,
        install_amount=body.install_amount,
        packaging=body.packaging,
        local_freight=local, intl_freight=intl, import_charge=imp,
        gst_default_pct=pick(body.gst_default_pct, s.gst_default_pct),
        home_state=s.home_state or "",
        place_of_supply=body.place_of_supply or "",
    )


def _prepare_quote_write(db: Session, body: QuoteCreate, user, s: AppSettings):
    """Shared by create/update: build lines + totals, forcing approval instead of
    hard-blocking when a non-manager/admin line exceeds the configured discount cap.
    """
    over_cap = False
    if not can_see_cost(user.role):
        over_cap = any(li.line_disc > s.max_discount_pct for li in body.lines)
    addons = _resolve_addons(body, s)
    lines = _build_lines(db, body, addons.gst_default_pct)
    _, totals = compute_quote(
        [QuoteLineInput(l.unit_price, l.unit_cost, l.qty, l.line_disc, l.gst_pct)
         for l in lines],
        addons,
    )
    if over_cap:
        totals = dataclasses.replace(totals, needs_approval=True)
    return lines, totals, addons


@router.post("")
def create_quote(body: QuoteCreate, db: Session = Depends(get_session),
                 user=Depends(get_current_user)):
    s = _get_settings(db)
    lines, totals, addons = _prepare_quote_write(db, body, user, s)
    quote = Quote(
        quote_no=_next_quote_no(db), client_id=body.client_id,
        customer_name=body.customer_name, customer_email=body.customer_email,
        customer_address=body.customer_address, customer_mobile=body.customer_mobile,
        share_token=secrets.token_urlsafe(24),
        currency=body.currency, terms_template_id=body.terms_template_id,
        install_enabled=body.install_enabled, install_pct=body.install_pct,
        install_amount=body.install_amount, packaging=body.packaging,
        freight=totals.freight, local_freight=addons.local_freight,
        intl_freight=addons.intl_freight, import_charge=addons.import_charge,
        place_of_supply=body.place_of_supply, home_state=s.home_state,
        gst_default_pct=addons.gst_default_pct,
        subtotal_net=totals.subtotal_net, grand_total=totals.grand_total,
        taxable_amount=totals.taxable_amount, gst_total=totals.gst_total,
        cgst=totals.cgst, sgst=totals.sgst, igst=totals.igst,
        final_payable=totals.final_payable,
        total_cost=totals.total_cost, needs_approval=totals.needs_approval,
        lines=lines,
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return quote_out(quote, can_see_cost(user.role))


@router.put("/{quote_id}")
def update_quote(quote_id: int, body: QuoteCreate, db: Session = Depends(get_session),
                 user=Depends(get_current_user)):
    """Update an existing draft in place (same id/quote_no/share_token).

    Once a quote leaves "draft" it's locked — nobody (including admin) can edit
    it directly here; "Revise" is the only way to change it (forks a new draft).
    """
    quote = db.get(Quote, quote_id)
    if not quote:
        raise HTTPException(404, "Quote not found")
    if quote.status != "draft":
        raise HTTPException(
            403, f"Quote is locked (status: {quote.status}). "
                 "Use Revise to create an editable copy.")
    s = _get_settings(db)
    lines, totals, addons = _prepare_quote_write(db, body, user, s)
    quote.client_id = body.client_id
    quote.customer_name = body.customer_name
    quote.customer_email = body.customer_email
    quote.customer_address = body.customer_address
    quote.customer_mobile = body.customer_mobile
    quote.currency = body.currency
    quote.terms_template_id = body.terms_template_id
    quote.install_enabled = body.install_enabled
    quote.install_pct = body.install_pct
    quote.install_amount = body.install_amount
    quote.packaging = body.packaging
    quote.freight = totals.freight
    quote.local_freight = addons.local_freight
    quote.intl_freight = addons.intl_freight
    quote.import_charge = addons.import_charge
    quote.place_of_supply = body.place_of_supply
    quote.home_state = s.home_state
    quote.gst_default_pct = addons.gst_default_pct
    quote.subtotal_net = totals.subtotal_net
    quote.grand_total = totals.grand_total
    quote.taxable_amount = totals.taxable_amount
    quote.gst_total = totals.gst_total
    quote.cgst = totals.cgst
    quote.sgst = totals.sgst
    quote.igst = totals.igst
    quote.final_payable = totals.final_payable
    quote.total_cost = totals.total_cost
    quote.needs_approval = totals.needs_approval
    quote.approved = False  # edited content invalidates any prior approval
    quote.lines.clear()
    quote.lines.extend(lines)
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
        "approved": q.approved,
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
    if (q.needs_approval and not q.approved and body.status == "sent"
            and not can_see_cost(user.role)):
        raise HTTPException(403, "Quote needs manager approval before it can be sent")
    q.status = body.status
    db.commit()
    return {"id": q.id, "status": q.status}


@router.patch("/{quote_id}/approve")
def approve_quote(quote_id: int, db: Session = Depends(get_session),
                  user=Depends(require_role("manager", "admin"))):
    """Manager/admin sign-off on a quote that exceeded the discount policy —
    unblocks email/WhatsApp sending for whoever created it, without changing
    the quote's id/quote_no."""
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    if not q.needs_approval:
        raise HTTPException(422, "Quote does not require approval")
    q.approved = True
    q.approved_by = user.email
    q.approved_at = datetime.utcnow()
    db.commit()
    return {"id": q.id, "approved": q.approved, "approved_by": q.approved_by,
            "approved_at": q.approved_at.isoformat()}


@router.get("/{quote_id}/pdf")
def quote_pdf(quote_id: int, db: Session = Depends(get_session),
              user=Depends(get_current_user)):
    """Branded, client-safe Detailed PDF, with product photos (no cost —
    built from the preview payload)."""
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    pdf = _render_pdf(db, q)
    fname = q.quote_no.replace("/", "_") + ".pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.get("/{quote_id}/pdf/summary")
def quote_pdf_summary(quote_id: int, db: Session = Depends(get_session),
                      user=Depends(get_current_user)):
    """Branded, client-safe Summary PDF — condensed line items, no photos."""
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    pdf = _render_summary_pdf(db, q)
    fname = q.quote_no.replace("/", "_") + "_summary.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.post("/{quote_id}/email")
def quote_email(quote_id: int, request: Request, db: Session = Depends(get_session),
                user=Depends(get_current_user)):
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    if q.needs_approval and not q.approved and not can_see_cost(user.role):
        raise HTTPException(403, "Quote needs manager approval before it can be emailed")
    if not q.customer_email:
        raise HTTPException(422, "Quote has no client email address")
    pdf = _render_pdf(db, q)
    setup = db.execute(select(EmailSetup)).scalars().first()
    try:
        result = send_quote_email(
            setup, to_email=q.customer_email,
            subject=f"Quotation {q.quote_no} - Evavo Wellness & Solutions LLP",
            body=_quote_message(q, request),
            pdf_bytes=pdf, pdf_name=q.quote_no.replace("/", "_") + ".pdf")
    except Exception as exc:
        raise HTTPException(502, f"Failed to send email: {exc}")
    if result.get("sent") and q.status == "draft":
        q.status = "sent"
        db.commit()
    return result


@router.post("/{quote_id}/whatsapp")
def quote_whatsapp(quote_id: int, request: Request, db: Session = Depends(get_session),
                   user=Depends(get_current_user)):
    """Build a free wa.me click-to-chat link — no paid API, opened client-side."""
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found")
    if q.needs_approval and not q.approved and not can_see_cost(user.role):
        raise HTTPException(403, "Quote needs manager approval before it can be sent")
    if not q.customer_mobile:
        raise HTTPException(
            422, "Add a WhatsApp/mobile number for this customer (Customer Master "
                 "or this quote's WhatsApp field) before sending.")
    digits = _wa_digits(q.customer_mobile)
    if not digits:
        raise HTTPException(422, "The WhatsApp number on this quote looks invalid.")
    text = _quote_message(q, request)
    url = f"https://wa.me/{digits}?text={urlquote(text)}"
    logger.info("WhatsApp link built: quote_no=%s phone=%s", q.quote_no, digits)
    return {"url": url, "phone": digits}


@router.get("/share/{token}/pdf")
def quote_share_pdf(token: str, db: Session = Depends(get_session)):
    """Public, unauthenticated, client-safe Detailed PDF — no login required.

    Looked up by an unguessable share token, not the quote id. Always built
    from the client-preview payload, so cost/margin can never appear here.
    """
    q = db.execute(select(Quote).where(Quote.share_token == token)).scalars().first()
    if not q:
        raise HTTPException(404, "Quote not found")
    pdf = _render_pdf(db, q)
    fname = q.quote_no.replace("/", "_") + ".pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.get("/share/{token}/summary")
def quote_share_summary(token: str, db: Session = Depends(get_session)):
    """Public, unauthenticated, client-safe Summary PDF — no login required.

    Same share token as the Detailed PDF (one link per quote, two views).
    """
    q = db.execute(select(Quote).where(Quote.share_token == token)).scalars().first()
    if not q:
        raise HTTPException(404, "Quote not found")
    pdf = _render_summary_pdf(db, q)
    fname = q.quote_no.replace("/", "_") + "_summary.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


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
        customer_address=src.customer_address, customer_mobile=src.customer_mobile,
        share_token=secrets.token_urlsafe(24),
        currency=src.currency, terms_template_id=src.terms_template_id,
        install_enabled=src.install_enabled, install_pct=src.install_pct,
        install_amount=src.install_amount, packaging=src.packaging, freight=src.freight,
        local_freight=src.local_freight, intl_freight=src.intl_freight,
        import_charge=src.import_charge, place_of_supply=src.place_of_supply,
        home_state=src.home_state, gst_default_pct=src.gst_default_pct,
        subtotal_net=src.subtotal_net, grand_total=src.grand_total,
        taxable_amount=src.taxable_amount, gst_total=src.gst_total,
        cgst=src.cgst, sgst=src.sgst, igst=src.igst, final_payable=src.final_payable,
        total_cost=src.total_cost, needs_approval=src.needs_approval,
        revision_of=src.id, status="draft", approved=False,
        lines=[QuoteLine(product_id=l.product_id, name=l.name, model_no=l.model_no,
                         qty=l.qty, line_disc=l.line_disc, hsn_code=l.hsn_code,
                         gst_pct=l.gst_pct, gst_amount=l.gst_amount,
                         unit_price=l.unit_price, unit_cost=l.unit_cost) for l in src.lines],
    )
    db.add(rev)
    db.commit()
    db.refresh(rev)
    return quote_out(rev, can_see_cost(user.role))
