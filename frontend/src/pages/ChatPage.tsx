import { FormEvent, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiPost, getToken } from "../lib/api";

interface ConversationMessage {
  id: number;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  message_metadata: Record<string, string>;
  created_at: string;
}

interface Conversation {
  id: number;
  title: string;
  status: string;
  metadata: { github_url?: string; paper_url?: string };
  messages: ConversationMessage[];
}

interface ChatMessage {
  role: "user" | "agent";
  content: string;
  type?: "text" | "status";
}

export default function ChatPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
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
          role: msg.role === "user" ? "user" : "agent",
          content: msg.content,
          type: msg.role === "system" ? "status" : "text",
        }))
    );
    setLogs(
      conversation.messages
        .filter((msg) => msg.role === "tool")
        .map((msg) => `[${msg.message_metadata.tool_name || "tool"}] ${msg.content}`)
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
          setLogs((prev) => [
            ...prev,
            `[${payload.tool_name}] ${payload.message?.content || ""}`,
          ]);
        }
        if (payload.type === "message" && payload.message) {
          const msg = payload.message as ConversationMessage;
          if (msg.role !== "tool") {
            setMessages((prev) => [
              ...prev,
              {
                role: msg.role === "user" ? "user" : "agent",
                content: msg.content,
                type: msg.role === "system" ? "status" : "text",
              },
            ]);
          }
        }
      } catch {
        setLogs((prev) => [...prev, event.data]);
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
  }, [taskId, conversation?.status]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, logs]);

  const stopMutation = useMutation({
    mutationFn: () => apiFetch(`/api/conversations/${taskId}/stop`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversation", taskId] }),
  });

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!input.trim() || !taskId) return;
    const content = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content }]);
    try {
      await apiPost(`/api/conversations/${taskId}/messages`, { content });
      queryClient.invalidateQueries({ queryKey: ["conversation", taskId] });
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "agent", content: "发送失败，请稍后重试。", type: "status" },
      ]);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as FormEvent);
    }
  }

  const isRunning = conversation?.status === "running";

  return (
    <div className="flex-1 flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-8 py-8">
        <div className="max-w-4xl mx-auto space-y-6">
          {messages.map((msg, i) => (
            <MessageBubble key={`${msg.role}-${i}-${msg.content.slice(0, 12)}`} message={msg} />
          ))}

          {logs.length > 0 && (
            <div className="flex gap-4">
              <AgentAvatar />
              <div className="flex flex-col gap-2 w-full max-w-[85%]">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-bold text-slate-400">
                    Tool Events
                  </span>
                  {isRunning && <PulsingDot />}
                </div>
                <div className="border border-slate-200 rounded-xl bg-slate-50 p-4 font-mono text-[12px] max-h-[300px] overflow-y-auto">
                  {logs.map((line, i) => (
                    <div key={`${i}-${line}`} className="text-slate-500">
                      {line}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {isRunning && (
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
              placeholder={isRunning ? "任务执行中，完成后可继续对话..." : "继续输入你的问题或调整要求..."}
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

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex gap-4 justify-end">
        <div className="bg-slate-100 px-5 py-3.5 rounded-2xl rounded-tr-sm text-[14px] text-slate-700 max-w-[80%] whitespace-pre-wrap">
          {message.content}
        </div>
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
            message.content
          )}
        </div>
      </div>
    </div>
  );
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

function PulsingDot() {
  return (
    <span className="flex h-2 w-2 relative">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-orange-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-orange-500" />
    </span>
  );
}
