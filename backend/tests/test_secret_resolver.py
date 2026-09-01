"""Pluggable secret resolution: providers, references, selectors, caching,
and integration with the encryption KEK + stored connector secrets."""
from __future__ import annotations

import json

import pytest

from app import crypto, secret_resolver as sr
from app.secret_resolver import SecretError, resolve_mapping, resolve_secret


@pytest.fixture(autouse=True)
def _clean():
    sr.clear_cache()
    yield
    sr.clear_cache()
    sr.PROVIDERS.pop("fake", None)


# ── literals & basics ──────────────────────────────────────────

def test_literal_passthrough():
    assert resolve_secret("just-a-value") == "just-a-value"
    assert resolve_secret(None) is None
    assert resolve_secret("") == ""
    assert not sr.is_reference("plain")
    assert sr.is_reference("${env:X}")


def test_env_provider(monkeypatch):
    monkeypatch.setenv("KD_TEST_SECRET", "s3cr3t")
    assert resolve_secret("${env:KD_TEST_SECRET}") == "s3cr3t"


def test_missing_reference_raises_and_fallback_works():
    with pytest.raises(SecretError):
        resolve_secret("${env:KD_DEFINITELY_MISSING}")
    assert resolve_secret("${env:KD_DEFINITELY_MISSING|use-this}") == "use-this"


def test_file_provider(tmp_path):
    f = tmp_path / "pw"
    f.write_text("  from-a-file\n")
    assert resolve_secret(f"${{file:{f}}}") == "from-a-file"
    assert resolve_secret("${file:/no/such/path|fallback}") == "fallback"


def test_literal_provider_and_non_reference_values():
    assert resolve_secret("${literal:actual-password-value}") == "actual-password-value"
    # a value that merely contains "${" but is not a single valid reference is
    # returned untouched (no accidental resolution)
    assert resolve_secret("pre${env:X}post") == "pre${env:X}post"


def test_unknown_provider():
    with pytest.raises(SecretError):
        resolve_secret("${nope:x}")


# ── selector + caching (custom provider) ──────────────────────

def test_json_selector_and_cache():
    calls = {"n": 0}

    def _fake(locator):
        calls["n"] += 1
        return json.dumps({"user": "u", "password": f"pw-for-{locator}"})

    sr.PROVIDERS["fake"] = _fake
    assert resolve_secret("${fake:acme#password}") == "pw-for-acme"
    assert resolve_secret("${fake:acme#user}") == "u"          # different ref → 2nd call
    assert resolve_secret("${fake:acme#password}") == "pw-for-acme"  # cached
    assert calls["n"] == 2


def test_resolve_mapping():
    import os
    os.environ["KD_MAP_A"] = "AA"
    try:
        out = resolve_mapping({"a": "${env:KD_MAP_A}", "b": "plain", "c": "${env:KD_MAP_A|x}"})
        assert out == {"a": "AA", "b": "plain", "c": "AA"}
    finally:
        os.environ.pop("KD_MAP_A", None)


# ── integration ──────────────────────────────────────────────

def test_stored_connector_secret_can_be_a_reference(monkeypatch):
    monkeypatch.setenv("KD_CONN_KEY", "aws-key-value")
    token = crypto.encrypt_secrets({"aws_secret_access_key": "${env:KD_CONN_KEY}",
                                    "region": "us-east-1"})
    # display path: reference kept as-is
    assert crypto.decrypt_secrets(token)["aws_secret_access_key"] == "${env:KD_CONN_KEY}"
    # runtime path: resolved
    resolved = crypto.decrypt_secrets(token, resolve=True)
    assert resolved["aws_secret_access_key"] == "aws-key-value"
    assert resolved["region"] == "us-east-1"


def test_kek_can_be_sourced_from_a_reference(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setenv("KD_KEK_REF", Fernet.generate_key().decode())
    monkeypatch.setattr(s, "data_dir", str(tmp_path))
    monkeypatch.setattr(s, "kd_secret_key", "${env:KD_KEK_REF}")
    crypto.reset_cache()
    sr.clear_cache()
    try:
        assert crypto.decrypt(crypto.encrypt("hello")) == "hello"
        assert crypto.decrypt_secrets(crypto.encrypt_secrets({"x": 1})) == {"x": 1}
    finally:
        crypto.reset_cache()
        sr.clear_cache()


def test_available_providers_lists_builtins():
    ps = sr.available_providers()
    assert {"env", "file", "literal"} <= set(ps)
