"""Encryption at rest — envelope encryption with key rotation.

Key hierarchy (textbook two-tier):

    KEK  (key-encryption key)   from KD_SECRET_KEY, or generated to {DATA_DIR}/secret.key
      │  a MultiFernet: the first key encrypts, every key can decrypt, so KD_SECRET_KEY
      │  may be a comma list during rotation (new,old).
      ▼
    DEK  (data-encryption key)  random Fernet key, stored *wrapped by the KEK* in
                                {DATA_DIR}/data.key. Rotating the KEK only re-wraps
                                this file — no data re-encryption needed.
      │
      ▼
    field / payload ciphertext  (AES-128-CBC + HMAC via Fernet)

What this module protects:
  * ``encrypt`` / ``decrypt`` + the ``EncryptedText`` / ``EncryptedJSON`` SQLAlchemy
    types → the Q&A transcript (QueryLog), audit detail, and the document chunk
    text stored in Qdrant payloads.
  * ``encrypt_secrets`` / ``decrypt_secrets`` → connector credentials, TOTP
    secrets and SSO client secrets (encrypted directly with the KEK).

Legacy plaintext is read through transparently (``decrypt`` returns the input
unchanged when it is not a valid token), so encryption rolls out gradually —
run ``scripts/reencrypt_at_rest.py`` to convert existing rows and vectors.

In production the KEK should come from a KMS / Vault, never a file on the same
disk as the ciphertext. `KD_SECRET_KEY` accepts that value directly.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import get_settings
from .secret_resolver import resolve_mapping, resolve_secret

log = logging.getLogger("knowledgedesk.crypto")

_kek_cache: MultiFernet | None = None
_dek_cache: Fernet | None = None


# ── key material ──────────────────────────────────────────────────

def _to_fernet_key(raw: str) -> bytes:
    """A urlsafe-base64 32-byte string is used as-is; anything else is hashed to
    32 bytes so operators can set a human-friendly passphrase."""
    raw = raw.strip()
    try:
        if len(base64.urlsafe_b64decode(raw)) == 32:
            return raw.encode()
    except (ValueError, TypeError):
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())


def _kek() -> MultiFernet:
    global _kek_cache
    if _kek_cache is not None:
        return _kek_cache
    s = get_settings()
    keys: list[Fernet] = []
    if s.kd_secret_key:
        # comma list → [primary, previous, …] for rotation; each part may itself
        # be a ${provider:locator} reference (env / file / Vault / cloud SM).
        for part in s.kd_secret_key.split(","):
            part = (resolve_secret(part.strip()) or "").strip()
            if part:
                keys.append(Fernet(_to_fernet_key(part)))
    else:
        path = Path(s.data_dir) / "secret.key"
        if path.exists():
            keys.append(Fernet(path.read_text().strip().encode()))
        else:
            k = Fernet.generate_key()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(k.decode())
            _chmod_600(path)
            keys.append(Fernet(k))
    _kek_cache = MultiFernet(keys)
    return _kek_cache


def _dek() -> Fernet:
    """The data key, unwrapped with the KEK. Generated (and wrapped) on first use."""
    global _dek_cache
    if _dek_cache is not None:
        return _dek_cache
    s = get_settings()
    path = Path(s.data_dir) / "data.key"
    kek = _kek()
    if path.exists():
        wrapped = path.read_text().strip().encode()
        try:
            raw = kek.decrypt(wrapped)
        except InvalidToken as exc:  # KEK changed without re-wrapping data.key
            raise RuntimeError(
                "data.key cannot be unwrapped with the current KD_SECRET_KEY — "
                "keep the previous key in the comma list and run "
                "scripts/reencrypt_at_rest.py --rewrap") from exc
        _dek_cache = Fernet(raw)
        return _dek_cache
    raw = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(kek.encrypt(raw).decode())
    _chmod_600(path)
    _dek_cache = Fernet(raw)
    return _dek_cache


def _chmod_600(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def reset_cache() -> None:
    """Drop cached keys — used by rotation tooling and tests."""
    global _kek_cache, _dek_cache
    _kek_cache = _dek_cache = None


def rewrap_data_key() -> None:
    """Re-encrypt {DATA_DIR}/data.key under the current primary KEK. Call after
    changing KD_SECRET_KEY (with the old key still present to unwrap once)."""
    s = get_settings()
    path = Path(s.data_dir) / "data.key"
    raw = _kek().decrypt(path.read_text().strip().encode())
    path.write_text(MultiFernet(_kek()._fernets[:1]).encrypt(raw).decode())
    _chmod_600(path)
    reset_cache()


# ── field encryption (DEK) ────────────────────────────────────────

_PREFIX = "kdenc:"          # marks our ciphertext so legacy plaintext is obvious


def encrypt(text: str | None) -> str | None:
    if text is None:
        return None
    return _PREFIX + _dek().encrypt(text.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if token is None:
        return None
    if not isinstance(token, str) or not token.startswith(_PREFIX):
        return token                              # legacy plaintext — pass through
    try:
        return _dek().decrypt(token[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        log.warning("decrypt: token failed integrity check — returning as-is")
        return token


# ── SQLAlchemy column types ──────────────────────────────────────

from sqlalchemy import Text, TypeDecorator  # noqa: E402


class EncryptedText(TypeDecorator):
    """TEXT column transparently AES-encrypted with the DEK."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)


class EncryptedJSON(TypeDecorator):
    """JSON stored as encrypted TEXT. Reads legacy plain-JSON transparently."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt(json.dumps(value, separators=(",", ":"), default=str))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        raw = decrypt(value)
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw


# ── secret bundles (KEK) — connector creds, TOTP, SSO client secret ──

def encrypt_secrets(data: dict) -> str:
    payload = json.dumps(data or {}, separators=(",", ":")).encode()
    return _kek().encrypt(payload).decode()


def decrypt_secrets(token: str | None, *, resolve: bool = False) -> dict:
    """Decrypt a secret bundle. With ``resolve=True`` any value that is a
    ``${provider:locator}`` reference is fetched from its backend — used on the
    runtime path (connector overrides, SSO callback), not for display."""
    if not token:
        return {}
    try:
        data = json.loads(_kek().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError):
        return {}
    return resolve_mapping(data) if resolve else data
