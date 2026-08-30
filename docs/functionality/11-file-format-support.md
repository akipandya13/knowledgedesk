# File-format support

## What it does

Extracts plain text (with page numbers where the format has them) from common
office and text files, using deliberately dependency-light parsers.

## Supported formats

| Extension(s) | Parser | Notes |
|--------------|--------|-------|
| `pdf` | `pypdf` | one entry per page with extractable text; scanned PDFs with no text layer fail (no OCR) |
| `docx` | `python-docx` | paragraphs + table rows flattened as `a | b | c`; single page |
| `pptx` | `python-pptx` | one entry per slide, text frames concatenated |
| `xlsx` | `openpyxl` | one entry per sheet, rows joined as `a | b | c`, prefixed `Sheet: <name>` |
| `html`, `htm` | `BeautifulSoup` | `script/style/nav/footer` stripped, text extracted |
| `json` | stdlib | pretty-printed back to text |
| `txt`, `md`, `markdown`, `csv`, `log` | stdlib | decoded as UTF-8 (`errors="replace"`) |

Anything else is rejected at upload with `Unsupported type .<ext>`.

## Interfaces

Enforced by `validate_file()` during [upload](07-document-upload.md),
[ZIP ingest](08-bulk-zip-ingestion.md) and [connector sync](15-connector-sync-and-history.md).
The canonical set is `SUPPORTED_EXTENSIONS`.

## Configuration

`MAX_UPLOAD_MB` — size ceiling per file.

## Source

- [`backend/app/services/parsers.py`](../../backend/app/services/parsers.py)
- [`backend/app/services/ingestion.py`](../../backend/app/services/ingestion.py) — `validate_file`

## Related

[Ingestion pipeline](10-ingestion-pipeline.md) · [Document upload](07-document-upload.md)
