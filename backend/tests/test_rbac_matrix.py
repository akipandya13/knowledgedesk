"""The permission matrix and its enforcement at the route layer."""
from __future__ import annotations

import pytest

from app.database import (ROLE_MEMBER, ROLE_SERVICE, ROLE_SUPERADMIN,
                          ROLE_TENANT_ADMIN)
from app.rbac import (ALL_PERMISSIONS, Permission, ROLE_PERMISSIONS,
                      has_permission, missing_permissions)


# ── matrix invariants ───────────────────────────────────────────────

def test_member_is_subset_of_tenant_admin():
    assert ROLE_PERMISSIONS[ROLE_MEMBER] <= ROLE_PERMISSIONS[ROLE_TENANT_ADMIN]


def test_service_is_tenant_admin_minus_user_management():
    assert ROLE_PERMISSIONS[ROLE_SERVICE] == (
        ROLE_PERMISSIONS[ROLE_TENANT_ADMIN] - {Permission.USER_MANAGE}
    )


def test_superadmin_holds_no_workspace_content_permission():
    workspacey = {
        Permission.QUERY_RUN, Permission.FEEDBACK_WRITE, Permission.DOC_READ,
        Permission.DOC_WRITE_WORKSPACE, Permission.DOC_WRITE_TENANT,
        Permission.INSIGHTS_READ, Permission.SETTINGS_READ, Permission.SETTINGS_WRITE,
        Permission.MODEL_CONNECTOR_MANAGE, Permission.DATA_CONNECTOR_MANAGE,
        Permission.AUDIT_READ,
    }
    assert ROLE_PERMISSIONS[ROLE_SUPERADMIN].isdisjoint(workspacey)


def test_only_admins_publish_company_wide():
    assert not has_permission(ROLE_MEMBER, Permission.DOC_WRITE_TENANT)
    assert has_permission(ROLE_TENANT_ADMIN, Permission.DOC_WRITE_TENANT)
    assert has_permission(ROLE_SERVICE, Permission.DOC_WRITE_TENANT)


def test_every_role_permission_is_a_known_permission():
    for perms in ROLE_PERMISSIONS.values():
        assert perms <= ALL_PERMISSIONS


def test_missing_permissions_helper():
    assert missing_permissions(ROLE_MEMBER, {Permission.DOC_WRITE_TENANT}) == {
        Permission.DOC_WRITE_TENANT}
    assert missing_permissions(ROLE_TENANT_ADMIN, {Permission.DOC_WRITE_TENANT}) == set()


# ── enforcement at the HTTP layer ──────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("get", "/api/admin/audit"),
    ("get", "/api/admin/model-connectors"),
    ("get", "/api/connectors"),
    ("put", "/api/admin/settings"),
])
def test_member_blocked_from_admin_surfaces(client, make_world, method, path):
    w = make_world()
    fn = getattr(client, method)
    kwargs = {"json": {"settings": {}}} if method == "put" else {}
    assert fn(path, headers=w["alice"], **kwargs).status_code == 403
    # the same call as admin is not a 403 (may be 200/400/422 depending on body)
    assert fn(path, headers=w["admin"], **kwargs).status_code != 403


def test_superadmin_has_no_workspace_content_access(client, make_world):
    w = make_world()
    for path in ("/api/documents", "/api/admin/stats", "/api/connectors",
                 "/api/admin/model-connectors"):
        r = client.get(path, headers=w["superadmin"])
        assert r.status_code == 403, path


def test_superadmin_content_403_names_the_reason(client, make_world):
    w = make_world()
    r = client.post("/api/query/ask", headers=w["superadmin"],
                    json={"question": "hello there"})
    assert r.status_code == 403
    assert "workspace content" in r.json()["detail"].lower()


def test_service_key_manages_connectors_but_not_users(client, make_world):
    w = make_world()
    assert client.get("/api/connectors", headers=w["service"]).status_code == 200
    assert client.get("/api/users", headers=w["service"]).status_code == 403


def test_tenant_admin_can_read_audit_and_connectors(client, make_world):
    w = make_world()
    assert client.get("/api/admin/audit", headers=w["admin"]).status_code == 200
    assert client.get("/api/connectors", headers=w["admin"]).status_code == 200


def test_unauthenticated_is_401(client):
    assert client.get("/api/documents").status_code == 401
    assert client.post("/api/query/ask", json={"question": "hi there"}).status_code == 401
