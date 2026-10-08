import { useState, useRef, useEffect } from "react";
import { MessageCircle, X, Send, Loader2, Sparkles } from "lucide-react";
import { api } from "@/lib/apiClient";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

// A lightweight Q&A chat over this month's dashboard data — see
// dashboard_chat_service.py. Deliberately kept simple for v1: no
// persisted history across page reloads, capped conversation length sent
// to the backend each turn, and a cheap model (Haiku/gpt-4o-mini) used
// server-side regardless of whichever model the heavier executive summary
// is configured with, to keep this cheap to run.
export function DashboardChatBubble() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, sending]);

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setError("");
    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setSending(true);
    try {
      const res = await api.fetchRaw("/ai-analytics/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          // Only the last few turns go back to the backend each time —
          // keeps token usage from growing unbounded across a long chat.
          history: nextMessages.slice(-6, -1),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const d = await res.json();
      setMessages((prev) => [...prev, { role: "assistant", content: d.reply }]);
    } catch (e: any) {
      setError(e.message || "Something went wrong — try again.");
    }
    setSending(false);
  };

  return (
    <>
      {open && (
        <div className="fixed bottom-24 right-6 z-50 w-[360px] max-w-[calc(100vw-2rem)] h-[480px] max-h-[70vh] rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] shadow-2xl flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)] bg-white/5">
            <div className="flex items-center gap-2">
              <Sparkles size={16} className="text-[var(--accent-blue)]" />
              <span className="text-sm font-bold text-white">Ask about your business</span>
            </div>
            <button onClick={() => setOpen(false)} className="text-[var(--text-muted)] hover:text-white">
              <X size={18} />
            </button>
          </div>

          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.length === 0 && (
              <p className="text-xs text-[var(--text-muted)] text-center py-6">
                Ask anything about this month's revenue, targets, branches, or team leaders — e.g. "How is Kerala performing?" or "Who's the top team leader this month?"
              </p>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-xs leading-relaxed ${
                    m.role === "user"
                      ? "bg-[var(--accent-blue)] text-white"
                      : "bg-white/5 border border-[var(--border-subtle)] text-[var(--text-secondary)]"
                  }`}
                >
                  {m.content}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="rounded-2xl px-3.5 py-2 bg-white/5 border border-[var(--border-subtle)] text-[var(--text-muted)]">
                  <Loader2 size={14} className="animate-spin" />
                </div>
              </div>
            )}
            {error && <p className="text-xs text-rose-400 text-center">{error}</p>}
          </div>

          <div className="flex items-center gap-2 p-3 border-t border-[var(--border-subtle)]">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") send(); }}
              placeholder="Ask a question..."
              className="flex-1 px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]"
            />
            <button
              onClick={send}
              disabled={sending || !input.trim()}
              className="p-2 rounded-xl bg-[var(--accent-blue)] text-white disabled:opacity-40"
            >
              <Send size={14} />
            </button>
          </div>
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full bg-[var(--accent-blue)] text-white shadow-lg flex items-center justify-center hover:scale-105 transition-transform"
        title="Ask about your business"
      >
        {open ? <X size={22} /> : <MessageCircle size={22} />}
      </button>
    </>
  );
}
