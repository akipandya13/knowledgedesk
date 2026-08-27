"""Sentence-aware chunking.

Splits page text into chunks of ~CHUNK_SIZE characters with CHUNK_OVERLAP,
preferring paragraph and sentence boundaries so chunks read naturally —
which directly improves both retrieval and LLM answer quality.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from ..config import get_settings


@dataclass
class Chunk:
    text: str
    page: int
    index: int  # position within the document


_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


def _split_sentences(text: str) -> List[str]:
    parts: List[str] = []
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if not para:
            continue
        parts.extend(s.strip() for s in _SENTENCE_END.split(para) if s.strip())
    return parts


def chunk_pages(pages: List[Tuple[int, str]],
                chunk_size: int | None = None,
                overlap: int | None = None) -> List[Chunk]:
    s = get_settings()
    chunk_size = chunk_size or s.chunk_size
    overlap = overlap if overlap is not None else s.chunk_overlap

    chunks: List[Chunk] = []
    idx = 0
    for page_no, text in pages:
        sentences = _split_sentences(text)
        if not sentences:
            continue
        buf: List[str] = []
        size = 0
        for sent in sentences:
            # Hard-split pathological sentences (tables, minified text)
            while len(sent) > chunk_size:
                head, sent = sent[:chunk_size], sent[chunk_size - overlap:]
                chunks.append(Chunk(head.strip(), page_no, idx)); idx += 1
            if size + len(sent) > chunk_size and buf:
                chunks.append(Chunk(" ".join(buf).strip(), page_no, idx)); idx += 1
                # carry overlap: keep trailing sentences up to `overlap` chars
                carried, csize = [], 0
                for prev in reversed(buf):
                    if csize + len(prev) > overlap:
                        break
                    carried.insert(0, prev); csize += len(prev)
                buf, size = carried, csize
            buf.append(sent)
            size += len(sent) + 1
        if buf:
            chunks.append(Chunk(" ".join(buf).strip(), page_no, idx)); idx += 1
    return [c for c in chunks if len(c.text) > 30]
