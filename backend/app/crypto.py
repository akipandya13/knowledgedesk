"""Application-layer encryption for model connector credentials.

Connector secrets (AWS keys, Azure API keys) are stored as a single Fernet
token in the DB, never in plaintext. The master key comes from
``KD_SECRET_KEY``; when unset it is generated once and persisted to
``{data_dir}/secret.key`` (mirrors the JWT-secret handling in ``security.py``).

In production the master key should be injected from a KMS / secrets manager
rather than read from a file on disk.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

_fernet_cache: Fernet | None = None


def _derive_fernet_key(raw: str) -> bytes:
    """Accept either a real Fernet key or an arbitrary passphrase.

    A urlsafe-base64 32-byte string is used as-is; anything else is hashed to
    32 bytes so operators can set a human-friendly ``KD_SECRET_KEY``.
    """
    raw = raw.strip()
    try:
        if len(base64.urlsafe_b64decode(raw)) == 32:
            return raw.encode()
    except (ValueError, TypeError):
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())


def _load_key() -> bytes:
    s = get_settings()
    if s.kd_secret_key:
        return _derive_fernet_key(s.kd_secret_key)
    path = Path(s.data_dir) / "secret.key"
    if path.exists():
        return path.read_text().strip().encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_text(key.decode())
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def _fernet() -> Fernet:
    global _fernet_cache
    if _fernet_cache is None:
        _fernet_cache = Fernet(_load_key())
    return _fernet_cache


def encrypt_secrets(data: dict) -> str:
    """Encrypt a dict of secret fields to a Fernet token string."""
    payload = json.dumps(data or {}, separators=(",", ":")).encode()
    return _fernet().encrypt(payload).decode()


def decrypt_secrets(token: str | None) -> dict:
    """Decrypt a token produced by :func:`encrypt_secrets`. Returns {} on failure."""
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError):
        return {}
