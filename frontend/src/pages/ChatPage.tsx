import { useEffect, useRef, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MarkdownContent } from "../components/MarkdownContent";
import { apiFetch, apiPost, getToken } from "../lib/api";

interface ConversationMessage {
  id: number;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  message_metadata: Record<string, unknown>;
  created_at: string;
}

interface Conversation {
  id: number;
  title: string;
  status: string;
  updated_at: string;
  metadata: {
    github_url?: string;
    paper_url?: string;
    workflow_state?: string;
    pending_user_input?: {
      question: string;
      options?: string[];
      step?: string;
      tool_name?: string;
      tool_input?: Record<string, unknown>;
    } | null;
  };
  messages: ConversationMessage[];
}

interface ChatMessage {
  id: number | string;
  role: "user" | "agent";
  content: string;
  created_at: string;
  type?: "text" | "status";
}

export default function ChatPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [copiedMessageId, setCopiedMessageId] = useState<number | string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { data: conversation } = useQuery({
    queryKey: ["conversation", taskId],
    queryFn: () => apiFetch<Conversation>(`/api/conversations/${taskId}`),
    enabled: !!taskId,
    refetchInterval: 3000,
  });

  useEffect(() => {
    if (!conversation) return;
    setMessages(
      conversation.messages
        .filter((msg) => msg.role !== "tool")
        .map((msg) => ({
          id: msg.id,
          role: msg.role === "user" ? "user" : "agent",
          content: msg.content,
          created_at: msg.created_at,
          type: msg.role === "system" ? "status" : "text",
        }))
    );
  }, [conversation]);

  useEffect(() => {
    if (!taskId || !conversation) return;
    if (!["active", "running"].includes(conversation.status)) return;
    const token = getToken();
    if (!token) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/api/conversations/${taskId}/stream?token=${token}`
    );
    let closedByClient = false;
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "tool") {
          queryClient.invalidateQueries({ queryKey: ["conversation", taskId] });
        }
        if (payload.type === "message" && payload.message) {
          const msg = payload.message as ConversationMessage;
          if (msg.role !== "tool") {
            setMessages((prev) => [
              ...prev,
              {
                id: msg.id,
                role: msg.role === "user" ? "user" : "agent",
                content: msg.content,
                created_at: msg.created_at,
                type: msg.role === "system" ? "status" : "text",
              },
            ]);
          }
        }
        if (payload.type === "ask_user" || payload.type === "status" || payload.type === "memory_compacted") {
          queryClient.invalidateQueries({ queryKey: ["conversation", taskId] });
        }
      } catch {
        queryClient.invalidateQueries({ queryKey: ["conversation", taskId] });
      }
    };
    ws.onerror = () => {
      if (!closedByClient) {
        ws.close();
      }
    };
    return () => {
      closedByClient = true;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close(1000, "component unmounted");
      }
    };
  }, [taskId, conversation?.status, conversation?.updated_at, queryClient]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const stopMutation = useMutation({
    mutationFn: () => apiFetch(`/api/conversations/${taskId}/stop`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversation", taskId] }),
  });

  async function submitMessage(content: string) {
    if (!content.trim() || !taskId) return;
    const trimmed = content.trim();
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: `pending-${Date.now()}`, role: "user", content: trimmed, created_at: new Date().toISOString() },
    ]);
    try {
      await apiPost(`/api/conversations/${taskId}/messages`, { content: trimmed });
      queryClient.invalidateQueries({ queryKey: ["conversation", taskId] });
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "agent",
          content: "发送失败，请稍后重试。",
          created_at: new Date().toISOString(),
          type: "status",
        },
      ]);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    await submitMessage(input);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as FormEvent);
    }
  }

  const isRunning = conversation?.status === "running";
  const pendingInput = conversation?.metadata?.pending_user_input;
  const isWaitingForUser =
    conversation?.metadata?.workflow_state === "waiting_for_user" && !!pendingInput;

  async function copyMessage(message: ChatMessage) {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessageId(message.id);
      window.setTimeout(() => setCopiedMessageId(null), 1200);
    } catch {
      setCopiedMessageId(null);
    }
  }

  return (
    <div className="flex-1 flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-8 py-8">
        <div className="max-w-4xl mx-auto space-y-6">
          {messages.map((msg, i) => (
            <MessageBubble
              key={`${msg.id}-${msg.role}-${i}`}
              message={msg}
              copied={copiedMessageId === msg.id}
              onCopy={() => copyMessage(msg)}
            />
          ))}

          {isWaitingForUser && pendingInput && (
            <div className="flex gap-4">
              <AgentAvatar />
              <div className="w-full max-w-[85%] rounded-xl border border-amber-200 bg-amber-50 p-4">
                <div className="text-[12px] font-bold uppercase text-amber-700">
                  等待你确认
                </div>
                {pendingInput.tool_name && (
                  <div className="mt-1 text-[11px] text-amber-600">
                    工具：{pendingInput.tool_name}
                  </div>
                )}
                <div className="mt-2 text-[14px] leading-relaxed text-slate-700">
                  {pendingInput.question}
                </div>
                {pendingInput.options && pendingInput.options.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {pendingInput.options.map((option) => (
                      <button
                        key={option}
                        type="button"
                        onClick={() => submitMessage(option)}
                        className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-[13px] text-slate-700 hover:bg-amber-100"
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {(isRunning || isWaitingForUser) && (
            <div className="flex justify-center">
              <button
                onClick={() => stopMutation.mutate()}
                disabled={stopMutation.isPending}
                className="px-4 py-2 rounded-xl border border-red-200 bg-red-50 text-red-600 text-[13px] font-medium hover:bg-red-100 transition-colors"
              >
                停止执行
              </button>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="shrink-0 p-3 bg-white border-t border-slate-100">
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto">
          <div className="w-full flex items-end gap-3 rounded-xl border border-slate-200 bg-slate-50 focus-within:border-slate-300 focus-within:bg-white px-4 py-3 transition-colors">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isRunning
                  ? "任务执行中，完成后可继续对话..."
                  : isWaitingForUser
                    ? "请直接回复确认，或点击上方选项..."
                    : "继续输入你的问题或调整要求..."
              }
              disabled={isRunning}
              rows={1}
              className="flex-1 text-[14px] text-slate-700 placeholder-slate-300 bg-transparent resize-none leading-relaxed disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={isRunning || !input.trim()}
              className="w-[32px] h-[32px] flex items-center justify-center rounded-full bg-slate-800 hover:bg-slate-700 disabled:bg-slate-300 text-white transition-colors shrink-0"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function MessageBubble({
  message,
  copied,
  onCopy,
}: {
  message: ChatMessage;
  copied: boolean;
  onCopy: () => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex flex-col items-end gap-1.5">
        <div className="bg-slate-100 px-5 py-3.5 rounded-2xl rounded-tr-sm text-[14px] text-slate-700 max-w-[80%] whitespace-pre-wrap">
          {message.content}
        </div>
        <MessageMeta message={message} copied={copied} onCopy={onCopy} align="right" />
      </div>
    );
  }

  return (
    <div className="flex gap-4">
      <AgentAvatar />
      <div className="flex flex-col gap-2 max-w-[85%]">
        <span className="text-[13px] font-medium text-slate-800">LOBSTER Agent</span>
        <div className="border border-slate-200 rounded-xl bg-white p-4 text-[14px] text-slate-600 leading-relaxed whitespace-pre-wrap">
          {message.type === "status" ? (
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
              <span>{message.content}</span>
            </div>
          ) : (
            <MarkdownContent content={message.content} />
          )}
        </div>
        <MessageMeta message={message} copied={copied} onCopy={onCopy} align="left" />
      </div>
    </div>
  );
}

function MessageMeta({
  message,
  copied,
  onCopy,
  align,
}: {
  message: ChatMessage;
  copied: boolean;
  onCopy: () => void;
  align: "left" | "right";
}) {
  return (
    <div
      className={`flex items-center gap-2 text-[11px] text-slate-400 ${
        align === "right" ? "justify-end pr-1" : "justify-start pl-1"
      }`}
    >
      <span>{formatMessageTime(message.created_at)}</span>
      <button
        type="button"
        onClick={onCopy}
        title={copied ? "已复制" : "复制"}
        aria-label={copied ? "已复制" : "复制消息"}
        className="h-5 w-5 inline-flex items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
      >
        {copied ? <CheckIcon /> : <CopyIcon />}
      </button>
    </div>
  );
}

function formatMessageTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function AgentAvatar() {
  return (
    <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center shrink-0 mt-1">
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    </div>
  );
}

function CopyIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M8 8h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2Z"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="m5 13 4 4L19 7" />
    </svg>
  );
}
