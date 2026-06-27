"""Auth & role gating.

Roles: sales | manager | admin. Cost/margin visibility is the key distinction —
`can_see_cost(role)` is the single switch the serializers consult so confidential
fields are withheld from sales users (and never sent to the client documents).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ROLES = ("sales", "manager", "admin")
COST_ROLES = ("manager", "admin")


def hash_password(plain: str) -> str:
    # bcrypt operates on the first 72 bytes; truncate explicitly (avoids the
    # ValueError some bcrypt builds raise on longer secrets).
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def can_see_cost(role: str) -> bool:
    return role in COST_ROLES


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


def get_current_user(token: str = Depends(oauth2_scheme),
                     db: Session = Depends(get_session)):
    from app.models import User
    payload = _decode(token)
    email: Optional[str] = payload.get("sub")
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_role(*allowed: str):
    """Dependency factory: 403 unless the current user's role is allowed."""
    def _dep(user=Depends(get_current_user)):
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Requires role in {allowed}")
        return user
    return _dep
