"use client";

import { apiFetch } from "./client";
import type { AnswerResult, QuerySource, StreamEvent } from "@/lib/types";

export interface QueryFilters {
  doc_ids?: number[];
  source?: string;
  filename?: string;
}

function cleanFilters(f?: QueryFilters): QueryFilters | undefined {
  if (!f) return undefined;
  const out: QueryFilters = {};
  if (f.doc_ids && f.doc_ids.length) out.doc_ids = f.doc_ids;
  if (f.source) out.source = f.source;
  if (f.filename) out.filename = f.filename;
  return Object.keys(out).length ? out : undefined;
}

export function ask(question: string, filters?: QueryFilters) {
  return apiFetch<AnswerResult>("/query/ask", {
    method: "POST",
    body: { question, filters: cleanFilters(filters) },
  });
}

export function search(question: string, filters?: QueryFilters) {
  return apiFetch<{ results: QuerySource[] }>("/query/search", {
    method: "POST",
    body: { question, filters: cleanFilters(filters) },
  });
}

export function sendFeedback(query_id: number, helpful: boolean) {
  return apiFetch<{ ok: boolean }>("/query/feedback", {
    method: "POST",
    body: { query_id, helpful },
  });
}

/**
 * Stream an answer over Server-Sent Events. The backend is a POST that returns
 * `text/event-stream` with frames of `data: {json}\n\n`, so EventSource can't be
 * used — we read the body stream and parse frames by hand.
 */
export async function* streamAsk(
  question: string,
  filters?: QueryFilters,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await apiFetch<Response>("/query/ask/stream", {
    method: "POST",
    body: { question, filters: cleanFilters(filters) },
    raw: true,
    signal,
  });
  const reader = res.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() || "";
    for (const line of lines) {
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        yield JSON.parse(payload) as StreamEvent;
      } catch {
        // ignore malformed frame
      }
    }
  }
}
