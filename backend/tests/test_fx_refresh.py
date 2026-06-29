"""POST /api/fx/refresh: role gating + all-or-nothing external-call handling.

The outbound call to Frankfurter.app is monkeypatched so these tests don't
depend on network access (and don't flake on rate-limits/downtime).
"""

import app.routers.fx as fx_router


def _count_rows(client, manager_headers):
    return len(client.get("/api/fx", headers=manager_headers).json())


def test_refresh_fx_manager_success(client, manager_headers, monkeypatch):
    monkeypatch.setattr(fx_router, "_fetch_live_rate",
                        lambda c, ccy: {"USD": 84.12, "EUR": 91.05}[ccy])
    before = _count_rows(client, manager_headers)

    r = client.post("/api/fx/refresh", headers=manager_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 2
    assert {row["currency"] for row in rows} == {"USD", "EUR"}
    assert all(row["kind"] == "display" for row in rows)
    by_ccy = {row["currency"]: row["rate_to_inr"] for row in rows}
    assert by_ccy == {"USD": 84.12, "EUR": 91.05}

    assert _count_rows(client, manager_headers) == before + 2


def test_refresh_fx_sales_forbidden(client, sales_headers, manager_headers):
    before = _count_rows(client, manager_headers)
    r = client.post("/api/fx/refresh", headers=sales_headers)
    assert r.status_code == 403
    assert _count_rows(client, manager_headers) == before


def test_refresh_fx_failure_no_partial_insert(client, manager_headers, monkeypatch):
    def _boom(c, ccy):
        if ccy == "EUR":
            raise __import__("fastapi").HTTPException(502, "simulated external failure")
        return 84.12
    monkeypatch.setattr(fx_router, "_fetch_live_rate", _boom)
    before = _count_rows(client, manager_headers)

    r = client.post("/api/fx/refresh", headers=manager_headers)
    assert r.status_code == 502

    assert _count_rows(client, manager_headers) == before
