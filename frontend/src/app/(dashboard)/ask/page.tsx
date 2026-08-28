"use client";

import { useRef, useState } from "react";
import { sendFeedback, streamAsk } from "@/lib/api/query";
import { ApiError } from "@/lib/api/client";
import type { QuerySource } from "@/lib/types";
import { PageHeader } from "@/components/ui";
import { IconSend } from "@/components/icons";

interface ChatMsg {
  role: "user" | "ai";
  text: string;
  sources: QuerySource[];
  confidence: number;
  queryId: number | null;
  mode: string;
  statusNote: string;
  streaming: boolean;
}

const STARTER_QUESTIONS = [
  "What is our PTO / leave policy?",
  "How do I submit an expense report?",
  "What is the security incident escalation path?",
  "Summarise the latest onboarding checklist.",
];

export default function AskPage() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [feedbackDone, setFeedbackDone] = useState<Record<number, boolean>>({});
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollToEnd = () =>
    requestAnimationFrame(() => scrollRef.current?.scrollIntoView({ behavior: "smooth" }));

  async function run(question: string) {
    if (!question.trim() || busy) return;
    setBusy(true);
    setInput("");
    setMessages((m) => [
      ...m,
      { role: "user", text: question, sources: [], confidence: 0, queryId: null, mode: "", statusNote: "", streaming: false },
      { role: "ai", text: "", sources: [], confidence: 0, queryId: null, mode: "", statusNote: "", streaming: true },
    ]);
    scrollToEnd();

    const patchAi = (patch: Partial<ChatMsg>) =>
      setMessages((m) => {
        const copy = [...m];
        for (let i = copy.length - 1; i >= 0; i--) {
          if (copy[i].role === "ai") {
            copy[i] = { ...copy[i], ...patch };
            break;
          }
        }
        return copy;
      });

    try {
      for await (const evt of streamAsk(question)) {
        if (evt.type === "meta") {
          patchAi({ sources: evt.sources || [], confidence: evt.confidence || 0, mode: evt.mode });
        } else if (evt.type === "token") {
          const chunk = evt.text;
          setMessages((m) => {
            const copy = [...m];
            for (let i = copy.length - 1; i >= 0; i--) {
              if (copy[i].role === "ai") {
                copy[i] = { ...copy[i], text: copy[i].text + chunk };
                break;
              }
            }
            return copy;
          });
          scrollToEnd();
        } else if (evt.type === "status") {
          patchAi({ statusNote: evt.message, mode: evt.mode });
        } else if (evt.type === "error") {
          patchAi({ text: `⚠️ ${evt.message}`, streaming: false });
        } else if (evt.type === "done") {
          patchAi({ queryId: evt.query_id, streaming: false });
        }
      }
      patchAi({ streaming: false });
    } catch (err) {
      patchAi({
        text: `⚠️ ${err instanceof ApiError ? err.detail : "Request failed"}`,
        streaming: false,
      });
    } finally {
      setBusy(false);
      scrollToEnd();
    }
  }

  async function vote(queryId: number, helpful: boolean) {
    try {
      await sendFeedback(queryId, helpful);
      setFeedbackDone((f) => ({ ...f, [queryId]: true }));
    } catch {
      /* ignore */
    }
  }

  return (
    <>
      <PageHeader
        title="Ask"
        subtitle="Ask a question and get a grounded answer with citations from your workspace documents."
      />

      {messages.length === 0 && (
        <div className="chips">
          {STARTER_QUESTIONS.map((s) => (
            <button key={s} className="chip" onClick={() => run(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="chat-area">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role === "user" ? "msg-user" : "msg-ai"}`}>
            <div className="msg-label">{m.role === "user" ? "YOU" : "KNOWLEDGEDESK"}</div>
            <div className={`msg-body${m.mode === "not_found" ? " not-found" : ""}`}>
              {m.statusNote && (
                <div className="notice amber" style={{ marginBottom: 10 }}>
                  Generation fallback: {m.statusNote}
                </div>
              )}
              {m.streaming && !m.text ? (
                <span className="typing-dots">
                  <span />
                  <span />
                  <span />
                </span>
              ) : (
                m.text
              )}

              {!m.streaming && m.sources.length > 0 && (
                <div className="sources">
                  {m.sources.map((s, idx) => (
                    <SourceChip key={idx} index={idx} source={s} />
                  ))}
                </div>
              )}

              {!m.streaming && m.confidence > 0 && (
                <div className="confidence">
                  Confidence: <span>{Math.round(m.confidence * 100)}%</span>
                </div>
              )}

              {!m.streaming && m.queryId != null && (
                <div className="feedback-row">
                  {feedbackDone[m.queryId] ? (
                    <span>Thanks for the feedback.</span>
                  ) : (
                    <>
                      Was this helpful?
                      <button className="fb-btn" onClick={() => vote(m.queryId!, true)}>
                        👍
                      </button>
                      <button className="fb-btn" onClick={() => vote(m.queryId!, false)}>
                        👎
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={scrollRef} />
      </div>

      <form
        className="ask-bar"
        onSubmit={(e) => {
          e.preventDefault();
          run(input);
        }}
      >
        <textarea
          value={input}
          placeholder="Ask about a policy, process, or document…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              run(input);
            }
          }}
        />
        <button className="btn" type="submit" disabled={busy || !input.trim()}>
          <IconSend /> {busy ? "Thinking…" : "Ask"}
        </button>
      </form>
    </>
  );
}

function SourceChip({ index, source }: { index: number; source: QuerySource }) {
  const [open, setOpen] = useState<boolean>(false);
  return (
    <>
      <button className="source-chip" onClick={() => setOpen((v) => !v)}>
        [{index + 1}] {source.filename}
        {source.page ? ` · p.${source.page}` : ""}
      </button>
      <div className={`source-panel${open ? " open" : ""}`}>{source.snippet}</div>
    </>
  );
}
