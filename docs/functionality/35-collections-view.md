# Collections view

## What it does

A read-only reorganisation of the document list by **department**,
**confidentiality** and **tags** — a browsable map of the knowledge base.

## How it works

- Client-side only: `/collections` fetches `GET /api/documents` (respecting
  [document scope](09-document-scope.md) — you see company-wide docs plus your
  own) and groups them:
  - by `department` (blank → "Unfiled"), largest group first, with a
    `ready/total` badge per group;
  - a **Tags** cloud with per-tag counts;
  - each group shows file, confidentiality badge, status, chunk count.

## Interfaces

UI: `/collections`. No dedicated endpoint — derived from `/api/documents`.

## Permissions

`document.read` (member and up).

## Source

- [`frontend/src/app/(dashboard)/collections/page.tsx`](../../frontend/src/app/(dashboard)/collections/page.tsx)

## Related

[Document upload](07-document-upload.md) (sets department/confidentiality/tags) ·
[Document lifecycle](12-document-lifecycle.md)
