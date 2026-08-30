"""External document-source connectors.

Each provider module exposes the same interface:
    validate(config: dict, secrets: dict) -> None        # raise on bad creds
    list_files(config: dict, secrets: dict) -> list[dict]
    download_file(file: dict, config: dict, secrets: dict) -> tuple[str, bytes]
"""
from __future__ import annotations

from . import gdrive, sharepoint
from .base import ConnectorConfigError

PROVIDERS = {
    "gdrive": gdrive,
    "sharepoint": sharepoint,
}

__all__ = ["PROVIDERS", "gdrive", "sharepoint", "ConnectorConfigError"]
