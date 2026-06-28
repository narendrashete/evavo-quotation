"""Seed default users, FX rates and terms templates (idempotent)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import User, FxRate, TermsTemplate, Client, Project, Lead

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

    # Demo Clients + Projects, so the Client/Project/Lead hierarchy isn't empty
    # out of the box. A couple of the demo Leads below are linked to these via
    # project_id (Lead.client_id is then auto-derived), the rest stay
    # unlinked (project_id=None) to show what that looks like in the UI.
    client_by_name: dict[str, Client] = {}
    if not db.execute(select(Client)).first():
        for name, city in [("Aqua Bliss Spa", "Goa"), ("Ghareni Spa & Salon", "Mumbai")]:
            c = Client(name=name, city=city)
            db.add(c)
            client_by_name[name] = c
        db.flush()  # assign ids before Projects reference them

    project_by_name: dict[str, Project] = {}
    if client_by_name and not db.execute(select(Project)).first():
        for name, client_name, city in [
            ("Aqua Bliss Spa - Salon Fitout", "Aqua Bliss Spa", "Goa"),
            ("Ghareni Spa & Salon - Master Quote", "Ghareni Spa & Salon", "Mumbai"),
        ]:
            p = Project(name=name, client_id=client_by_name[client_name].id, city=city)
            db.add(p)
            project_by_name[name] = p
        db.flush()

    if not db.execute(select(Lead)).first():
        linked = {
            "Aqua Bliss Spa": "Aqua Bliss Spa - Salon Fitout",
            "Ghareni Spa & Salon": "Ghareni Spa & Salon - Master Quote",
        }
        for name, owner, stage, amount in [
            ("Aqua Bliss Spa", "Parth", 0, 1240000),
            ("Zen Retreat Resort", "Riya", 0, 860000),
            ("TIPAI Wellness", "Parth", 1, 894200),
            ("Lotus Salon Co.", "Alan", 1, 238800),
            ("Ghareni Spa & Salon", "Alan", 2, 1527466),
            ("Urban Glow Salon", "Riya", 2, 540000),
            ("Serenity Day Spa", "Alan", 3, 410000),
        ]:
            project = project_by_name.get(linked.get(name))
            db.add(Lead(name=name, owner=owner, stage=stage, amount=amount,
                        project_id=project.id if project else None,
                        client_id=project.client_id if project else None))

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
