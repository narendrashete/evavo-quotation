"""FX rates router — the dated, editable rate table (manager/admin to edit)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.core.security import get_current_user, require_role
from app.models import FxRate
from app.schemas import FxRateIn, FxRateOut

router = APIRouter(prefix="/api/fx", tags=["fx"])

FRANKFURTER_URL = "https://api.frankfurter.app/latest"


def _out(r: FxRate) -> FxRateOut:
    return FxRateOut(id=r.id, currency=r.currency, rate_to_inr=r.rate_to_inr,
                     kind=r.kind, effective_date=str(r.effective_date))


@router.get("", response_model=list[FxRateOut])
def list_fx(db: Session = Depends(get_session), user=Depends(get_current_user)):
    rows = db.execute(select(FxRate).order_by(FxRate.effective_date.desc())).scalars().all()
    return [_out(r) for r in rows]


@router.post("", response_model=FxRateOut)
def add_fx(body: FxRateIn, db: Session = Depends(get_session),
           user=Depends(require_role("manager", "admin"))):
    r = FxRate(currency=body.currency.upper(), rate_to_inr=body.rate_to_inr, kind=body.kind)
    db.add(r)
    db.commit()
    db.refresh(r)
    return _out(r)


def _fetch_live_rate(client: httpx.Client, currency: str) -> float:
    try:
        resp = client.get(FRANKFURTER_URL, params={"from": currency, "to": "INR"})
        resp.raise_for_status()
        rate = float(resp.json()["rates"]["INR"])
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(502, f"Could not fetch live FX rate for {currency}: {e}") from e
    if not (1 <= rate <= 1000):
        raise HTTPException(502, f"Live FX rate for {currency} looks implausible: {rate}")
    return rate


@router.post("/refresh", response_model=list[FxRateOut])
def refresh_fx(db: Session = Depends(get_session),
               user=Depends(require_role("manager", "admin"))):
    """Pull current USD/EUR -> INR display rates from a free, no-key API
    (Frankfurter.app, ECB reference rates) and store them as new dated rows.

    Only "display" rates are touched here — "procurement" rates feed the
    pricing engine's cost/margin calculations and stay a manual business
    decision (see CLAUDE.md). All-or-nothing: if either currency fetch fails,
    nothing is written.
    """
    with httpx.Client(timeout=8.0) as client:
        rates = {ccy: _fetch_live_rate(client, ccy) for ccy in ("USD", "EUR")}

    rows = [FxRate(currency=ccy, rate_to_inr=rate, kind="display") for ccy, rate in rates.items()]
    db.add_all(rows)
    db.commit()
    for r in rows:
        db.refresh(r)
    return [_out(r) for r in rows]
