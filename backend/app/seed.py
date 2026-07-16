"""Seed default users, FX rates and terms templates (idempotent)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import User, FxRate, TermsTemplate, Client, Project, Lead, AppSettings

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
        # Bodies use the "# Heading" convention: each `# X` line becomes a bold
        # section headline on the Proposal PDF's Terms page, the lines under it
        # its body. See app/services/pdf.py:_parse_terms_sections.
        db.add(TermsTemplate(
            name="Currency / International", kind="currency",
            body=("# Price\n"
                  "Price quoted is Ex-Works. Excludes all taxes and local levies (GST 18%).\n"
                  "# Validity\n"
                  "Quote valid for TWO weeks from date of issue.\n"
                  "# Freight\n"
                  "International import freight, GST and local freight charges extra at actuals.\n"
                  "# Payment Terms\n"
                  "100% advance. Order once placed cannot be cancelled and advance is "
                  "non-refundable. Payment via NEFT/RTGS.\n"
                  "# Other Duties & Charges\n"
                  "1) Installation charges are 10.5% of the total price. 2) Lodging, boarding, "
                  "travel and food allowance for installation outside Mumbai to be borne by the "
                  "client. 3) Any special/fragile packaging (upholstery, ceramic/glass, wooden) "
                  "will cost extra. 4) Lead time 12-16 weeks. 5) Civil, plumbing, piping & "
                  "electrical works are in the client's scope.")))
        db.add(TermsTemplate(
            name="Regular (Domestic)", kind="regular",
            body=("# Price\n"
                  "Prices are Ex-Works. Excludes all taxes (GST 18%).\n"
                  "# Validity\n"
                  "Quote valid for TWO weeks from date of issue.\n"
                  "# Freight\n"
                  "Freight charges extra at actuals.\n"
                  "# Payment Terms\n"
                  "100% advance; order confirmed on receipt. Payment via NEFT/RTGS.\n"
                  "# Other Duties & Charges\n"
                  "1) Installation charges are 10.5% of equipment value. 2) Lead time 8-12 "
                  "weeks for production & delivery.")))

    if not db.execute(select(AppSettings)).first():
        db.add(AppSettings())  # all defaults (12% cap, 18% GST, 10.5% install, home state 27)
    db.commit()
