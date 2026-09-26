import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useState } from "react";
import {
  MessageSquare, Send, Search, UserCheck, Bot, ArrowLeft,
} from "lucide-react";
import type { IGConversation, IGMessage } from "./types";

export default function Conversations() {
  const [selectedConv, setSelectedConv] = useState<number | null>(null);
  const [filter, setFilter] = useState("active");
  const queryClient = useQueryClient();

  const { data: conversations, isLoading } = useQuery({
    queryKey: ["ig-conversations", filter],
    queryFn: () => api.get<IGConversation[]>(`/instagram/conversations?status=${filter}`),
  });

  const { data: messages } = useQuery({
    queryKey: ["ig-messages", selectedConv],
    queryFn: () => api.get<IGMessage[]>(`/instagram/conversations/${selectedConv}`),
    enabled: !!selectedConv,
  });

  const selected = conversations?.find((c) => c.id === selectedConv);

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <MessageSquare className="text-pink-400" size={22} />
            Instagram Conversations
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            View and manage AI-powered DM conversations
          </p>
        </div>

        <div className="flex gap-4">
          {/* Conversation List */}
          <div className={`${selectedConv ? "hidden lg:block" : "w-full"} lg:w-96 space-y-3`}>
            {/* Filter Tabs */}
            <div className="flex gap-2">
              {["active", "needs_attention", "archived"].map((s) => (
                <button
                  key={s}
                  onClick={() => { setFilter(s); setSelectedConv(null); }}
                  className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors ${
                    filter === s
                      ? s === "needs_attention"
                        ? "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                        : "bg-pink-500/20 text-pink-400 border border-pink-500/30"
                      : "bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border-subtle)] hover:text-white"
                  }`}
                >
                  {s === "needs_attention" ? "Needs Attention" : s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>

            {isLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-20 rounded-xl bg-[var(--bg-card)] animate-pulse" />
                ))}
              </div>
            ) : conversations && conversations.length > 0 ? (
              conversations.map((conv) => (
                <button
                  key={conv.id}
                  onClick={() => setSelectedConv(conv.id)}
                  className={`w-full text-left p-4 rounded-xl border transition-all ${
                    selectedConv === conv.id
                      ? "bg-pink-500/10 border-pink-500/30"
                      : "bg-[var(--bg-card)] border-[var(--border-subtle)] hover:border-pink-500/20"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-semibold text-white">
                      {conv.customer_name || conv.ig_user_id}
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)]">
                      {conv.message_count} msgs
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-[var(--text-muted)]">
                      @{conv.ig_user_id}
                    </span>
                    <div className="flex gap-1">
                      {conv.lead_id && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">Lead</span>
                      )}
                      {conv.assignee_name && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">{conv.assignee_name}</span>
                      )}
                    </div>
                  </div>
                </button>
              ))
            ) : (
              <div className="text-center py-10 text-xs text-[var(--text-muted)]">
                No {filter} conversations
              </div>
            )}
          </div>

          {/* Chat View */}
          <div className={`${selectedConv ? "w-full" : "hidden lg:block"} lg:flex-1`}>
            {selectedConv && messages && selected ? (
              <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] h-[calc(100vh-200px)] flex flex-col">
                {/* Header */}
                <div className="p-4 border-b border-[var(--border-subtle)] flex items-center gap-3">
                  <button
                    onClick={() => setSelectedConv(null)}
                    className="lg:hidden p-1 rounded-lg hover:bg-white/5"
                  >
                    <ArrowLeft size={18} className="text-white" />
                  </button>
                  <div className="w-9 h-9 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
                    <span className="text-xs font-bold text-white">
                      {(selected.customer_name || selected.ig_user_id).charAt(0).toUpperCase()}
                    </span>
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-white">
                      {selected.customer_name || selected.ig_user_id}
                    </p>
                    <p className="text-[10px] text-[var(--text-muted)]">
                      @{selected.ig_user_id}
                    </p>
                  </div>
                  {selected.assignee_name && (
                    <span className="text-xs px-3 py-1 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
                      <UserCheck size={12} className="inline mr-1" />
                      {selected.assignee_name}
                    </span>
                  )}
                </div>

                {/* Messages */}
                <div className="flex-1 overflow-y-auto p-4 space-y-3">
                  {messages.map((msg) => (
                    <div
                      key={msg.id}
                      className={`flex ${msg.direction === "outbound" ? "justify-end" : "justify-start"}`}
                    >
                      <div
                        className={`max-w-[70%] px-4 py-2.5 rounded-2xl text-sm ${
                          msg.direction === "outbound"
                            ? "bg-pink-500/20 text-white rounded-br-md"
                            : "bg-[var(--bg-primary)] text-white border border-[var(--border-subtle)] rounded-bl-md"
                        }`}
                      >
                        <p>{msg.content}</p>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-[10px] opacity-50">
                            {msg.created_at ? new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}
                          </span>
                          {msg.ai_provider && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 flex items-center gap-1">
                              <Bot size={10} />
                              {msg.ai_provider}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-[var(--border-subtle)] bg-[var(--bg-card)] h-[calc(100vh-200px)] flex items-center justify-center">
                <div className="text-center">
                  <MessageSquare size={40} className="mx-auto text-pink-400 mb-3 opacity-30" />
                  <p className="text-sm font-semibold text-white">Select a conversation</p>
                  <p className="text-xs text-[var(--text-muted)] mt-1">Choose from the list to view messages</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </ErrorBoundary>
  );
}
