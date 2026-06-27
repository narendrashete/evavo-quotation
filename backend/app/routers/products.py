"""Products router — cost fields are gated by the caller's role."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.core.security import get_current_user, can_see_cost
from app.core.serialize import product_out
from app.models import Product

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("")
def list_products(q: Optional[str] = None, category: Optional[str] = None,
                  db: Session = Depends(get_session), user=Depends(get_current_user)):
    stmt = select(Product)
    if category:
        stmt = stmt.where(Product.category == category)
    rows = db.execute(stmt).scalars().all()
    if q:
        ql = q.lower()
        rows = [p for p in rows
                if ql in p.name.lower() or ql in (p.model_no or "").lower()]
    include = can_see_cost(user.role)
    return [product_out(p, include) for p in rows]


@router.get("/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_session),
                user=Depends(get_current_user)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return product_out(p, can_see_cost(user.role))
