"""Google Drive connector — mass-ingest a folder (per-workspace).

Auth: a Google Cloud **service account** key (JSON). The target folder must be
shared with the service-account email, or domain-wide delegation must be set up
and an impersonation user supplied. Access tokens are minted with `google-auth`
and refreshed automatically, so a connector keeps working indefinitely.

Native Google Docs/Sheets/Slides are exported to Office formats; regular files
(PDF, DOCX, …) are downloaded as-is. Everything funnels into the same ingestion
pipeline as manual uploads.

Legacy: `GDRIVE_ACCESS_TOKEN` / `GDRIVE_FOLDER_ID` in .env are still recognised
by `is_configured()` for the deprecated global connector shown on the UI.
"""
from __future__ import annotations

import json
import threading
from typing import Any

import httpx

from ...config import get_settings
from .base import ConnectorConfigError

DRIVE_API = "https://www.googleapis.com/drive/v3"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

EXPORT_MAP = {
    "application/vnd.google-apps.document":
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet":
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation":
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}

_FOLDER_MIME = "application/vnd.google-apps.folder"

_creds_cache: dict[str, Any] = {}
_lock = threading.Lock()


def is_configured() -> bool:
    """Legacy env-based global connector (deprecated; per-tenant is preferred)."""
    s = get_settings()
    return bool(s.gdrive_access_token and s.gdrive_folder_id)


def _bearer(config: dict, secrets: dict) -> str:
    """Return a valid OAuth access token for the service account."""
    raw = (secrets or {}).get("service_account_json", "")
    if not raw:
        # Fall back to a legacy pasted access token if present.
        if (config or {}).get("_legacy_access_token"):
            return config["_legacy_access_token"]
        raise ConnectorConfigError("Google Drive connector needs a service account JSON key.")

    cache_key = json.dumps(
        {"j": raw[:64] + str(len(raw)), "s": (config or {}).get("impersonate_email", "")},
        sort_keys=True,
    )
    with _lock:
        creds = _creds_cache.get(cache_key)
        if creds is None:
            try:
                from google.oauth2 import service_account  # noqa: PLC0415
            except ImportError as e:  # pragma: no cover
                raise ConnectorConfigError("google-auth is not installed on the server.") from e
            try:
                info = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ConnectorConfigError(f"Service account key is not valid JSON: {e}") from e
            try:
                creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
            except (ValueError, KeyError) as e:
                raise ConnectorConfigError(f"Service account key is missing required fields: {e}") from e
            subject = (config or {}).get("impersonate_email")
            if subject:
                creds = creds.with_subject(subject)
            _creds_cache[cache_key] = creds

        if not creds.valid:
            from google.auth.transport.requests import Request  # noqa: PLC0415
            try:
                creds.refresh(Request())
            except Exception as e:  # noqa: BLE001 — google surfaces many auth error types
                raise ConnectorConfigError(f"Could not obtain a Google access token: {e}") from e
        return creds.token


def validate(config: dict, secrets: dict) -> None:
    if not (config or {}).get("folder_id"):
        raise ConnectorConfigError("Google Drive connector needs a folder_id.")
    _bearer(config, secrets)  # forces credential parse + token mint


def list_files(config: dict, secrets: dict) -> list[dict]:
    """Recursively list every file under folder_id. Returns Drive file dicts."""
    folder_id = (config or {}).get("folder_id")
    if not folder_id:
        raise ConnectorConfigError("Google Drive connector needs a folder_id.")
    headers = {"Authorization": f"Bearer {_bearer(config, secrets)}"}
    files: list[dict] = []
    stack = [folder_id]
    seen: set[str] = set()
    with httpx.Client(timeout=60) as client:
        while stack:
            parent = stack.pop()
            if parent in seen:
                continue
            seen.add(parent)
            page_token = None
            while True:
                params = {
                    "q": f"'{parent}' in parents and trashed=false",
                    "fields": "nextPageToken, files(id, name, mimeType, size)",
                    "pageSize": 200,
                }
                if page_token:
                    params["pageToken"] = page_token
                r = client.get(f"{DRIVE_API}/files", headers=headers, params=params)
                r.raise_for_status()
                data = r.json()
                for f in data.get("files", []):
                    if f.get("mimeType") == _FOLDER_MIME:
                        stack.append(f["id"])
                    else:
                        files.append(f)
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
    return files


def download_file(file: dict, config: dict, secrets: dict) -> tuple[str, bytes]:
    """Returns (filename, content). Google-native files are exported."""
    headers = {"Authorization": f"Bearer {_bearer(config, secrets)}"}
    mime = file.get("mimeType", "")
    with httpx.Client(timeout=120) as client:
        if mime in EXPORT_MAP:
            export_mime, ext = EXPORT_MAP[mime]
            r = client.get(f"{DRIVE_API}/files/{file['id']}/export",
                           headers=headers, params={"mimeType": export_mime})
            r.raise_for_status()
            return file["name"] + ext, r.content
        r = client.get(f"{DRIVE_API}/files/{file['id']}",
                       headers=headers, params={"alt": "media"})
        r.raise_for_status()
        return file["name"], r.content
