"""Test harness.

The suite exercises the real FastAPI app end-to-end through ``TestClient``.
Two heavy externals are stubbed so tests need no services running:

  * ``qdrant_client`` — replaced by an in-memory fake (vector writes/deletes are
    recorded, searches return nothing by default; individual tests can inject
    hits via ``fake_qdrant``).
  * document ingestion — ``ingest_document`` is neutralised so uploads settle
    without parsing/embedding.
"""
from __future__ import annotations

import itertools
import os
import sys
import tempfile
import types
import uuid
from pathlib import Path

import pytest

_SLUG_SEQ = itertools.count(1)

# ── env: isolated data dir, deterministic secrets, no demo noise ──────
_DATA_DIR = tempfile.mkdtemp(prefix="kd-test-")
os.environ.update(
    DATA_DIR=_DATA_DIR,
    JWT_SECRET="test-secret-do-not-use-in-prod",
    KD_SECRET_KEY="dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRpbmcxMjM=",
    DEMO_TENANT_ENABLED="false",
    DEMO_USERS_ENABLED="false",
    SUPERADMIN_EMAIL="root@platform.test",
    SUPERADMIN_PASSWORD="RootPass!12345",
    PASSWORD_MIN_LENGTH="8",
    OBSERVABILITY_SINKS="stdout,sqlite",
    OBSERVABILITY_HEALTH_PROBE_SECONDS="0",
    OBS_STDOUT_METRICS="false",
    AUTH_LOGIN_RATE_PER_MIN="5",
    AUTH_LOGIN_RATE_IP_PER_MIN="100000",
    AUTH_MAX_SESSIONS_PER_USER="4",
    EMAIL_SENDER="console",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── stub qdrant_client before anything imports vectorstore ────────────
class _FakePoints:
    def __init__(self, points):
        self.points = points


class _FakeQdrant:
    """Records writes; returns configured hits from query_points."""

    _next_hits: list = []

    def __init__(self, *a, **k):
        self.deleted: list = []
        self.upserts: list = []

    # collection lifecycle -------------------------------------------------
    def collection_exists(self, name):  # noqa: D401
        return True

    def create_collection(self, *a, **k):
        return None

    def get_collections(self):
        return types.SimpleNamespace(collections=[])

    def delete_collection(self, *a, **k):
        return None

    # data ---------------------------------------------------------------
    def upsert(self, collection_name, points):
        self.upserts.append((collection_name, points))

    def delete(self, collection_name, points_selector=None):
        self.deleted.append((collection_name, points_selector))

    def query_points(self, **kwargs):
        hits, _FakeQdrant._next_hits = _FakeQdrant._next_hits, []
        return _FakePoints(hits)


_qc = types.ModuleType("qdrant_client")
_qc.QdrantClient = _FakeQdrant
_qc_models = types.ModuleType("qdrant_client.models")


def _stub_repr(self):
    return f"{type(self).__name__}({self.__dict__!r})"


for _name in ("Distance", "FieldCondition", "Filter", "IsEmptyCondition",
              "MatchAny", "MatchValue", "PayloadField", "PointStruct",
              "VectorParams"):
    setattr(_qc_models, _name, type(_name, (), {
        "__init__": lambda self, **k: self.__dict__.update(k),
        "__repr__": _stub_repr,
    }))
_qc.models = _qc_models
sys.modules.setdefault("qdrant_client", _qc)
sys.modules.setdefault("qdrant_client.models", _qc_models)

from fastapi.testclient import TestClient  # noqa: E402

from app import database  # noqa: E402
from app.database import (ROLE_MEMBER, ROLE_SUPERADMIN, ROLE_TENANT_ADMIN,  # noqa: E402
                          SessionLocal, Tenant, User, new_api_key)
from app import security  # noqa: E402
from app.services import ingestion as _ingestion  # noqa: E402
import app.main as main  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_ingest(monkeypatch):
    monkeypatch.setattr(_ingestion, "ingest_document", lambda *a, **k: None)
    monkeypatch.setattr("app.routers.documents.vectorstore.delete_document",
                        lambda *a, **k: None)


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    database.init_db()
    yield


@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def fake_qdrant():
    """Give a test control over the next ``query_points`` result."""
    def _set(hits):
        _FakeQdrant._next_hits = hits
    yield _set
    _FakeQdrant._next_hits = []


# ── account factory ──────────────────────────────────────────────────

@pytest.fixture()
def make_world():
    """Create an isolated tenant with an admin + two members, plus a superadmin.

    Returns a dict of auth-header sets keyed by role/alias.
    """
    created = {"tenants": [], "users": [], "n": 0}

    def _hdr(*, uid, email, role, tenant_id, pwv, slug):
        tok = security.create_access_token(
            user_id=uid, email=email, role=role, tenant_id=tenant_id,
            tenant_slug=slug if role != ROLE_SUPERADMIN else None,
            password_version=pwv)
        return {"Authorization": f"Bearer {tok}"}

    def _factory(slug=None):
        slug = slug or f"ws{next(_SLUG_SEQ)}-{uuid.uuid4().hex[:6]}"
        db = SessionLocal()
        try:
            tenant = Tenant(slug=slug, name=slug.title(), api_key=new_api_key())
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
            tenant_id, api_key = tenant.id, tenant.api_key
            created["tenants"].append(tenant_id)

            def _mk(email, role):
                u = User(email=email, full_name=email, role=role,
                         tenant_id=tenant_id if role != ROLE_SUPERADMIN else None,
                         password_hash=security.hash_password("Passw0rd!123"),
                         force_password_change=0)
                db.add(u)
                db.commit()
                db.refresh(u)
                created["users"].append(u.id)
                return _hdr(uid=u.id, email=u.email, role=u.role,
                            tenant_id=u.tenant_id, pwv=u.password_version, slug=slug), u.id

            (admin_h, admin_id) = _mk(f"admin@{slug}.test", ROLE_TENANT_ADMIN)
            (alice_h, alice_id) = _mk(f"alice@{slug}.test", ROLE_MEMBER)
            (bob_h, bob_id) = _mk(f"bob@{slug}.test", ROLE_MEMBER)

            root = db.query(User).filter(User.role == ROLE_SUPERADMIN).first()
            root_h = _hdr(uid=root.id, email=root.email, role=root.role,
                          tenant_id=None, pwv=root.password_version, slug=slug)
        finally:
            db.close()

        return {
            "slug": slug, "tenant_id": tenant_id,
            "admin": admin_h, "alice": alice_h, "bob": bob_h,
            "superadmin": root_h,
            "service": {"X-API-Key": api_key},
            "ids": {"admin": admin_id, "alice": alice_id, "bob": bob_id},
        }

    yield _factory
