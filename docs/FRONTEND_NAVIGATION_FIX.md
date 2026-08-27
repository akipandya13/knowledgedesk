# Frontend Navigation Fix

This package includes a hardened frontend navigation implementation for the single-file KnowledgeDesk UI.

## What was fixed

- Sidebar page changes no longer depend on fragile inline `onclick` behavior alone.
- Navigation items now use explicit event listeners, keyboard activation, `data-page` metadata, and `aria-current` state.
- Page switching now updates both the `.active` class and explicit `display` styles, so the previous page cannot remain visible due to stale CSS or proxy caching.
- Routes now prefer hash navigation (`#ask`, `#documents`, `#change-pw`, etc.) to avoid accidental server round trips in Docker demos and reverse-proxy deployments.
- Existing direct paths such as `/ask`, `/documents`, `/insights`, and `/change-password` remain supported through the FastAPI SPA fallback.
- User-dropdown navigation to Change password is handled without event bubbling blocking the page switch.

## Smoke-tested pages

The frontend smoke test validated switching between:

- Ask
- Documents
- Change password
- Users
- Settings
- Header dropdown → Change password

