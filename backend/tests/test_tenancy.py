"""Multi-tenancy: isolation, tenant-aware authz/data access, and the
organization lifecycle (provision → configure → suspend → reactivate → delete).
"""
from __future__ import annotations

from app.database import (ApiKey, AuditLog, Document, Role, SessionLocal,
                          Tenant, User)


def _login(client, email, password="Passw0rd!123"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


# ── isolation ─────────────────────────────────────────────────────

def test_cross_tenant_data_is_invisible(client, make_world):
    a, b = make_world(), make_world()
    client.post("/api/documents/upload", headers=a["admin"],
                files={"files": ("secret-a.txt", b"alpha", "text/plain")},
                data={"scope": "company"})

    b_docs = client.get("/api/documents", headers=b["admin"]).json()
    assert all(d["filename"] != "secret-a.txt" for d in b_docs)

    # audit of one workspace never contains the other's rows
    b_audit = client.get("/api/admin/audit", headers=b["admin"]).json()
    assert all(r["tenant_id"] in (None, b["tenant_id"]) for r in b_audit)

    # cannot act on the other workspace's users
    r = client.patch(f"/api/users/{a['ids']['alice']}", headers=b["admin"],
                     json={"full_name": "hijacked"})
    assert r.status_code in (403, 404)


def test_tenant_admin_cannot_reach_platform_tenant_api(client, make_world):
    w = make_world()
    assert client.get("/api/admin/tenants", headers=w["admin"]).status_code == 403
    assert client.post(f"/api/admin/tenants/{w['slug']}/suspend", headers=w["admin"],
                       json={}).status_code == 403


# ── suspension ────────────────────────────────────────────────────

def test_suspend_blocks_the_workspace_but_not_superadmin(client, make_world):
    w = make_world()
    assert client.get("/api/documents", headers=w["alice"]).status_code == 200

    r = client.post(f"/api/admin/tenants/{w['slug']}/suspend",
                    headers=w["superadmin"], json={"reason": "non-payment"})
    assert r.status_code == 200 and r.json()["status"] == "suspended"

    # every credential for the workspace is refused
    assert client.get("/api/documents", headers=w["alice"]).status_code == 403
    assert client.get("/api/admin/audit", headers=w["admin"]).status_code == 403
    assert client.get("/api/documents", headers=w["service"]).status_code == 403
    assert client.post("/api/auth/login",
                       json={"email": f"alice@{w['slug']}.test",
                             "password": "Passw0rd!123"}).status_code == 403
    # superadmin still manages it
    assert client.get(f"/api/admin/tenants/{w['slug']}",
                      headers=w["superadmin"]).status_code == 200

    client.post(f"/api/admin/tenants/{w['slug']}/reactivate", headers=w["superadmin"])
    assert client.get("/api/documents", headers=w["alice"]).status_code == 200


def test_suspend_revokes_live_sessions(client, make_world):
    w = make_world()
    tokens = _login(client, f"alice@{w['slug']}.test")
    refresh = tokens["refresh_token"]

    client.post(f"/api/admin/tenants/{w['slug']}/suspend", headers=w["superadmin"], json={})
    # the refresh chain is dead — revoked on suspend
    assert client.post("/api/auth/refresh",
                       json={"refresh_token": refresh}).status_code in (401, 403)

    db = SessionLocal()
    try:
        uid = w["ids"]["alice"]
        from app.database import RefreshToken
        live = db.query(RefreshToken).filter(RefreshToken.user_id == uid,
                                             RefreshToken.revoked == 0).count()
        assert live == 0
    finally:
        db.close()


# ── provisioning & configuration ─────────────────────────────────

def test_create_workspace_with_first_admin(client, make_world):
    w = make_world()
    r = client.post("/api/admin/tenants", headers=w["superadmin"],
                    json={"slug": "acme-co", "name": "Acme Co",
                          "admin_email": "boss@acme-co.test",
                          "entitlements": ["sso"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "active"
    temp_pw = body["admin"]["temporary_password"]

    # the provisioned admin can sign in and is a tenant_admin
    login = client.post("/api/auth/login",
                        json={"email": "boss@acme-co.test", "password": temp_pw})
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "tenant_admin"

    detail = client.get("/api/admin/tenants/acme-co", headers=w["superadmin"]).json()
    assert detail["entitlements"]["sso"] is True
    assert detail["counts"]["users"] == 1


def test_update_tenant_entitlements_is_audited(client, make_world):
    w = make_world()
    client.patch(f"/api/admin/tenants/{w['slug']}", headers=w["superadmin"],
                 json={"entitlements": ["sso"], "name": "Renamed Inc"})

    detail = client.get(f"/api/admin/tenants/{w['slug']}", headers=w["superadmin"]).json()
    assert detail["name"] == "Renamed Inc"
    assert detail["entitlements"]["sso"] is True

    # the auth-policy view the workspace admin sees now reports the entitlement
    pol = client.get("/api/access/auth-policy", headers=w["admin"]).json()
    assert pol["entitlements"]["sso"] is True

    hist = client.get(
        f"/api/admin/platform/audit?prefix=tenant.updated", headers=w["superadmin"]).json()
    assert hist and "entitlements" in (hist[0]["changes"] or {})


# ── deletion ─────────────────────────────────────────────────────

def test_delete_workspace_leaves_no_orphans(client, make_world):
    a, b = make_world(), make_world()
    client.post("/api/documents/upload", headers=a["admin"],
                files={"files": ("d.txt", b"x", "text/plain")}, data={"scope": "company"})
    client.post("/api/access/roles", headers=a["admin"],
                json={"key": "auditor", "name": "Auditor", "permissions": ["audit.read"]})
    client.post("/api/access/api-keys", headers=a["admin"], json={"name": "bot"})
    tid = a["tenant_id"]

    r = client.delete(f"/api/admin/tenants/{a['slug']}", headers=a["superadmin"])
    assert r.status_code == 200
    assert r.json()["rows_deleted"]

    db = SessionLocal()
    try:
        for model in (Document, Role, ApiKey, User):
            assert db.query(model).filter(model.tenant_id == tid).count() == 0, model
        assert db.query(AuditLog).filter(AuditLog.tenant_id == tid).count() == 0
        assert db.query(Tenant).filter(Tenant.id == tid).count() == 0
        # the other workspace is untouched
        assert db.query(User).filter(User.tenant_id == b["tenant_id"]).count() > 0
    finally:
        db.close()

    # platform audit keeps the deletion record
    pa = client.get("/api/admin/platform/audit?prefix=tenant.deleted",
                    headers=b["superadmin"]).json()
    assert any(row["detail"] == a["slug"] for row in pa)
