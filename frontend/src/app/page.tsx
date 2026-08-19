"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { apiRequest } from "@/lib/api";

interface ChatMessage {
  id: string;
  sender: "user" | "assistant" | "system";
  text: string;
  timestamp: string;
  confirmation?: {
    toolName: string;
    summary: string;
    details: Record<string, unknown>;
    status?: "pending" | "approved" | "rejected";
  };
}

interface ChatSession {
  id: string;
  title: string;
  started_at: string;
}

interface BackendChatResponse {
  session_id: string;
  response_text: string;
  intent?: string;
  requires_confirmation: boolean;
  pending_confirmation: boolean;
  confirmation_payload?: {
    tool_name: string;
    tool_args: Record<string, unknown>;
    message: string;
  };
  tool_result?: Record<string, unknown>;
}

export default function ChatDashboardPage() {
  const { user, token, isLoading, logout } = useAuth();
  const router = useRouter();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const fetchUserSessions = async () => {
    try {
      const data = await apiRequest<ChatSession[]>("/chat/sessions");
      setSessions(data);
    } catch (err) {
      console.error("Failed to load sessions:", err);
    }
  };

  useEffect(() => {
    if (!isLoading && !token) {
      router.push("/login");
    } else if (token) {
      let isMounted = true;
      (async () => {
        try {
          const data = await apiRequest<ChatSession[]>("/chat/sessions");
          if (isMounted) setSessions(data);
        } catch (err) {
          console.error("Failed to load sessions:", err);
        }
      })();
      return () => {
        isMounted = false;
      };
    }
  }, [isLoading, token, router]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const loadSessionTurns = async (sid: string) => {
    setSessionId(sid);
    try {
      const turns = await apiRequest<{ id: string; role: string; content: string; created_at: string }[]>(
        `/chat/sessions/${sid}/turns`
      );
      const formattedMsgs: ChatMessage[] = turns.map((t) => ({
        id: t.id,
        sender: t.role === "user" ? "user" : "assistant",
        text: t.content,
        timestamp: t.created_at ? new Date(t.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "",
      }));
      setMessages(formattedMsgs);
    } catch (err) {
      console.error("Failed to load turns:", err);
    }
  };

  const handleSendMessage = async (textToSend?: string, confirmationResponse?: boolean) => {
    const query = textToSend || inputText;
    if (!query.trim() && confirmationResponse === undefined) return;

    if (query.trim()) {
      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        sender: "user",
        text: query,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, userMsg]);
    }

    if (!textToSend) setInputText("");
    setIsTyping(true);

    try {
      const res = await apiRequest<BackendChatResponse>("/chat/message", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId,
          input_text: query || "Confirmation Response",
          confirmation_response: confirmationResponse,
        }),
      });

      if (!sessionId) {
        setSessionId(res.session_id);
        fetchUserSessions();
      }

      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        sender: "assistant",
        text: res.response_text,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        confirmation: res.pending_confirmation && res.confirmation_payload ? {
          toolName: res.confirmation_payload.tool_name,
          summary: res.confirmation_payload.message,
          details: res.confirmation_payload.tool_args,
          status: "pending",
        } : undefined,
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const error = err as Error;
      const errorMsg: ChatMessage = {
        id: crypto.randomUUID(),
        sender: "assistant",
        text: `⚠️ Error: ${error.message || "Failed to process chat message."}`,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleConfirmationAction = (msgId: string, action: "approved" | "rejected") => {
    setMessages((prev) =>
      prev.map((msg) => {
        if (msg.id === msgId && msg.confirmation) {
          return {
            ...msg,
            confirmation: {
              ...msg.confirmation,
              status: action,
            },
          };
        }
        return msg;
      })
    );

    // Call backend with user decision (true = approved, false = rejected)
    handleSendMessage("Proceeding with decision", action === "approved");
  };

  const handleNewChat = () => {
    setSessionId(null);
    setMessages([]);
  };

  const promptSuggestions = [
    "📅 Schedule a team sync meeting tomorrow at 3 PM",
    "⏰ Set a reminder to submit code review by 5 PM",
    "🔍 Search web for latest LangGraph features",
    "✉️ Draft an update email to the project team",
  ];

  if (isLoading || !token) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950 p-4">
        <div className="flex items-center space-x-3 text-slate-400">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
          <span className="text-sm font-medium">Authenticating session...</span>
        </div>
      </main>
    );
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-slate-950 text-slate-100">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? "w-64" : "w-16"} flex flex-col border-r border-slate-800/80 bg-slate-900/60 backdrop-blur-xl transition-all duration-300`}>
        {/* Sidebar Header */}
        <div className="flex h-16 items-center justify-between px-4 border-b border-slate-800/80">
          {sidebarOpen ? (
            <div className="flex items-center space-x-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-500 shadow-md shadow-indigo-500/20">
                <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                </svg>
              </div>
              <span className="font-bold text-white tracking-wide">Alex AI</span>
            </div>
          ) : (
            <div className="mx-auto flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-500 text-white">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
            </div>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={sidebarOpen ? "M11 19l-7-7 7-7m8 14l-7-7 7-7" : "M13 5l7 7-7 7M5 5l7 7-7 7"} />
            </svg>
          </button>
        </div>

        {/* New Chat Button */}
        <div className="p-3">
          <button
            onClick={handleNewChat}
            className={`flex w-full items-center justify-center space-x-2 rounded-xl bg-gradient-to-r from-indigo-500 to-purple-600 ${sidebarOpen ? "px-4" : "px-2"} py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 hover:from-indigo-600 hover:to-purple-700 transition-all`}
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            {sidebarOpen && <span>New Chat</span>}
          </button>
        </div>

        {/* Past Sessions & Tools Status */}
        {sidebarOpen && (
          <div className="flex-1 overflow-y-auto px-3 py-2 space-y-4">
            {sessions.length > 0 && (
              <div>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 px-2">Recent Chats</span>
                <div className="mt-2 space-y-1">
                  {sessions.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => loadSessionTurns(s.id)}
                      className={`flex w-full items-center space-x-2 rounded-lg px-2.5 py-2 text-xs transition-colors ${
                        sessionId === s.id ? "bg-indigo-600/20 text-indigo-300 font-semibold border border-indigo-500/30" : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                      }`}
                    >
                      <svg className="h-3.5 w-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                      </svg>
                      <span className="truncate text-left">{s.title}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 px-2">FastMCP Tools</span>
              <div className="mt-2 space-y-1 text-xs">
                {[
                  { name: "calendar-mcp", color: "bg-emerald-400" },
                  { name: "contacts-mcp", color: "bg-emerald-400" },
                  { name: "reminders-mcp", color: "bg-emerald-400" },
                  { name: "search-rag-mcp", color: "bg-emerald-400" },
                  { name: "email-messaging-mcp", color: "bg-emerald-400" },
                ].map((tool) => (
                  <div key={tool.name} className="flex items-center justify-between rounded-lg px-2.5 py-1.5 text-slate-300 hover:bg-slate-800/60">
                    <span className="truncate">{tool.name}</span>
                    <span className={`h-2 w-2 rounded-full ${tool.color}`} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* User Profile Footer */}
        <div className="mt-auto border-t border-slate-800/80 p-3">
          {sidebarOpen ? (
            <div className="flex items-center justify-between">
              <div className="flex flex-col truncate">
                <span className="text-xs font-semibold text-white truncate">{user?.name}</span>
                <span className="text-[11px] text-slate-400 truncate">{user?.email}</span>
              </div>
              <button
                onClick={logout}
                title="Sign Out"
                className="rounded-lg p-1.5 text-slate-400 hover:bg-red-500/20 hover:text-red-400 transition-colors"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </button>
            </div>
          ) : (
            <button
              onClick={logout}
              title="Sign Out"
              className="mx-auto flex h-9 w-9 items-center justify-center rounded-xl text-slate-400 hover:bg-red-500/20 hover:text-red-400"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
            </button>
          )}
        </div>
      </aside>

      {/* Main Chat Content */}
      <main className="flex flex-1 flex-col overflow-hidden bg-slate-950">
        {/* Top Header */}
        <header className="flex h-16 items-center justify-between border-b border-slate-800/80 bg-slate-950/80 px-6 backdrop-blur-xl">
          <div className="flex items-center space-x-3">
            <h2 className="text-base font-bold text-white">Alex AI Assistant</h2>
            <span className="flex items-center space-x-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-400">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              LangGraph Connected
            </span>
            <span className="hidden sm:flex items-center space-x-1 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-0.5 text-xs font-medium text-indigo-300">
              ⚡ CI/CD Verified
            </span>
          </div>
        </header>

        {/* Scrollable Message List */}
        <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
          {messages.length === 0 ? (
            <div className="my-auto flex flex-col items-center justify-center pt-16 text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-tr from-indigo-500 to-purple-500 p-0.5 shadow-xl shadow-indigo-500/25 mb-6">
                <div className="flex h-full w-full items-center justify-center rounded-[14px] bg-slate-950">
                  <svg className="h-8 w-8 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                  </svg>
                </div>
              </div>
              <h3 className="text-2xl font-bold text-white">How can I help you today, {user?.name}?</h3>
              <p className="mt-2 text-sm text-slate-400 max-w-md">
                I can schedule events, set reminders, search the web, manage contacts, and execute multi-tool workflows via LangGraph.
              </p>

              {/* Prompt Suggestions */}
              <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-3 w-full max-w-2xl">
                {promptSuggestions.map((suggestion, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleSendMessage(suggestion.replace(/^[^\s]+\s/, ""))}
                    className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-left text-xs text-slate-300 transition-all hover:border-indigo-500/50 hover:bg-slate-900 hover:text-white"
                  >
                    <span>{suggestion}</span>
                    <svg className="h-4 w-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                    </svg>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex w-full ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
              >
                <div className={`flex max-w-2xl items-start space-x-3 ${msg.sender === "user" ? "flex-row-reverse space-x-reverse" : "flex-row"}`}>
                  {/* Avatar */}
                  <div className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl text-xs font-bold ${
                    msg.sender === "user"
                      ? "bg-gradient-to-tr from-purple-500 to-indigo-500 text-white"
                      : "bg-slate-800 text-indigo-400 border border-slate-700"
                  }`}>
                    {msg.sender === "user" ? user?.name?.[0]?.toUpperCase() || "U" : "A"}
                  </div>

                  {/* Bubble Content */}
                  <div className="space-y-3">
                    <div className={`rounded-2xl px-5 py-3.5 text-sm leading-relaxed ${
                      msg.sender === "user"
                        ? "bg-indigo-600 text-white shadow-lg shadow-indigo-600/20"
                        : "bg-slate-900 border border-slate-800 text-slate-200"
                    }`}>
                      {renderFormattedMessage(msg.text)}
                    </div>

                    {/* Interactive Confirmation Card */}
                    {msg.confirmation && (
                      <div className="rounded-2xl border border-indigo-500/40 bg-slate-900/90 p-4 shadow-xl backdrop-blur-xl space-y-3">
                        <div className="flex items-center justify-between text-xs font-semibold text-indigo-400">
                          <span className="uppercase tracking-wider">Security Confirmation Required</span>
                          <span className="rounded-md bg-indigo-500/10 px-2 py-0.5 border border-indigo-500/20">{msg.confirmation.toolName}</span>
                        </div>
                        <p className="text-sm font-medium text-white">{msg.confirmation.summary}</p>
                        
                        {msg.confirmation.status === "pending" ? (
                          <div className="flex items-center space-x-3 pt-1">
                            <button
                              onClick={() => handleConfirmationAction(msg.id, "approved")}
                              className="rounded-xl bg-emerald-500 px-4 py-2 text-xs font-bold text-slate-950 hover:bg-emerald-400 transition-colors shadow-lg shadow-emerald-500/20"
                            >
                              ✅ Confirm Action
                            </button>
                            <button
                              onClick={() => handleConfirmationAction(msg.id, "rejected")}
                              className="rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-red-500/20 hover:text-red-400 transition-colors"
                            >
                              ❌ Cancel
                            </button>
                          </div>
                        ) : (
                          <div className={`text-xs font-semibold ${msg.confirmation.status === "approved" ? "text-emerald-400" : "text-red-400"}`}>
                            {msg.confirmation.status === "approved" ? "Approved & Executed" : "Cancelled by User"}
                          </div>
                        )}
                      </div>
                    )}

                    {msg.timestamp && <span className="block text-[10px] text-slate-500 px-1">{msg.timestamp}</span>}
                  </div>
                </div>
              </div>
            ))
          )}

          {/* Typing Indicator */}
          {isTyping && (
            <div className="flex items-center space-x-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-800 text-indigo-400 border border-slate-700 font-bold text-xs">
                A
              </div>
              <div className="flex items-center space-x-1.5 rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3 text-slate-400">
                <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400 [animation-delay:-0.3s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400 [animation-delay:-0.15s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400" />
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <footer className="p-4 border-t border-slate-800/80 bg-slate-950/80 backdrop-blur-xl">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendMessage();
            }}
            className="mx-auto max-w-4xl flex items-center space-x-3"
          >
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="Ask Alex to schedule meetings, set reminders, search..."
              className="flex-1 rounded-xl border border-slate-800 bg-slate-900/80 px-4 py-3.5 text-sm text-white placeholder-slate-500 transition-all focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />
            <button
              type="submit"
              disabled={!inputText.trim()}
              className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-r from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25 transition-all hover:from-indigo-600 hover:to-purple-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9-2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </form>
        </footer>
      </main>
    </div>
  );
}

function renderFormattedMessage(text: string) {
  if (!text) return null;

  const lines = text.split("\n");
  const hasTable = lines.some((l) => l.trim().startsWith("|") && l.includes("|"));

  if (hasTable) {
    const nonTableBefore: string[] = [];
    const tableLines: string[] = [];
    const nonTableAfter: string[] = [];
    let state: "before" | "in_table" | "after" = "before";

    for (const line of lines) {
      const isTableLine = line.trim().startsWith("|") && line.includes("|");
      if (isTableLine) {
        state = "in_table";
        tableLines.push(line);
      } else if (state === "before") {
        nonTableBefore.push(line);
      } else {
        nonTableAfter.push(line);
      }
    }

    const validTableRows = tableLines.filter(
      (l) => !l.trim().match(/^\|(?:\s*:?-+:?\s*\|)+$/)
    );

    if (validTableRows.length > 0) {
      const headerRow = validTableRows[0];
      const bodyRows = validTableRows.slice(1);

      const parseCells = (rowStr: string) =>
        rowStr
          .split("|")
          .map((c) => c.trim())
          .filter((c, idx, arr) => idx > 0 && idx < arr.length - 1);

      const headers = parseCells(headerRow);

      return (
        <div className="space-y-4 w-full overflow-x-auto">
          {nonTableBefore.length > 0 && (
            <div className="whitespace-pre-wrap font-medium">{renderInlineFormatting(nonTableBefore.join("\n").trim())}</div>
          )}

          <div className="my-3 overflow-hidden rounded-xl border border-indigo-500/40 bg-slate-950/90 shadow-2xl backdrop-blur-md">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-indigo-600/30 text-indigo-200 border-b border-indigo-500/30 font-bold uppercase tracking-wider">
                  {headers.map((h, i) => (
                    <th key={i} className="px-4 py-3 border-r border-indigo-500/20 last:border-r-0">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 text-slate-200">
                {bodyRows.map((rowStr, rIdx) => {
                  const cells = parseCells(rowStr);
                  return (
                    <tr
                      key={rIdx}
                      className="hover:bg-indigo-500/10 transition-colors odd:bg-slate-900/50 even:bg-slate-900/90"
                    >
                      {cells.map((cell, cIdx) => (
                        <td key={cIdx} className="px-4 py-3 border-r border-slate-800 last:border-r-0 font-normal">
                          {renderInlineFormatting(cell)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {nonTableAfter.length > 0 && (
            <div className="whitespace-pre-wrap">{renderInlineFormatting(nonTableAfter.join("\n").trim())}</div>
          )}
        </div>
      );
    }
  }

  return (
    <div className="whitespace-pre-wrap leading-relaxed space-y-1">
      {renderInlineFormatting(text)}
    </div>
  );
}

function renderInlineFormatting(str: string) {
  if (!str) return null;

  const parts = str.split(/(\[[^\]]+\]\([^)]+\))/g);

  return parts.map((part, i) => {
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      const [, label, url] = linkMatch;
      return (
        <a
          key={i}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-indigo-400 underline font-semibold hover:text-indigo-300 transition-colors"
        >
          {label}
        </a>
      );
    }
    return <span key={i}>{part}</span>;
  });
}
