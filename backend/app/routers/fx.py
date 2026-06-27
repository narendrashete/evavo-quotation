"""FX rates router — the dated, editable rate table (manager/admin to edit)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.core.security import get_current_user, require_role
from app.models import FxRate
from app.schemas import FxRateIn, FxRateOut

router = APIRouter(prefix="/api/fx", tags=["fx"])


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
