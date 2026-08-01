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
    # A line's Unit Price is the LIST price (client price * 1.10), which the line
    # discount then comes off. Pedicure 118800*1.5*2 = 356400 client -> 392040
    # list (qty 2 -> 784080); Facial 66300*1.5*2 = 198900 -> 218790 list.
    # subtotal_net = (784080 + 218790) * (1-0.09) = 1002870 * 0.91 = 912611.70
    assert abs(q["totals"]["subtotal_net"] - 912611.70) < 1.0
    assert "total_cost" in q["totals"]  # manager sees cost


def test_quote_line_exposes_unit_and_discounted_price(client, manager_headers):
    q = client.post("/api/quotes", json=_new_quote_payload(line_disc=10.0),
                    headers=manager_headers).json()
    line = q["lines"][0]
    assert abs(line["unit_price"] - 392040.0) < 1.0            # list price
    assert abs(line["discounted_unit_price"] - 352836.0) < 1.0  # less 10%


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


def test_sales_exceeds_cap_saves_pending_approval(client, sales_headers, manager_headers):
    # 20% line discount exceeds the 12% hard cap; sales can still save it, but it
    # lands in Pending Approval instead of being rejected outright.
    created = client.post("/api/quotes", json=_new_quote_payload(line_disc=20.0),
                          headers=sales_headers).json()
    assert created["status"] == "draft"
    assert created["totals"]["needs_approval"] is True

    # Sales still cannot send their own pending-approval quote.
    r = client.patch(f"/api/quotes/{created['id']}/status",
                     json={"status": "sent"}, headers=sales_headers)
    assert r.status_code == 403

    # Once a manager approves it (same quote id), sales can send it.
    approve = client.patch(f"/api/quotes/{created['id']}/approve", headers=manager_headers)
    assert approve.status_code == 200 and approve.json()["approved"] is True
    r2 = client.patch(f"/api/quotes/{created['id']}/status",
                      json={"status": "sent"}, headers=sales_headers)
    assert r2.status_code == 200 and r2.json()["status"] == "sent"


def test_manager_exceeds_cap_and_flags_approval(client, manager_headers):
    # Manager may exceed the cap; the quote still flags for approval.
    created = client.post("/api/quotes", json=_new_quote_payload(line_disc=20.0),
                          headers=manager_headers).json()
    assert created["totals"]["needs_approval"] is True


def test_sales_cannot_send_pending_approval_quote(client, manager_headers, sales_headers):
    # A manager-created high-discount quote needs approval; sales cannot send it.
    created = client.post("/api/quotes", json=_new_quote_payload(line_disc=20.0),
                          headers=manager_headers).json()
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
    # Numbered off the original, and pointing back at it.
    assert rev["quote_no"] == created["quote_no"] + "-R1"
    assert rev["revision_no"] == 1
    assert rev["revision_of"] == created["id"]
    assert rev["root_quote_id"] == created["id"]
    assert rev["root_quote_no"] == created["quote_no"]


def test_revisions_chain_off_the_original_not_the_parent(client, manager_headers):
    original = client.post("/api/quotes", json=_new_quote_payload(),
                           headers=manager_headers).json()
    r1 = client.post(f"/api/quotes/{original['id']}/revise", headers=manager_headers).json()
    # Revising R1 gives R2 (numbered off the original), not "...-R1-R1".
    r2 = client.post(f"/api/quotes/{r1['id']}/revise", headers=manager_headers).json()
    assert r2["quote_no"] == original["quote_no"] + "-R2"
    assert r2["revision_no"] == 2
    assert r2["revision_of"] == r1["id"]        # forked from R1
    assert r2["root_quote_id"] == original["id"]  # but rooted at the original

    # A brand-new quote still gets the next *original* number — revisions don't
    # consume sequence numbers.
    nxt = client.post("/api/quotes", json=_new_quote_payload(),
                      headers=manager_headers).json()
    assert nxt["quote_no"].endswith("0002") and nxt["revision_no"] == 0

    hist = client.get(f"/api/quotes/{r1['id']}/history", headers=manager_headers).json()
    assert [q["quote_no"] for q in hist["quotes"]] == [
        original["quote_no"], r1["quote_no"], r2["quote_no"]]
    assert [q["label"] for q in hist["quotes"]] == ["Original", "Revision 1", "Revision 2"]
    assert hist["current_quote_id"] == r1["id"]
    assert hist["quotes"][0]["is_original"] is True


def test_overall_discount_reduces_final_payable(client, manager_headers):
    payload = _new_quote_payload(line_disc=0.0)
    payload["install_enabled"] = False
    payload["gst_default_pct"] = 0.0
    base = client.post("/api/quotes", json=payload, headers=manager_headers).json()
    subtotal = base["totals"]["subtotal_net"]

    payload["overall_disc_pct"] = 5.0
    disc = client.post("/api/quotes", json=payload, headers=manager_headers).json()
    t = disc["totals"]
    assert abs(t["overall_discount"] - subtotal * 0.05) < 1.0
    assert abs(t["goods_net"] - subtotal * 0.95) < 1.0
    assert abs(t["final_payable"] - subtotal * 0.95) < 1.0

    # A flat amount wins over the percentage.
    payload["overall_disc_amount"] = 10000.0
    flat = client.post("/api/quotes", json=payload, headers=manager_headers).json()
    assert abs(flat["totals"]["overall_discount"] - 10000.0) < 0.01


def test_installation_uses_per_area_rates(client, manager_headers):
    # Categorise product 1 as Wet Area and leave product 2 uncategorised, then
    # quote both with distinct dry/wet/other rates.
    client.put("/api/masters/products/1", json={"area_category": "Wet Area"},
               headers=manager_headers)
    payload = _new_quote_payload(line_disc=0.0)
    payload.update({"install_enabled": True, "gst_default_pct": 0.0,
                    "install_pct": 0.10, "install_dry_pct": 0.05,
                    "install_wet_pct": 0.20})
    q = client.post("/api/quotes", json=payload, headers=manager_headers).json()
    t = q["totals"]
    # Wet line (product 1, qty 2 @ 392040) at 20%; the other line at 10%.
    assert abs(t["install_wet"] - 784080 * 0.20) < 1.0
    assert abs(t["install_other"] - 218790 * 0.10) < 1.0
    assert t["install_dry"] == 0.0
    assert abs(t["installation"] - (t["install_wet"] + t["install_other"])) < 0.01


def test_saved_totals_match_the_recomputed_ones(client, manager_headers):
    """The totals snapshotted on the Quote row must equal what read paths compute.

    `create_quote` stores `final_payable` (used by the quote list, the revision
    history and the WhatsApp/email message) while every read recomputes from the
    line snapshots — if the two calls disagree on their inputs, the stored figure
    silently drifts from the one the customer is shown.
    """
    client.put("/api/masters/products/1", json={"area_category": "Wet Area"},
               headers=manager_headers)
    client.put("/api/masters/products/2", json={"area_category": "Dry Area"},
               headers=manager_headers)
    payload = _new_quote_payload()
    payload.update({"install_pct": 0.105, "install_dry_pct": 0.06,
                    "install_wet_pct": 0.14, "overall_disc_pct": 5.0,
                    "place_of_supply": "27"})
    created = client.post("/api/quotes", json=payload, headers=manager_headers).json()

    listed = client.get("/api/quotes", headers=manager_headers).json()
    row = next(q for q in listed if q["id"] == created["id"])
    assert abs(row["grand_total"] - created["totals"]["grand_total"]) < 0.01

    hist = client.get(f"/api/quotes/{created['id']}/history",
                      headers=manager_headers).json()
    assert abs(hist["quotes"][0]["final_payable"]
               - created["totals"]["final_payable"]) < 0.01


def test_product_specification_is_editable_and_reaches_the_quote(client, manager_headers):
    spec = "Electric height adjustment 620-880 mm, three-section top."
    r = client.put("/api/masters/products/2", json={"description": spec},
                   headers=manager_headers)
    assert r.status_code == 200 and r.json()["description"] == spec
    created = client.post("/api/quotes", json=_new_quote_payload(),
                          headers=manager_headers).json()
    preview = client.get(f"/api/quotes/{created['id']}/preview",
                         headers=manager_headers).json()
    specs = [l["specification"] for l in preview["lines"]]
    assert spec in specs


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


# --- Delete permissions (manager/admin always; admin can grant to a user) ----

def test_manager_can_delete_quote(client, manager_headers):
    created = client.post("/api/quotes", json=_new_quote_payload(),
                          headers=manager_headers).json()
    r = client.delete(f"/api/quotes/{created['id']}", headers=manager_headers)
    assert r.status_code == 200
    assert client.get(f"/api/quotes/{created['id']}", headers=manager_headers).status_code == 404


def test_sales_cannot_delete_quote_without_grant(client, manager_headers, sales_headers):
    created = client.post("/api/quotes", json=_new_quote_payload(),
                          headers=manager_headers).json()
    r = client.delete(f"/api/quotes/{created['id']}", headers=sales_headers)
    assert r.status_code == 403


def test_admin_can_grant_delete_access_to_a_sales_user(client, admin_headers, sales_headers):
    me = client.get("/api/auth/me", headers=sales_headers).json()
    r = client.put(f"/api/users/{me['id']}", json={
        "name": "Sales", "email": "sales@evavo.test", "role": "sales",
        "is_active": True, "can_delete": True,
    }, headers=admin_headers)
    assert r.status_code == 200 and r.json()["can_delete"] is True

    created = client.post("/api/quotes", json=_new_quote_payload(),
                          headers=admin_headers).json()
    r2 = client.delete(f"/api/quotes/{created['id']}", headers=sales_headers)
    assert r2.status_code == 200


def test_cannot_delete_quote_with_revisions(client, manager_headers):
    created = client.post("/api/quotes", json=_new_quote_payload(),
                          headers=manager_headers).json()
    client.post(f"/api/quotes/{created['id']}/revise", headers=manager_headers)
    r = client.delete(f"/api/quotes/{created['id']}", headers=manager_headers)
    assert r.status_code == 400


def test_manager_can_create_and_delete_product(client, manager_headers):
    r = client.post("/api/masters/products", json={
        "name": "Test Facial Steamer", "category": "Salon Equipment",
        "source_price_inr": 5000.0,
    }, headers=manager_headers)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    r2 = client.delete(f"/api/masters/products/{pid}", headers=manager_headers)
    assert r2.status_code == 200
    assert client.get(f"/api/products/{pid}", headers=manager_headers).status_code == 404


def test_sales_cannot_create_product(client, sales_headers):
    r = client.post("/api/masters/products", json={
        "name": "Test Product", "category": "Salon Equipment",
    }, headers=sales_headers)
    assert r.status_code == 403


def test_cannot_delete_product_used_on_a_quote(client, manager_headers):
    client.post("/api/quotes", json=_new_quote_payload(), headers=manager_headers)
    r = client.delete("/api/masters/products/1", headers=manager_headers)
    assert r.status_code == 400


# --- Lead linkage survives create/read/revise -------------------------------

def test_quote_carries_lead_id_through_create_and_revise(client, manager_headers):
    client_row = client.post("/api/masters/clients", json={"name": "Acme Spa"},
                             headers=manager_headers).json()
    project = client.post("/api/masters/projects", json={
        "name": "Acme Fitout", "client_id": client_row["id"]}, headers=manager_headers).json()
    lead = client.post("/api/masters/leads", json={
        "name": "Jane Doe", "project_id": project["id"]}, headers=manager_headers).json()

    payload = _new_quote_payload()
    payload["lead_id"] = lead["id"]
    created = client.post("/api/quotes", json=payload, headers=manager_headers).json()
    assert created["lead_id"] == lead["id"]

    fetched = client.get(f"/api/quotes/{created['id']}", headers=manager_headers).json()
    assert fetched["lead_id"] == lead["id"]

    rev = client.post(f"/api/quotes/{created['id']}/revise", headers=manager_headers).json()
    assert rev["lead_id"] == lead["id"]
