"""SharePoint / OneDrive connector via Microsoft Graph (client credentials).

Per-workspace config (stored on a DataConnector):
  config:  tenant_id, client_id, site_id, drive_id (optional)
  secret:  client_secret
Needs an Azure AD app registration with the Sites.Read.All application
permission (admin-consented). Access tokens are minted per request.

Legacy: MSGRAPH_* in .env are still recognised by `is_configured()` for the
deprecated global connector shown on the UI.
"""
from __future__ import annotations

import httpx

from ...config import get_settings
from ..parsers import SUPPORTED_EXTENSIONS
from .base import ConnectorConfigError

GRAPH = "https://graph.microsoft.com/v1.0"


def is_configured() -> bool:
    """Legacy env-based global connector (deprecated; per-tenant is preferred)."""
    s = get_settings()
    return bool(s.msgraph_tenant_id and s.msgraph_client_id
                and s.msgraph_client_secret and s.msgraph_site_id)


def _require(config: dict, secrets: dict) -> None:
    missing = [k for k in ("tenant_id", "client_id", "site_id") if not (config or {}).get(k)]
    if missing:
        raise ConnectorConfigError(f"SharePoint connector is missing: {', '.join(missing)}")
    if not (secrets or {}).get("client_secret"):
        raise ConnectorConfigError("SharePoint connector needs a client_secret.")


def _token(client: httpx.Client, config: dict, secrets: dict) -> str:
    r = client.post(
        f"https://login.microsoftonline.com/{config['tenant_id']}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": config["client_id"],
            "client_secret": secrets["client_secret"],
            "scope": "https://graph.microsoft.com/.default",
        },
    )
    if r.status_code >= 400:
        raise ConnectorConfigError(f"Microsoft Graph token request failed: {r.status_code} {r.text[:300]}")
    return r.json()["access_token"]


def _drive_id(client: httpx.Client, headers: dict, config: dict) -> str:
    if config.get("drive_id"):
        return config["drive_id"]
    r = client.get(f"{GRAPH}/sites/{config['site_id']}/drive", headers=headers)
    r.raise_for_status()
    return r.json()["id"]


def validate(config: dict, secrets: dict) -> None:
    _require(config, secrets)
    with httpx.Client(timeout=30) as client:
        headers = {"Authorization": f"Bearer {_token(client, config, secrets)}"}
        _drive_id(client, headers, config)


def list_files(config: dict, secrets: dict) -> list[dict]:
    """Recursively lists supported files. Returns [{id, name, size, drive_id}]."""
    _require(config, secrets)
    with httpx.Client(timeout=60) as client:
        headers = {"Authorization": f"Bearer {_token(client, config, secrets)}"}
        drive_id = _drive_id(client, headers, config)
        out: list[dict] = []
        stack = ["root"]
        while stack:
            item_id = stack.pop()
            url = f"{GRAPH}/drives/{drive_id}/items/{item_id}/children"
            while url:
                r = client.get(url, headers=headers)
                r.raise_for_status()
                data = r.json()
                for item in data.get("value", []):
                    if "folder" in item:
                        stack.append(item["id"])
                    elif "file" in item:
                        ext = item["name"].rsplit(".", 1)[-1].lower() if "." in item["name"] else ""
                        if ext in SUPPORTED_EXTENSIONS:
                            out.append({"id": item["id"], "name": item["name"],
                                        "size": item.get("size", 0),
                                        "drive_id": drive_id})
                url = data.get("@odata.nextLink")
        return out


def download_file(file: dict, config: dict, secrets: dict) -> tuple[str, bytes]:
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        headers = {"Authorization": f"Bearer {_token(client, config, secrets)}"}
        r = client.get(f"{GRAPH}/drives/{file['drive_id']}/items/{file['id']}/content",
                       headers=headers)
        r.raise_for_status()
        return file["name"], r.content
