"""Encryption at rest: envelope key hierarchy, transparent column encryption,
Qdrant chunk-text encryption, legacy plaintext passthrough, KEK rotation."""
from __future__ import annotations

from sqlalchemy import text as sql

from app import crypto
from app.database import AuditLog, QueryLog, SessionLocal
from app.services import vectorstore


class _Chunk:
    def __init__(self, t, page=1, index=0):
        self.text, self.page, self.index = t, page, index


# ── primitives ──────────────────────────────────────────────────

def test_field_encrypt_decrypt_and_passthrough():
    tok = crypto.encrypt("top secret")
    assert tok.startswith("kdenc:") and "top secret" not in tok
    assert crypto.decrypt(tok) == "top secret"
    assert crypto.decrypt("legacy plaintext value") == "legacy plaintext value"
    assert crypto.encrypt(None) is None and crypto.decrypt(None) is None


# ── SQLAlchemy column types ────────────────────────────────────

def test_query_log_is_ciphertext_on_disk_plaintext_via_orm():
    db = SessionLocal()
    try:
        row = QueryLog(tenant_id=1, question="what is our PTO policy?",
                       answer="20 days per year", mode="llm",
                       sources_json=[{"n": 1, "filename": "hr.pdf"}])
        db.add(row)
        db.commit()
        rid = row.id

        raw_q, raw_a, raw_s = db.execute(
            sql("SELECT question, answer, sources_json FROM query_log WHERE id=:i"),
            {"i": rid}).one()
        assert raw_q.startswith("kdenc:") and "PTO" not in raw_q
        assert raw_a.startswith("kdenc:") and "20 days" not in raw_a
        assert raw_s.startswith("kdenc:") and "hr.pdf" not in raw_s

        db.expire_all()
        fresh = db.get(QueryLog, rid)
        assert fresh.question == "what is our PTO policy?"
        assert fresh.answer == "20 days per year"
        assert fresh.sources_json == [{"n": 1, "filename": "hr.pdf"}]
    finally:
        db.close()


def test_audit_detail_encrypted(client, make_world):
    w = make_world()
    # any audited mutation
    client.post("/api/access/roles", headers=w["admin"],
                json={"key": "enc-probe", "permissions": ["audit.read"]})
    db = SessionLocal()
    try:
        rows = db.execute(sql(
            "SELECT detail FROM audit_log WHERE action='access.role_created' ORDER BY id DESC LIMIT 1"
        )).fetchall()
        assert rows and rows[0][0].startswith("kdenc:")
        obj = db.query(AuditLog).filter(AuditLog.action == "access.role_created") \
            .order_by(AuditLog.id.desc()).first()
        assert "enc-probe" in obj.detail            # decrypts transparently
    finally:
        db.close()


def test_legacy_plaintext_row_reads_without_error():
    db = SessionLocal()
    try:
        db.execute(sql("INSERT INTO query_log (tenant_id, question, answer, mode) "
                       "VALUES (1, :q, :a, 'llm')"),
                   {"q": "PRE-ENCRYPTION QUESTION", "a": "PRE-ENCRYPTION ANSWER"})
        db.commit()
        rid = db.execute(sql("SELECT id FROM query_log WHERE question=:q"),
                         {"q": "PRE-ENCRYPTION QUESTION"}).scalar()
        obj = db.get(QueryLog, rid)
        assert obj.question == "PRE-ENCRYPTION QUESTION"   # passthrough, no crash
        assert obj.answer == "PRE-ENCRYPTION ANSWER"
    finally:
        db.close()


# ── Qdrant chunk text ─────────────────────────────────────────

def test_qdrant_upsert_encrypts_and_search_decrypts(fake_qdrant):
    vectorstore.upsert_chunks("acme", 7, "f.txt", [_Chunk("confidential chunk body")],
                              [[0.1, 0.2, 0.3]],
                              metadata={"embedding_model": "m", "embedding_provider": "local"})
    _, points = vectorstore._client.upserts[-1]
    stored = points[0].payload["text"]
    assert stored.startswith("kdenc:") and "confidential" not in stored
    assert crypto.decrypt(stored) == "confidential chunk body"

    class _Hit:
        score = 0.88
        payload = {"doc_id": 7, "filename": "f.txt", "page": 1,
                   "text": crypto.encrypt("confidential chunk body"),
                   "embedding_model": "m", "scope": "tenant"}
    fake_qdrant([_Hit()])
    res = vectorstore.search("acme", [0.1, 0.2, 0.3], 5, 0.0,
                             embedding_model="m", embedding_provider="local")
    assert res[0]["text"] == "confidential chunk body"


# ── KEK rotation ─────────────────────────────────────────────

def test_kek_rotation_multifernet(monkeypatch, tmp_path):
    """Runs against an isolated DATA_DIR so it can rewrap data.key freely."""
    from cryptography.fernet import Fernet
    from app.config import get_settings
    s = get_settings()
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    monkeypatch.setattr(s, "data_dir", str(tmp_path))
    monkeypatch.setattr(s, "kd_secret_key", key_a)
    crypto.reset_cache()
    try:
        legacy = crypto.encrypt_secrets({"api_key": "abc123"})   # under KEK A
        field_a = crypto.encrypt("field under A")

        # rotate: B primary, A kept so old tokens still decrypt
        monkeypatch.setattr(s, "kd_secret_key", f"{key_b},{key_a}")
        crypto.reset_cache()
        assert crypto.decrypt_secrets(legacy) == {"api_key": "abc123"}
        assert crypto.decrypt(field_a) == "field under A"        # DEK unchanged
        crypto.rewrap_data_key()                                 # re-wrap DEK under B
        fresh = crypto.encrypt_secrets({"x": 1})

        # drop A entirely
        monkeypatch.setattr(s, "kd_secret_key", key_b)
        crypto.reset_cache()
        assert crypto.decrypt_secrets(fresh) == {"x": 1}
        assert crypto.decrypt(field_a) == "field under A"
        assert crypto.decrypt(crypto.encrypt("still working")) == "still working"
    finally:
        crypto.reset_cache()
