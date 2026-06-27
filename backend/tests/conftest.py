"""Test fixtures: an in-memory SQLite DB wired into the app via dependency override.

Lets the full API (auth, role gating, quotes) be tested without a SQL Server.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db import Base, get_session
from app.main import app
from app import models  # noqa: F401 register mappers
from app.seed import seed
from app.core.serialize import product_engine_price  # noqa: F401


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = TestingSession()
    seed(db)
    # a couple of products to quote against
    _seed_products(db)
    try:
        yield db
    finally:
        db.close()


def _seed_products(db):
    from app.models import Product
    db.add(Product(name="Pedicure Chair (Luxury)", model_no="EV-PC-200",
                   category="Salon Equipment", source_price_inr=118800.0,
                   loading_factor=1.5, client_markup=2.0, list_uplift=0.10,
                   markup_base="final_c2e"))
    db.add(Product(name="Facial Bed", model_no="EV-FB-500", category="Massage Beds",
                   source_price_inr=66300.0, loading_factor=1.5, client_markup=2.0,
                   list_uplift=0.10, markup_base="final_c2e"))
    db.commit()


@pytest.fixture()
def client(db_session):
    def _override_session():
        yield db_session
    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _token(client, email, pw):
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture()
def sales_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'sales@evavo.test', 'sales123')}"}


@pytest.fixture()
def manager_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'manager@evavo.test', 'manager123')}"}
