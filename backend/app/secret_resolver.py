"""Pluggable secret resolution — one seam for every 'open' subsystem.

Any secret the app consumes (the KEK, JWT secret, SMTP password, observability
sink tokens, and the stored model/data-connector + SSO credentials) may be a
literal **or** a reference:

    ${provider:locator}              ${env:SMTP_PASSWORD}
    ${provider:locator#key}          ${vault:secret/data/kd#smtp_password}
    ${provider:locator|fallback}     ${env:SMTP_PASSWORD|}      (empty fallback)

Built-in providers — always available, zero dependencies:

    env      os.environ[locator]
    file     contents of the file at `locator`  (Docker/K8s `/run/secrets/...`)
    literal  the locator verbatim (escape hatch for values containing "${")

Optional providers — enabled when their SDK is importable:

    vault    HashiCorp Vault KV v2   (hvac; VAULT_ADDR / VAULT_TOKEN)
    awssm    AWS Secrets Manager     (boto3; default credential chain)
    gcpsm    GCP Secret Manager      (google-cloud-secret-manager)
    azkv     Azure Key Vault         (azure-keyvault-secrets + azure-identity)

Register your own:  PROVIDERS["mine"] = lambda locator: my_backend.get(locator)

Resolution is cached for SECRETS_CACHE_TTL seconds so hot paths don't hammer the
backend. A reference that cannot be resolved (and has no `|fallback`) raises
SecretError — fail closed.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

from .config import get_settings

log = logging.getLogger("knowledgedesk.secrets")

_REF = re.compile(r"^\$\{([a-z0-9_]+):([^}]*)\}$", re.IGNORECASE)


class SecretError(RuntimeError):
    pass


# ── built-in providers ────────────────────────────────────────────

def _p_env(locator: str) -> str | None:
    return os.environ.get(locator)


def _p_file(locator: str) -> str | None:
    try:
        with open(locator, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _p_literal(locator: str) -> str:
    return locator


# ── optional providers (import-guarded) ──────────────────────────

def _p_vault(locator: str) -> str | None:
    try:
        import hvac  # noqa: PLC0415
    except ImportError:
        raise SecretError("provider 'vault' needs the 'hvac' package")
    c = hvac.Client(url=os.environ.get("VAULT_ADDR"),
                    token=os.environ.get("VAULT_TOKEN"))
    mount, _, path = locator.partition("/")
    # accept both "secret/data/kd" and "kd" (default mount 'secret')
    if not path:
        mount, path = "secret", locator
    resp = c.secrets.kv.v2.read_secret_version(path=path, mount_point=mount)
    return json.dumps(resp["data"]["data"])         # dict → JSON, selector picks the key


def _p_awssm(locator: str) -> str | None:
    import boto3  # boto3 is already a dependency
    v = boto3.client("secretsmanager").get_secret_value(SecretId=locator)
    return v.get("SecretString")


def _p_gcpsm(locator: str) -> str | None:
    try:
        from google.cloud import secretmanager  # noqa: PLC0415
    except ImportError:
        raise SecretError("provider 'gcpsm' needs 'google-cloud-secret-manager'")
    name = locator if "/versions/" in locator else f"{locator}/versions/latest"
    client = secretmanager.SecretManagerServiceClient()
    return client.access_secret_version(name=name).payload.data.decode()


def _p_azkv(locator: str) -> str | None:
    try:
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415
        from azure.keyvault.secrets import SecretClient  # noqa: PLC0415
    except ImportError:
        raise SecretError("provider 'azkv' needs 'azure-keyvault-secrets' + 'azure-identity'")
    # locator: https://<vault>.vault.azure.net/secrets/<name>[/<version>]
    parts = locator.rstrip("/").split("/secrets/")
    vault_url, rest = parts[0], parts[1]
    name, _, version = rest.partition("/")
    client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
    return client.get_secret(name, version or None).value


PROVIDERS: dict[str, callable] = {
    "env": _p_env,
    "file": _p_file,
    "literal": _p_literal,
    "vault": _p_vault,
    "awssm": _p_awssm,
    "gcpsm": _p_gcpsm,
    "azkv": _p_azkv,
}

#: providers whose SDK is present and can be used right now
BUILTIN = {"env", "file", "literal"}


def available_providers() -> list[str]:
    ok = list(BUILTIN)
    for name, spec in (("vault", "hvac"), ("awssm", "boto3"),
                       ("gcpsm", "google.cloud.secretmanager"),
                       ("azkv", "azure.keyvault.secrets")):
        try:
            __import__(spec.split(".")[0])
            ok.append(name)
        except Exception:
            pass
    return sorted(set(ok) | (set(PROVIDERS) - {"vault", "awssm", "gcpsm", "azkv"}))


# ── cache + resolution ───────────────────────────────────────────

_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def _cached(key: str, produce) -> str:
    ttl = int(getattr(get_settings(), "secrets_cache_ttl", 300))
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = produce()
    with _lock:
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def is_reference(value) -> bool:
    return isinstance(value, str) and bool(_REF.match(value.strip()))


def resolve_secret(value: str | None) -> str | None:
    """Return a literal unchanged; resolve a ${provider:locator[#key][|default]}
    reference through its provider (cached)."""
    if not is_reference(value):
        return value
    m = _REF.match(value.strip())
    provider, body = m.group(1).lower(), m.group(2)

    default = None
    if "|" in body:
        body, default = body.rsplit("|", 1)
    locator, _, selector = body.partition("#")

    fn = PROVIDERS.get(provider)
    if fn is None:
        raise SecretError(f"unknown secret provider '{provider}'")

    def _produce() -> str:
        try:
            raw = fn(locator)
        except SecretError:
            raise
        except Exception as exc:  # noqa: BLE001
            if default is not None:
                log.warning("secret %s:%s failed (%s) — using fallback", provider, locator, exc)
                return default
            raise SecretError(f"secret {provider}:{locator} failed: {exc}") from exc
        if raw is None:
            if default is not None:
                return default
            raise SecretError(f"secret {provider}:{locator} not found")
        if selector:
            try:
                raw = json.loads(raw)[selector]
            except Exception as exc:  # noqa: BLE001
                raise SecretError(f"secret {provider}:{locator}#{selector}: {exc}") from exc
        return str(raw)

    return _cached(value.strip(), _produce)


def resolve_mapping(data: dict) -> dict:
    """Resolve every ${...} value in a flat dict (stored connector secrets)."""
    return {k: (resolve_secret(v) if is_reference(v) else v) for k, v in (data or {}).items()}
