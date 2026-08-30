"""Shared types for document-source connectors."""
from __future__ import annotations


class ConnectorConfigError(RuntimeError):
    """Raised when a connector's config or credentials are missing/invalid."""
