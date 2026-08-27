"""SharePoint / OneDrive connector via Microsoft Graph (client credentials).

Configuration (.env):
  MSGRAPH_TENANT_ID, MSGRAPH_CLIENT_ID, MSGRAPH_CLIENT_SECRET
      — an Azure AD app registration with Sites.Read.All application permission
  MSGRAPH_SITE_ID   — the SharePoint site to sync
  MSGRAPH_DRIVE_ID  — optional; defaults to the site's default document library

Recursively walks the document library and feeds every supported file into
the standard ingestion pipeline.
"""
from __future__ import annotations

import httpx

from ...config import get_settings
from ..parsers import SUPPORTED_EXTENSIONS

GRAPH = "https://graph.microsoft.com/v1.0"


def is_configured() -> bool:
    s = get_settings()
    return bool(s.msgraph_tenant_id and s.msgraph_client_id
                and s.msgraph_client_secret and s.msgraph_site_id)


def _token(client: httpx.Client) -> str:
    s = get_settings()
    r = client.post(
        f"https://login.microsoftonline.com/{s.msgraph_tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": s.msgraph_client_id,
            "client_secret": s.msgraph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _drive_id(client: httpx.Client, headers: dict) -> str:
    s = get_settings()
    if s.msgraph_drive_id:
        return s.msgraph_drive_id
    r = client.get(f"{GRAPH}/sites/{s.msgraph_site_id}/drive", headers=headers)
    r.raise_for_status()
    return r.json()["id"]


def list_files() -> list[dict]:
    """Recursively lists supported files. Returns [{id, name, size, drive_id}]."""
    with httpx.Client(timeout=60) as client:
        headers = {"Authorization": f"Bearer {_token(client)}"}
        drive_id = _drive_id(client, headers)
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
                        ext = item["name"].rsplit(".", 1)[-1].lower()
                        if ext in SUPPORTED_EXTENSIONS:
                            out.append({"id": item["id"], "name": item["name"],
                                        "size": item.get("size", 0),
                                        "drive_id": drive_id})
                url = data.get("@odata.nextLink")
        return out


def download_file(file: dict) -> tuple[str, bytes]:
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        headers = {"Authorization": f"Bearer {_token(client)}"}
        r = client.get(f"{GRAPH}/drives/{file['drive_id']}/items/{file['id']}/content",
                       headers=headers)
        r.raise_for_status()
        return file["name"], r.content
