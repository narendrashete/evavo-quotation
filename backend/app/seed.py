"""Seed default users, FX rates and terms templates (idempotent)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import User, FxRate, TermsTemplate, Lead

DEFAULT_USERS = [
    ("Alan Sales", "sales@evavo.test", "sales123", "sales"),
    ("Maya Manager", "manager@evavo.test", "manager123", "manager"),
    ("Admin", "admin@evavo.test", "admin123", "admin"),
]

DEFAULT_FX = [  # display rates (INR per 1 unit), from the prototype
    ("INR", 1.0, "display"),
    ("USD", 83.5, "display"),
    ("EUR", 90.0, "display"),
    ("USD", 100.0, "procurement"),
    ("EUR", 115.0, "procurement"),
]


def seed(db: Session) -> None:
    for name, email, pw, role in DEFAULT_USERS:
        if not db.execute(select(User).where(User.email == email)).scalar_one_or_none():
            db.add(User(name=name, email=email, password_hash=hash_password(pw), role=role))

    if not db.execute(select(FxRate)).first():
        for cur, rate, kind in DEFAULT_FX:
            db.add(FxRate(currency=cur, rate_to_inr=rate, kind=kind))

    if not db.execute(select(Lead)).first():
        for name, owner, stage, amount in [
            ("Aqua Bliss Spa", "Parth", 0, 1240000),
            ("Zen Retreat Resort", "Riya", 0, 860000),
            ("TIPAI Wellness", "Parth", 1, 894200),
            ("Lotus Salon Co.", "Alan", 1, 238800),
            ("Ghareni Spa & Salon", "Alan", 2, 1527466),
            ("Urban Glow Salon", "Riya", 2, 540000),
            ("Serenity Day Spa", "Alan", 3, 410000),
        ]:
            db.add(Lead(name=name, owner=owner, stage=stage, amount=amount))

    if not db.execute(select(TermsTemplate)).first():
        db.add(TermsTemplate(
            name="Currency / International", kind="currency",
            body=("1. Quotation valid for two weeks from date of issue.\n"
                  "2. Prices quoted are Ex-Works; freight & import charges extra at actuals.\n"
                  "3. Payment terms: 100% advance; order confirmed on receipt.\n"
                  "4. Installation charges 10.5% of equipment value.\n"
                  "5. Civil, plumbing, piping & electrical works are in the client's scope.\n"
                  "6. Lead time: 8-12 weeks for production & delivery.")))
        db.add(TermsTemplate(
            name="Regular (Domestic)", kind="regular",
            body=("1. Quotation valid for two weeks.\n"
                  "2. Prices are Ex-Works; freight extra at actuals.\n"
                  "3. Payment: 100% advance.\n"
                  "4. Installation 10.5% of equipment value.\n"
                  "5. Lead time: 8-12 weeks.")))
    db.commit()
