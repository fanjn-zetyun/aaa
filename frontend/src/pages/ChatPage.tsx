import { useEffect, useRef, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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

interface StreamPayload {
  seq?: number;
  type: string;
  run_id?: string | null;
  timestamp?: string;
  delta?: string;
  stage?: string;
  content?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  ok?: boolean;
  error?: string;
  message?: ConversationMessage;
}

interface TimelineEvent {
  id: number | string;
  title: string;
  content?: string;
  created_at: string;
  status: "running" | "done" | "error" | "info";
  tool_name?: string;
}

interface ChatMessage {
  id: number | string;
  role: "user" | "agent";
  content: string;
  created_at: string;
  type?: "text" | "status";
  events?: TimelineEvent[];
  streaming?: boolean;
  run_id?: string | null;
}

export default function ChatPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [copiedMessageId, setCopiedMessageId] = useState<number | string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastSeqRef = useRef(0);
  const activeAgentMessageIdRef = useRef<number | string | null>(null);

  const { data: conversation } = useQuery({
    queryKey: ["conversation", taskId],
    queryFn: () => apiFetch<Conversation>(`/api/conversations/${taskId}`),
    enabled: !!taskId,
    refetchInterval: 3000,
  });

  useEffect(() => {
    lastSeqRef.current = 0;
    activeAgentMessageIdRef.current = null;
    setMessages([]);
  }, [taskId]);

  useEffect(() => {
    if (!conversation) return;
    activeAgentMessageIdRef.current = null;
    setMessages(buildChatMessages(conversation.messages));
  }, [conversation?.id]);

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
        const payload = JSON.parse(event.data) as StreamPayload;
        if (typeof payload.seq === "number") {
          if (payload.seq <= lastSeqRef.current) return;
          lastSeqRef.current = payload.seq;
        }
        handleStreamPayload(payload);
        if (["ask_user", "status", "memory_compacted", "assistant_completed"].includes(payload.type)) {
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
  }, [taskId, conversation?.id, conversation?.status, queryClient]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleStreamPayload(payload: StreamPayload) {
    if (payload.type === "assistant_started") {
      setMessages((prev) => ensureActiveAgentMessage(prev, payload).messages);
      return;
    }
    if (payload.type === "assistant_delta" && payload.delta) {
      setMessages((prev) => {
        const { messages: next, id } = ensureActiveAgentMessage(prev, payload);
        activeAgentMessageIdRef.current = id;
        return next.map((msg) =>
          msg.id === id ? { ...msg, content: `${msg.content}${payload.delta}` } : msg
        );
      });
      return;
    }
    if (payload.type === "assistant_completed" && payload.message) {
      completeAssistantMessage(payload.message, payload.run_id);
      return;
    }
    if (payload.type === "progress") {
      appendTimelineEvent(payload, {
        id: `progress-${payload.seq ?? Date.now()}`,
        title: progressTitle(payload.stage),
        content: payload.content,
        created_at: payload.timestamp || new Date().toISOString(),
        status: "info",
      });
      return;
    }
    if (payload.type === "tool_started" && payload.tool_name) {
      appendTimelineEvent(payload, {
        id: `tool-start-${payload.seq ?? Date.now()}`,
        title: payload.tool_name,
        content: formatToolInput(payload.tool_input),
        created_at: payload.timestamp || new Date().toISOString(),
        status: "running",
        tool_name: payload.tool_name,
      });
      return;
    }
    if (payload.type === "tool_completed" && payload.message) {
      const toolName = payload.tool_name || String(payload.message.message_metadata.tool_name || "tool");
      appendTimelineEvent(payload, {
        id: `tool-${payload.message.id}`,
        title: toolName,
        content: payload.message.content,
        created_at: payload.message.created_at,
        status: payload.ok === false ? "error" : "done",
        tool_name: toolName,
      });
      return;
    }
    if (payload.type === "tool_error" && payload.tool_name) {
      appendTimelineEvent(payload, {
        id: `tool-error-${payload.seq ?? Date.now()}`,
        title: payload.tool_name,
        content: payload.error,
        created_at: payload.timestamp || new Date().toISOString(),
        status: "error",
        tool_name: payload.tool_name,
      });
      return;
    }
    if (payload.type === "message" && payload.message) {
      appendPersistedMessage(payload.message);
    }
  }

  function ensureActiveAgentMessage(prev: ChatMessage[], payload: StreamPayload) {
    const runId = payload.run_id ?? null;
    const activeId = activeAgentMessageIdRef.current;
    if (activeId && prev.some((msg) => msg.id === activeId)) {
      return { messages: prev, id: activeId };
    }
    const existing = runId
      ? [...prev].reverse().find((msg) => msg.role === "agent" && msg.run_id === runId && msg.streaming)
      : undefined;
    if (existing) {
      activeAgentMessageIdRef.current = existing.id;
      return { messages: prev, id: existing.id };
    }
    const id = `stream-${runId || payload.seq || Date.now()}`;
    activeAgentMessageIdRef.current = id;
    return {
      id,
      messages: [
        ...prev,
        {
          id,
          role: "agent" as const,
          content: "",
          created_at: payload.timestamp || new Date().toISOString(),
          type: "text" as const,
          events: [],
          streaming: true,
          run_id: runId,
        },
      ],
    };
  }

  function appendTimelineEvent(payload: StreamPayload, timelineEvent: TimelineEvent) {
    setMessages((prev) => {
      const { messages: next, id } = ensureActiveAgentMessage(prev, payload);
      activeAgentMessageIdRef.current = id;
      return next.map((msg) => {
        if (msg.id !== id) return msg;
        const events = [...(msg.events || [])];
        const existingIndex = events.findIndex((item) => item.id === timelineEvent.id);
        if (existingIndex >= 0) {
          events[existingIndex] = { ...events[existingIndex], ...timelineEvent };
          return { ...msg, events };
        }
        const pendingIndex =
          timelineEvent.status !== "running" && timelineEvent.tool_name
            ? findLastIndex(
                events,
                (item) => item.tool_name === timelineEvent.tool_name && item.status === "running"
              )
            : -1;
        if (pendingIndex >= 0) {
          events[pendingIndex] = { ...events[pendingIndex], ...timelineEvent };
        } else {
          events.push(timelineEvent);
        }
        return { ...msg, events };
      });
    });
  }

  function completeAssistantMessage(message: ConversationMessage, runId?: string | null) {
    setMessages((prev) => {
      if (prev.some((item) => item.id === message.id)) return prev;
      const activeId = activeAgentMessageIdRef.current;
      const activeIndex = findLastIndex(
        prev,
        (item) =>
          item.role === "agent" &&
          (item.id === activeId || (!!runId && item.run_id === runId) || item.streaming === true)
      );
      if (activeIndex < 0) {
        return [...prev, chatMessageFromConversation(message)];
      }
      const next = [...prev];
      next[activeIndex] = {
        ...next[activeIndex],
        id: message.id,
        content: message.content,
        created_at: message.created_at,
        streaming: false,
        type: "text",
        run_id: runId ?? next[activeIndex].run_id,
      };
      return next;
    });
    activeAgentMessageIdRef.current = null;
  }

  function appendPersistedMessage(message: ConversationMessage) {
    if (message.role === "tool") {
      appendTimelineEvent(
        { type: "tool_completed", message, tool_name: String(message.message_metadata.tool_name || "tool") },
        toolEventFromMessage(message)
      );
      return;
    }
    setMessages((prev) => {
      if (prev.some((item) => item.id === message.id)) return prev;
      const pendingUserIndex =
        message.role === "user"
          ? prev.findIndex(
              (item) =>
                item.role === "user" &&
                String(item.id).startsWith("pending-") &&
                item.content === message.content
            )
          : -1;
      if (pendingUserIndex >= 0) {
        const next = [...prev];
        next[pendingUserIndex] = chatMessageFromConversation(message);
        return next;
      }
      return [...prev, chatMessageFromConversation(message)];
    });
  }

  async function submitMessage(content: string) {
    if (!content.trim() || !taskId) return;
    const trimmed = content.trim();
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: `pending-${Date.now()}`, role: "user", content: trimmed, created_at: new Date().toISOString() },
    ]);
    try {
      const detail = await apiPost<Conversation>(`/api/conversations/${taskId}/messages`, {
        content: trimmed,
      });
      setMessages((prev) => mergePersistedChatMessages(prev, detail.messages));
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
          {messages.map((msg) => (
            <MessageBubble
              key={`${msg.id}-${msg.role}`}
              message={msg}
              copied={copiedMessageId === msg.id}
              onCopy={() => copyMessage(msg)}
            />
          ))}

          {isWaitingForUser && pendingInput && (
            <div className="flex gap-4">
              <AgentAvatar />
              <div className="w-full max-w-[85%] rounded-xl border border-amber-200 bg-amber-50 p-4">
                <div className="text-ui-meta font-bold uppercase text-amber-700">
                  等待你确认
                </div>
                {pendingInput.tool_name && (
                  <div className="mt-1 text-ui-meta text-amber-600">
                    工具：{pendingInput.tool_name}
                  </div>
                )}
                <div className="mt-2 text-chat-body leading-relaxed text-slate-700">
                  {pendingInput.question}
                </div>
                {pendingInput.options && pendingInput.options.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {pendingInput.options.map((option) => (
                      <button
                        key={option}
                        type="button"
                        onClick={() => submitMessage(option)}
                        className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-ui-small text-slate-700 hover:bg-amber-100"
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                )}
              </div>
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
              className="flex-1 text-chat-body text-slate-700 placeholder-slate-300 bg-transparent resize-none leading-relaxed disabled:opacity-50"
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

function buildChatMessages(messages: ConversationMessage[]) {
  const result: ChatMessage[] = [];
  let pendingEvents: TimelineEvent[] = [];

  for (const msg of messages) {
    if (msg.role === "tool") {
      pendingEvents.push(toolEventFromMessage(msg));
      continue;
    }
    if (msg.role === "assistant") {
      result.push({ ...chatMessageFromConversation(msg), events: pendingEvents });
      pendingEvents = [];
      continue;
    }
    if (pendingEvents.length > 0) {
      result.push(eventOnlyMessage(pendingEvents, msg.created_at));
      pendingEvents = [];
    }
    result.push(chatMessageFromConversation(msg));
  }

  if (pendingEvents.length > 0) {
    result.push(eventOnlyMessage(pendingEvents, new Date().toISOString()));
  }
  return result;
}

function mergePersistedChatMessages(current: ChatMessage[], messages: ConversationMessage[]) {
  let next = [...current];
  for (const msg of messages) {
    if (msg.role === "tool") {
      const event = toolEventFromMessage(msg);
      if (next.some((item) => item.events?.some((existing) => existing.id === event.id))) {
        continue;
      }
      const lastAgentIndex = findLastIndex(next, (item) => item.role === "agent");
      if (lastAgentIndex >= 0) {
        next = next.map((item, index) =>
          index === lastAgentIndex ? { ...item, events: [...(item.events || []), event] } : item
        );
      } else {
        next.push(eventOnlyMessage([event], msg.created_at));
      }
      continue;
    }

    if (next.some((item) => item.id === msg.id)) continue;
    const chatMessage = chatMessageFromConversation(msg);
    const pendingUserIndex =
      msg.role === "user"
        ? next.findIndex(
            (item) =>
              item.role === "user" &&
              String(item.id).startsWith("pending-") &&
              item.content === msg.content
          )
        : -1;
    if (pendingUserIndex >= 0) {
      next = next.map((item, index) => (index === pendingUserIndex ? chatMessage : item));
    } else {
      next.push(chatMessage);
    }
  }
  return next;
}

function chatMessageFromConversation(msg: ConversationMessage): ChatMessage {
  return {
    id: msg.id,
    role: msg.role === "user" ? "user" : "agent",
    content: msg.content,
    created_at: msg.created_at,
    type: msg.role === "system" ? "status" : "text",
  };
}

function eventOnlyMessage(events: TimelineEvent[], createdAt: string): ChatMessage {
  return {
    id: `events-${events[0]?.id || createdAt}`,
    role: "agent",
    content: "",
    created_at: createdAt,
    type: "text",
    events,
  };
}

function toolEventFromMessage(msg: ConversationMessage): TimelineEvent {
  const toolName = String(msg.message_metadata.tool_name || "tool");
  return {
    id: `tool-${msg.id}`,
    title: toolName,
    content: msg.content,
    created_at: msg.created_at,
    status: msg.message_metadata.ok === false ? "error" : "done",
    tool_name: toolName,
  };
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
        <div className="bg-slate-100 px-5 py-3.5 rounded-2xl rounded-tr-sm text-chat-body text-slate-700 max-w-[80%] whitespace-pre-wrap">
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
        <span className="text-ui-small font-medium text-slate-800">LOBSTER Agent</span>
        <div className="border border-slate-200 rounded-xl bg-white p-4 text-chat-body text-slate-600 leading-relaxed whitespace-pre-wrap">
          {message.type === "status" ? (
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
              <span>{message.content}</span>
            </div>
          ) : (
            <div className="space-y-3">
              {message.events && message.events.length > 0 && (
                <ExecutionTimeline events={message.events} />
              )}
              {message.content ? (
                <MarkdownContent content={message.content} />
              ) : message.streaming ? (
                <div className="flex items-center gap-2 text-slate-500">
                  <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
                  <span>正在执行...</span>
                </div>
              ) : null}
            </div>
          )}
        </div>
        <MessageMeta message={message} copied={copied} onCopy={onCopy} align="left" />
      </div>
    </div>
  );
}

function ExecutionTimeline({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
      <div className="mb-2 text-ui-meta font-semibold text-slate-500">执行过程</div>
      <div className="space-y-2">
        {events.map((event) => (
          <div key={event.id} className="flex gap-2 text-ui-small leading-relaxed">
            <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${eventDotClass(event.status)}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-slate-700">{event.title}</span>
                <span className="shrink-0 text-ui-micro text-slate-400">
                  {formatMessageTime(event.created_at)}
                </span>
              </div>
              {event.content && (
                <div className="mt-0.5 break-words text-slate-500">{event.content}</div>
              )}
            </div>
          </div>
        ))}
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
      className={`flex items-center gap-2 text-ui-micro text-slate-400 ${
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

function progressTitle(stage?: string) {
  if (stage === "skill_selection") return "选择 skill";
  if (stage === "plan") return "生成计划";
  return "任务进度";
}

function formatToolInput(input?: Record<string, unknown>) {
  if (!input || Object.keys(input).length === 0) return undefined;
  return JSON.stringify(input);
}

function eventDotClass(status: TimelineEvent["status"]) {
  if (status === "running") return "bg-blue-500 animate-pulse";
  if (status === "done") return "bg-emerald-500";
  if (status === "error") return "bg-red-500";
  return "bg-slate-400";
}

function findLastIndex<T>(items: T[], predicate: (item: T) => boolean) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index])) return index;
  }
  return -1;
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
