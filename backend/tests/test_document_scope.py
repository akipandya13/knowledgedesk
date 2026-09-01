"""The two-layer document model: personal workspace vs company-wide, and the
search-scope filter that keeps one user out of another's private documents."""
from __future__ import annotations

import io

from app.database import SessionLocal, Document


def _upload(client, headers, name="note.txt", body=b"hello world", **form):
    return client.post(
        "/api/documents/upload",
        headers=headers,
        files={"files": (name, io.BytesIO(body), "text/plain")},
        data=form or None,
    )


def _doc(db_id):
    db = SessionLocal()
    try:
        return db.get(Document, db_id)
    finally:
        db.close()


# ── creation / scope resolution ────────────────────────────────────

def test_member_upload_lands_in_own_workspace(client, make_world):
    w = make_world()
    r = _upload(client, w["alice"], name="alice-private.txt")
    assert r.status_code == 200
    doc = r.json()["accepted"][0]
    assert doc["scope"] == "workspace"
    assert doc["owner_user_id"] == w["ids"]["alice"]


def test_admin_upload_defaults_to_company_wide(client, make_world):
    w = make_world()
    r = _upload(client, w["admin"], name="handbook.txt")
    assert r.status_code == 200
    doc = r.json()["accepted"][0]
    assert doc["scope"] == "tenant"
    assert doc["owner_user_id"] is None


def test_member_cannot_publish_company_wide(client, make_world):
    w = make_world()
    r = _upload(client, w["alice"], name="sneaky.txt", scope="company")
    assert r.status_code == 403


def test_admin_can_place_a_doc_in_a_members_workspace(client, make_world):
    w = make_world()
    r = _upload(client, w["admin"], name="for-bob.txt",
                scope="workspace", owner_user_id=str(w["ids"]["bob"]))
    assert r.status_code == 200
    doc = r.json()["accepted"][0]
    assert doc["scope"] == "workspace" and doc["owner_user_id"] == w["ids"]["bob"]


def test_member_cannot_target_another_users_workspace(client, make_world):
    w = make_world()
    r = _upload(client, w["alice"], name="x.txt",
                scope="workspace", owner_user_id=str(w["ids"]["bob"]))
    assert r.status_code == 403


# ── visibility on the document list ────────────────────────────────

def test_members_see_company_docs_plus_only_their_own(client, make_world):
    w = make_world()
    _upload(client, w["admin"], name="company.txt")
    _upload(client, w["alice"], name="alice-only.txt")
    _upload(client, w["bob"], name="bob-only.txt")

    alice_files = {d["filename"] for d in client.get("/api/documents", headers=w["alice"]).json()}
    assert "company.txt" in alice_files
    assert "alice-only.txt" in alice_files
    assert "bob-only.txt" not in alice_files

    # admin sees everything in the workspace
    admin_files = {d["filename"] for d in client.get("/api/documents", headers=w["admin"]).json()}
    assert {"company.txt", "alice-only.txt", "bob-only.txt"} <= admin_files


def test_list_scope_filter(client, make_world):
    w = make_world()
    _upload(client, w["admin"], name="company.txt")
    _upload(client, w["alice"], name="mine.txt")

    only_mine = client.get("/api/documents?scope=workspace", headers=w["alice"]).json()
    assert {d["filename"] for d in only_mine} == {"mine.txt"}
    only_co = client.get("/api/documents?scope=company", headers=w["alice"]).json()
    assert {d["filename"] for d in only_co} == {"company.txt"}


# ── deletion rules ────────────────────────────────────────────────

def test_member_cannot_delete_another_members_doc(client, make_world):
    w = make_world()
    bob_doc = _upload(client, w["bob"], name="bob.txt").json()["accepted"][0]["id"]
    assert client.delete(f"/api/documents/{bob_doc}", headers=w["alice"]).status_code == 403
    # bob can; admin can
    assert client.delete(f"/api/documents/{bob_doc}", headers=w["bob"]).status_code == 200


def test_member_cannot_delete_company_doc_but_admin_can(client, make_world):
    w = make_world()
    co_doc = _upload(client, w["admin"], name="co.txt").json()["accepted"][0]["id"]
    assert client.delete(f"/api/documents/{co_doc}", headers=w["alice"]).status_code == 403
    assert client.delete(f"/api/documents/{co_doc}", headers=w["admin"]).status_code == 200


# ── search-scope access filter (unit-level on the retrieval filter) ──

def test_access_filter_isolates_private_docs():
    from app.services.vectorstore import _query_filter

    f_all = _query_filter(None, {"user_id": 7, "scope": "all"})
    # nested OR condition present
    assert f_all is not None and len(f_all.__dict__["must"]) == 1

    f_company = _query_filter(None, {"user_id": 7, "scope": "company"})
    # company scope must not reference the caller's owner id
    dumped = repr(f_company.__dict__)
    assert "7" not in dumped

    f_ws = _query_filter(None, {"user_id": 7, "scope": "workspace"})
    assert "7" in repr(f_ws.__dict__)


def test_ask_passes_caller_identity_into_retrieval(client, make_world, monkeypatch):
    w = make_world()
    seen = {}

    async def fake_answer(tenant, question, filters=None, access=None):
        seen["access"] = access
        return {"query_id": 1, "answer": "ok", "mode": "llm", "confidence": 0.9, "sources": []}

    monkeypatch.setattr("app.routers.query.rag.answer", fake_answer)
    r = client.post("/api/query/ask", headers=w["alice"],
                    json={"question": "what is the pto policy", "scope": "workspace"})
    assert r.status_code == 200
    assert seen["access"]["user_id"] == w["ids"]["alice"]
    assert seen["access"]["scope"] == "workspace"
    assert seen["access"]["granted_doc_ids"] == []          # no resource grants
    assert seen["access"]["allowed_confidentialities"] is None  # policy off by default
