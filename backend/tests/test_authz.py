"""Fine-grained access: custom roles, groups, allow/deny grants, resource ACLs,
and clearance-based confidentiality filtering."""
from __future__ import annotations

import io

from app import authz
from app.database import SessionLocal, User


def _upload(client, headers, name="doc.txt", body=None, **form):
    # body must be unique per file — dedup is by content hash within a scope
    body = body or f"policy text for {name} :: {name * 3}".encode()
    return client.post("/api/documents/upload", headers=headers,
                       files={"files": (name, io.BytesIO(body), "text/plain")},
                       data=form or None)


# ── router gating ─────────────────────────────────────────────────

def test_access_router_requires_access_manage(client, make_world):
    w = make_world()
    assert client.get("/api/access/roles", headers=w["alice"]).status_code == 403
    assert client.get("/api/access/roles", headers=w["admin"]).status_code == 200
    # /me is open to any workspace principal
    assert client.get("/api/access/me", headers=w["alice"]).status_code == 200


def test_platform_permission_is_not_assignable(client, make_world):
    w = make_world()
    r = client.post("/api/access/roles", headers=w["admin"],
                    json={"key": "bad", "permissions": ["tenant.manage"]})
    assert r.status_code == 400


# ── custom roles ─────────────────────────────────────────────────

def test_custom_role_grants_a_permission_a_member_lacks(client, make_world):
    w = make_world()
    assert client.get("/api/admin/audit", headers=w["alice"]).status_code == 403

    role = client.post("/api/access/roles", headers=w["admin"],
                       json={"key": "auditor", "name": "Auditor",
                             "permissions": ["audit.read"]}).json()
    client.post("/api/access/role-assignments", headers=w["admin"],
                json={"subject_type": "user", "subject_id": w["ids"]["alice"],
                      "role_id": role["id"]})

    assert client.get("/api/admin/audit", headers=w["alice"]).status_code == 200


def test_effective_endpoint_reflects_assignment(client, make_world):
    w = make_world()
    role = client.post("/api/access/roles", headers=w["admin"],
                       json={"key": "conn", "permissions": ["data_connector.manage"]}).json()
    client.post("/api/access/role-assignments", headers=w["admin"],
                json={"subject_type": "user", "subject_id": w["ids"]["alice"], "role_id": role["id"]})
    eff = client.get(f"/api/access/effective/{w['ids']['alice']}", headers=w["admin"]).json()
    assert "data_connector.manage" in eff["permissions"]
    assert client.get("/api/connectors", headers=w["alice"]).status_code == 200


# ── grants: allow / deny with deny precedence ────────────────────

def test_allow_grant_adds_a_permission(client, make_world):
    w = make_world()
    client.post("/api/access/grants", headers=w["admin"],
                json={"subject_type": "user", "subject_id": w["ids"]["bob"],
                      "permission": "audit.read", "effect": "allow"})
    assert client.get("/api/admin/audit", headers=w["bob"]).status_code == 200


def test_deny_grant_overrides_a_held_permission(client, make_world):
    w = make_world()
    assert client.get("/api/admin/audit", headers=w["admin"]).status_code == 200
    client.post("/api/access/grants", headers=w["admin"],
                json={"subject_type": "user", "subject_id": w["ids"]["admin"],
                      "permission": "audit.read", "effect": "deny"})
    assert client.get("/api/admin/audit", headers=w["admin"]).status_code == 403


def test_deny_wins_over_allow(client, make_world):
    w = make_world()
    for effect in ("allow", "deny"):
        client.post("/api/access/grants", headers=w["admin"],
                    json={"subject_type": "user", "subject_id": w["ids"]["alice"],
                          "permission": "audit.read", "effect": effect})
    eff = client.get(f"/api/access/effective/{w['ids']['alice']}", headers=w["admin"]).json()
    assert "audit.read" not in eff["permissions"]


def test_cannot_deny_own_access_manage(client, make_world):
    w = make_world()
    r = client.post("/api/access/grants", headers=w["admin"],
                    json={"subject_type": "user", "subject_id": w["ids"]["admin"],
                          "permission": "access.manage", "effect": "deny"})
    assert r.status_code == 400


# ── groups ───────────────────────────────────────────────────────

def test_group_role_assignment_applies_to_members(client, make_world):
    w = make_world()
    g = client.post("/api/access/groups", headers=w["admin"], json={"name": "Compliance"}).json()
    client.post(f"/api/access/groups/{g['id']}/members", headers=w["admin"],
                json={"user_id": w["ids"]["bob"]})
    role = client.post("/api/access/roles", headers=w["admin"],
                       json={"key": "grp-auditor", "permissions": ["audit.read"]}).json()
    client.post("/api/access/role-assignments", headers=w["admin"],
                json={"subject_type": "group", "subject_id": g["id"], "role_id": role["id"]})

    assert client.get("/api/admin/audit", headers=w["bob"]).status_code == 200
    # alice is not in the group
    assert client.get("/api/admin/audit", headers=w["alice"]).status_code == 403


# ── resource ACLs ────────────────────────────────────────────────

def test_resource_grant_shares_one_document_for_read(client, make_world):
    w = make_world()
    bob_doc = _upload(client, w["bob"], name="bob-secret.txt").json()["accepted"][0]["id"]
    # alice can't see it
    before = {d["filename"] for d in client.get("/api/documents", headers=w["alice"]).json()}
    assert "bob-secret.txt" not in before

    client.post("/api/access/resource-grants", headers=w["admin"],
                json={"subject_type": "user", "subject_id": w["ids"]["alice"],
                      "resource_type": "document", "resource_id": str(bob_doc),
                      "permission": "document.read"})

    after = {d["filename"] for d in client.get("/api/documents", headers=w["alice"]).json()}
    assert "bob-secret.txt" in after


def test_resource_grant_allows_delete_of_another_users_doc(client, make_world):
    w = make_world()
    bob_doc = _upload(client, w["bob"], name="bob-del.txt").json()["accepted"][0]["id"]
    assert client.delete(f"/api/documents/{bob_doc}", headers=w["alice"]).status_code == 403

    client.post("/api/access/resource-grants", headers=w["admin"],
                json={"subject_type": "user", "subject_id": w["ids"]["alice"],
                      "resource_type": "document", "resource_id": str(bob_doc),
                      "permission": "document.delete"})

    assert client.delete(f"/api/documents/{bob_doc}", headers=w["alice"]).status_code == 200


# ── clearance (ABAC) ─────────────────────────────────────────────

def _set_clearance(client, w, uid, level):
    return client.patch(f"/api/users/{uid}", headers=w["admin"], json={"clearance": level})


def test_clearance_filters_confidential_documents(client, make_world):
    w = make_world()
    # publish a confidential company-wide doc
    _upload(client, w["admin"], name="secret-plan.txt", scope="company", confidentiality="confidential")
    _upload(client, w["admin"], name="handbook.txt", scope="company", confidentiality="internal")

    # policy off → alice sees both
    seen = {d["filename"] for d in client.get("/api/documents?scope=company", headers=w["alice"]).json()}
    assert {"secret-plan.txt", "handbook.txt"} <= seen

    # turn enforcement on, drop alice below 'confidential' (30) -> clearance 20
    assert client.put("/api/access/policy", headers=w["admin"],
                      json={"confidentiality_enforced": True}).status_code == 200
    assert _set_clearance(client, w, w["ids"]["alice"], 20).status_code == 200

    seen = {d["filename"] for d in client.get("/api/documents?scope=company", headers=w["alice"]).json()}
    assert "handbook.txt" in seen
    assert "secret-plan.txt" not in seen
    # admin is unaffected
    admin_seen = {d["filename"] for d in client.get("/api/documents?scope=company", headers=w["admin"]).json()}
    assert "secret-plan.txt" in admin_seen


def test_resource_grant_overrides_clearance(client, make_world):
    w = make_world()
    doc = _upload(client, w["admin"], name="restricted.txt", scope="company",
                  confidentiality="restricted").json()["accepted"][0]["id"]
    client.put("/api/access/policy", headers=w["admin"], json={"confidentiality_enforced": True})
    _set_clearance(client, w, w["ids"]["alice"], 10)   # public only

    assert "restricted.txt" not in {d["filename"] for d in
                                    client.get("/api/documents", headers=w["alice"]).json()}
    client.post("/api/access/resource-grants", headers=w["admin"],
                json={"subject_type": "user", "subject_id": w["ids"]["alice"],
                      "resource_type": "document", "resource_id": str(doc),
                      "permission": "document.read"})
    assert "restricted.txt" in {d["filename"] for d in
                                client.get("/api/documents", headers=w["alice"]).json()}


# ── unit: resolver ───────────────────────────────────────────────

def test_effective_permissions_is_inert_without_config(make_world):
    w = make_world()
    db = SessionLocal()
    try:
        alice = db.get(User, w["ids"]["alice"])
        from app.rbac import ROLE_PERMISSIONS
        assert authz.effective_permissions(db, alice.role, alice) == ROLE_PERMISSIONS["member"]
    finally:
        db.close()
