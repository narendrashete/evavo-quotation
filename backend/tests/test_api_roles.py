"""API tests: role-based cost gating + the quote flow + approval guardrail."""

from app.core.pricing import CONFIDENTIAL_FIELDS


def _has_confidential(obj) -> bool:
    """Recursively check a JSON structure for any confidential key."""
    if isinstance(obj, dict):
        if set(obj) & CONFIDENTIAL_FIELDS:
            return True
        return any(_has_confidential(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_confidential(v) for v in obj)
    return False


def test_login_returns_role(client):
    r = client.post("/api/auth/login",
                    data={"username": "sales@evavo.test", "password": "sales123"})
    assert r.status_code == 200
    assert r.json()["role"] == "sales"


def test_products_hide_cost_for_sales(client, sales_headers):
    r = client.get("/api/products", headers=sales_headers)
    assert r.status_code == 200
    data = r.json()
    assert data and not _has_confidential(data), "sales must not see cost/margin"
    assert "client_unit_price" in data[0]


def test_products_show_cost_for_manager(client, manager_headers):
    r = client.get("/api/products", headers=manager_headers)
    assert r.status_code == 200
    assert any("final_c2e" in p for p in r.json()), "manager should see cost"


def test_products_require_auth(client):
    assert client.get("/api/products").status_code == 401


def _new_quote_payload(line_disc=9.0):
    return {
        "customer_name": "Ghareni Spa & Salon",
        "currency": "INR",
        "lines": [
            {"product_id": 1, "qty": 2, "line_disc": line_disc},
            {"product_id": 2, "qty": 1, "line_disc": line_disc},
        ],
    }


def test_create_quote_computes_totals(client, manager_headers):
    r = client.post("/api/quotes", json=_new_quote_payload(), headers=manager_headers)
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["quote_no"].startswith("EVAVO/QTN/")
    # Pedicure 118800*1.5*2 = 356400 (qty 2 -> 712800); Facial 66300*1.5*2 = 198900
    # subtotal_net = (712800 + 198900) * (1-0.09) = 911700 * 0.91 = 829647
    assert abs(q["totals"]["subtotal_net"] - 829647.0) < 1.0
    assert "total_cost" in q["totals"]  # manager sees cost


def test_quote_preview_never_has_cost(client, manager_headers):
    created = client.post("/api/quotes", json=_new_quote_payload(),
                          headers=manager_headers).json()
    r = client.get(f"/api/quotes/{created['id']}/preview", headers=manager_headers)
    assert r.status_code == 200
    assert not _has_confidential(r.json()), "client preview must never expose cost"


def test_sales_quote_view_hides_cost(client, sales_headers):
    created = client.post("/api/quotes", json=_new_quote_payload(),
                          headers=sales_headers).json()
    r = client.get(f"/api/quotes/{created['id']}", headers=sales_headers)
    assert not _has_confidential(r.json())


def test_high_discount_triggers_approval_and_blocks_send(client, sales_headers):
    created = client.post("/api/quotes", json=_new_quote_payload(line_disc=20.0),
                          headers=sales_headers).json()
    assert created["totals"]["needs_approval"] is True
    # sales cannot push it to "sent" while approval is pending
    r = client.patch(f"/api/quotes/{created['id']}/status",
                     json={"status": "sent"}, headers=sales_headers)
    assert r.status_code == 403


def test_manager_can_send_flagged_quote(client, manager_headers):
    created = client.post("/api/quotes", json=_new_quote_payload(line_disc=20.0),
                          headers=manager_headers).json()
    r = client.patch(f"/api/quotes/{created['id']}/status",
                     json={"status": "sent"}, headers=manager_headers)
    assert r.status_code == 200 and r.json()["status"] == "sent"


def test_sales_cannot_edit_fx(client, sales_headers):
    r = client.post("/api/fx", json={"currency": "USD", "rate_to_inr": 84.0},
                    headers=sales_headers)
    assert r.status_code == 403


def test_quote_pdf_is_generated(client, manager_headers):
    created = client.post("/api/quotes", json=_new_quote_payload(),
                          headers=manager_headers).json()
    r = client.get(f"/api/quotes/{created['id']}/pdf", headers=manager_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_quote_email_dry_run_without_setup(client, manager_headers):
    payload = _new_quote_payload()
    payload["customer_email"] = "client@example.com"
    created = client.post("/api/quotes", json=payload, headers=manager_headers).json()
    r = client.post(f"/api/quotes/{created['id']}/email", headers=manager_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True and body["sent"] is False


def test_revise_creates_linked_revision(client, manager_headers):
    created = client.post("/api/quotes", json=_new_quote_payload(),
                          headers=manager_headers).json()
    r = client.post(f"/api/quotes/{created['id']}/revise", headers=manager_headers)
    assert r.status_code == 200
    rev = r.json()
    assert rev["id"] != created["id"]
    assert rev["status"] == "draft"
    assert len(rev["lines"]) == len(created["lines"])


def test_manager_can_edit_product_pricing(client, manager_headers):
    r = client.put("/api/masters/products/1", json={"client_markup": 2.5},
                   headers=manager_headers)
    assert r.status_code == 200
    # Pedicure source 118800 * 1.5 * 2.5 = 445500
    assert abs(r.json()["client_unit_price"] - 445500.0) < 1.0


def test_sales_cannot_edit_product_pricing(client, sales_headers):
    r = client.put("/api/masters/products/1", json={"client_markup": 2.5},
                   headers=sales_headers)
    assert r.status_code == 403
