"""User management — admin-only CRUD (create/list/edit/delete login accounts).

Mirrors the Masters router's inline-form style. Every endpoint requires
role=admin; sales/manager get a 403 even if they guess the URL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.core.security import require_role, hash_password
from app.models import User
from app.schemas import UserIn

router = APIRouter(prefix="/api/users", tags=["users"])


def _out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role,
            "branch": u.branch, "is_active": u.is_active}


@router.get("")
def list_users(db: Session = Depends(get_session), user=Depends(require_role("admin"))):
    rows = db.execute(select(User).order_by(User.name)).scalars().all()
    return [_out(u) for u in rows]


@router.post("")
def create_user(body: UserIn, db: Session = Depends(get_session),
                user=Depends(require_role("admin"))):
    if not body.password:
        raise HTTPException(422, "Password is required for a new user")
    if db.execute(select(User).where(User.email == body.email)).scalar_one_or_none():
        raise HTTPException(409, "A user with this email already exists")
    u = User(name=body.name, email=body.email, password_hash=hash_password(body.password),
              role=body.role, branch=body.branch, is_active=body.is_active)
    db.add(u)
    db.commit()
    db.refresh(u)
    return _out(u)


@router.put("/{user_id}")
def update_user(user_id: int, body: UserIn, db: Session = Depends(get_session),
                user=Depends(require_role("admin"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    existing = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if existing and existing.id != user_id:
        raise HTTPException(409, "A user with this email already exists")
    u.name, u.email, u.role, u.branch, u.is_active = (
        body.name, body.email, body.role, body.branch, body.is_active)
    if body.password:
        u.password_hash = hash_password(body.password)
    db.commit()
    return _out(u)


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_session),
                user=Depends(require_role("admin"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == user.id:
        raise HTTPException(400, "You cannot delete your own account")
    db.delete(u)
    db.commit()
    return {"deleted": user_id}
