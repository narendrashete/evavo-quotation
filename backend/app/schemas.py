"""Pydantic request/response models.

Response bodies for products/quotes are built by the serializers in
`app/core/serialize.py` (role-gated), so these output schemas use plain dicts for
the variable cost fields rather than fixed models.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Auth ---
class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    branch: Optional[str] = None


class UserIn(BaseModel):
    name: str
    email: str
    password: Optional[str] = Field(None, min_length=6)  # required on create; blank = unchanged on edit
    role: str = "sales"  # sales|manager|admin
    branch: Optional[str] = None
    is_active: bool = True


# --- FX ---
class FxRateIn(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    rate_to_inr: float = Field(gt=0)
    kind: str = "display"


class FxRateOut(FxRateIn):
    id: int
    effective_date: str


# --- Quotes ---
class QuoteLineIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    product_id: Optional[int] = None
    name: Optional[str] = None
    model_no: Optional[str] = None
    qty: float = Field(gt=0, default=1.0)
    line_disc: float = Field(ge=0, le=100, default=0.0)
    # Optional override of unit price (else taken from the product engine price).
    unit_price: Optional[float] = None


class QuoteCreate(BaseModel):
    customer_name: str
    customer_email: Optional[str] = None
    customer_address: Optional[str] = None
    customer_mobile: Optional[str] = None
    client_id: Optional[int] = None
    currency: str = "INR"
    terms_template_id: Optional[int] = None
    install_enabled: bool = True
    install_pct: float = 0.105
    packaging: float = 0.0
    freight: float = 0.0
    lines: list[QuoteLineIn] = []


class QuoteStatusUpdate(BaseModel):
    status: str  # draft|sent|negotiation|won


# --- Masters (generic-ish) ---
class ClientIn(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    gstin: Optional[str] = None


class ProjectIn(BaseModel):
    name: str
    client_id: int
    city: Optional[str] = None


class LeadIn(BaseModel):
    name: str
    owner: Optional[str] = None
    stage: int = 0
    amount: float = 0.0
    project_id: int
    address: Optional[str] = None
    whatsapp_number: Optional[str] = None


class TermsIn(BaseModel):
    name: str
    kind: str = "regular"  # currency|regular
    body: str


class EmailSetupIn(BaseModel):
    smtp_host: str
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_email: str
    use_tls: bool = True


class ProductUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: Optional[str] = None
    model_no: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    source_price_inr: Optional[float] = None
    loading_factor: Optional[float] = None
    client_markup: Optional[float] = None
    list_uplift: Optional[float] = None
    markup_base: Optional[str] = None
