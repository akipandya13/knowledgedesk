"""Google Drive connector — mass-ingest a folder.

Configuration (.env):
  GDRIVE_ACCESS_TOKEN  OAuth2 access token with drive.readonly scope
                       (quickest path: https://developers.google.com/oauthplayground)
  GDRIVE_FOLDER_ID     the folder to sync (from the folder URL)

Native Google Docs/Sheets/Slides are exported to Office formats; regular
files (PDF, DOCX, …) are downloaded as-is. Everything funnels into the
same ingestion pipeline as manual uploads.
"""
from __future__ import annotations

import httpx

from ...config import get_settings

DRIVE_API = "https://www.googleapis.com/drive/v3"

EXPORT_MAP = {
    "application/vnd.google-apps.document":
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet":
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation":
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}


def is_configured() -> bool:
    s = get_settings()
    return bool(s.gdrive_access_token and s.gdrive_folder_id)


def list_files() -> list[dict]:
    s = get_settings()
    headers = {"Authorization": f"Bearer {s.gdrive_access_token}"}
    files, page_token = [], None
    with httpx.Client(timeout=60) as client:
        while True:
            params = {
                "q": f"'{s.gdrive_folder_id}' in parents and trashed=false",
                "fields": "nextPageToken, files(id, name, mimeType, size)",
                "pageSize": 200,
            }
            if page_token:
                params["pageToken"] = page_token
            r = client.get(f"{DRIVE_API}/files", headers=headers, params=params)
            r.raise_for_status()
            data = r.json()
            files.extend(data.get("files", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return files


def download_file(file: dict) -> tuple[str, bytes]:
    """Returns (filename, content). Google-native files are exported."""
    s = get_settings()
    headers = {"Authorization": f"Bearer {s.gdrive_access_token}"}
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
