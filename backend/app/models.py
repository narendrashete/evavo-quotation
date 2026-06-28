"""ORM models for the Evavo Quotation Platform.

Cost/margin columns (`source_price_inr`, `loading_factor`, `final_c2e`, ...) are
CONFIDENTIAL. Role gating happens at the API serialization layer (Phase 2): sales
responses omit them entirely; the client PDF can never include them.

Quote lines SNAPSHOT the computed unit price and unit cost at the time the line is
added, so historical quotes don't move when FX rates or markups change later, and
so revisions are reproducible.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    String, Integer, Float, Boolean, Date, DateTime, ForeignKey, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="sales")  # sales|manager|admin
    branch: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class FxRate(Base):
    """Dated, editable FX table — replaces the hand-typed S/T columns."""
    __tablename__ = "fx_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)   # USD, EUR, INR
    rate_to_inr: Mapped[float] = mapped_column(Float)             # INR per 1 unit
    kind: Mapped[str] = mapped_column(String(12), default="display")  # display|procurement
    effective_date: Mapped[date] = mapped_column(Date, default=date.today)


class Category(Base):
    """Product family with default pricing-rule constants."""
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    supplier_disc: Mapped[float] = mapped_column(Float, default=0.0)
    loading_factor: Mapped[float] = mapped_column(Float, default=1.5)
    client_markup: Mapped[float] = mapped_column(Float, default=2.0)
    list_uplift: Mapped[float] = mapped_column(Float, default=0.10)
    markup_base: Mapped[str] = mapped_column(String(12), default="final_c2e")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    model_no: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # CONFIDENTIAL pricing parameters (drive the engine)
    source_currency: Mapped[str] = mapped_column(String(3), default="INR")
    source_price_inr: Mapped[float] = mapped_column(Float, default=0.0)  # c2e_inr basis
    loading_factor: Mapped[float] = mapped_column(Float, default=1.5)
    client_markup: Mapped[float] = mapped_column(Float, default=2.0)
    list_uplift: Mapped[float] = mapped_column(Float, default=0.10)
    markup_base: Mapped[str] = mapped_column(String(12), default="final_c2e")

    # Migrated snapshot from Excel (kept verbatim for override rows)
    migrated_final_c2e: Mapped[float | None] = mapped_column(Float, nullable=True)
    migrated_client_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_manual_override: Mapped[bool] = mapped_column(Boolean, default=False)

    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_sheet: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_row: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# --- Legacy masters (from the old app screenshots) ---------------------------

class City(Base):
    __tablename__ = "cities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stage: Mapped[int] = mapped_column(Integer, default=0)  # 0 Leads..3 Won
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    # Auto-derived from project.client_id on create/update — not set directly.
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    # Site/installation address — may differ from the Client's registered address.
    address: Mapped[str | None] = mapped_column(Text, nullable=True)


class TermsTemplate(Base):
    __tablename__ = "terms_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="regular")  # currency|regular
    body: Mapped[str] = mapped_column(Text)


class EmailSetup(Base):
    __tablename__ = "email_setup"
    id: Mapped[int] = mapped_column(primary_key=True)
    smtp_host: Mapped[str] = mapped_column(String(200))
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    username: Mapped[str] = mapped_column(String(200))
    password: Mapped[str] = mapped_column(String(255))
    from_email: Mapped[str] = mapped_column(String(200))
    use_tls: Mapped[bool] = mapped_column(Boolean, default=True)


# --- Quotes ------------------------------------------------------------------

class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    quote_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|sent|negotiation|won
    terms_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("terms_templates.id"), nullable=True)

    install_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    install_pct: Mapped[float] = mapped_column(Float, default=0.105)
    packaging: Mapped[float] = mapped_column(Float, default=0.0)
    freight: Mapped[float] = mapped_column(Float, default=0.0)

    # Snapshotted totals (INR)
    subtotal_net: Mapped[float] = mapped_column(Float, default=0.0)
    grand_total: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)       # CONFIDENTIAL
    needs_approval: Mapped[bool] = mapped_column(Boolean, default=False)

    revision_of: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lines: Mapped[list["QuoteLine"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan")


class QuoteLine(Base):
    __tablename__ = "quote_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    model_no: Mapped[str | None] = mapped_column(String(120), nullable=True)
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    line_disc: Mapped[float] = mapped_column(Float, default=0.0)  # percent

    # SNAPSHOT at add-time (INR)
    unit_price: Mapped[float] = mapped_column(Float)                 # client selling
    unit_cost: Mapped[float] = mapped_column(Float)                  # CONFIDENTIAL (final_c2e)

    quote: Mapped["Quote"] = relationship(back_populates="lines")
