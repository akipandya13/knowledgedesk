# Ingestion pipeline

## What it does

Turns an uploaded or connector-fetched file into searchable, cited knowledge.

## How it works

Runs off the request thread (FastAPI background task). Stages:

1. **Parse** — `parse_file()` extracts `(page_number, text)` tuples per format
   ([File-format support](11-file-format-support.md)). Empty extraction (e.g. a
   scanned PDF with no OCR) fails the document with a clear error.
2. **Chunk** — `chunk_pages()` splits page text into ~`CHUNK_SIZE`-char chunks
   with `CHUNK_OVERLAP`, preferring paragraph then sentence boundaries.
   Pathological long lines (tables, minified text) are hard-split. Chunks under
   30 chars are dropped.
3. **Resolve model config** — the tenant's effective embedding provider/model
   (profile + overrides + connector). See [Model profiles](25-model-profiles.md).
4. **Embed** — `embeddings.embed_texts()` vectorises every chunk (local
   SentenceTransformer, or a remote embedding connector).
5. **Upsert to Qdrant** — points carry `doc_id`, `filename`, `page`,
   `chunk_index`, `text`, plus `source`, `department`, `confidentiality`, `tags`,
   `embedding_model`, and the ownership keys `scope` / `owner_user_id`.
6. **Finalise** — the `Document` row records `pages`, `chunk_count`,
   `embedding_provider/model`, and `status=ready`. First successful ingest also
   snapshots the workspace's embedding identity (see [Embedding lock](28-embedding-lock.md)).

Any stage failure sets `status=failed` and stores the error on the row.

## Interfaces

Not called directly — triggered by [upload](07-document-upload.md),
[ZIP ingest](08-bulk-zip-ingestion.md), [connector sync](15-connector-sync-and-history.md),
and [demo seed](38-demo-seed.md).

## Configuration

`CHUNK_SIZE` (1100), `CHUNK_OVERLAP` (180), `EMBEDDING_PROVIDER`,
`EMBEDDING_MODEL`, `EMBEDDING_BATCH_SIZE`, `QDRANT_URL`.

## Source

- [`backend/app/services/ingestion.py`](../../backend/app/services/ingestion.py)
- [`backend/app/services/parsers.py`](../../backend/app/services/parsers.py)
- [`backend/app/services/chunking.py`](../../backend/app/services/chunking.py)
- [`backend/app/services/embeddings.py`](../../backend/app/services/embeddings.py)
- [`backend/app/services/vectorstore.py`](../../backend/app/services/vectorstore.py)

## Related

[Document lifecycle & de-duplication](12-document-lifecycle.md) ·
[Retrieval & reranking](20-retrieval-and-reranking.md)
