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

interface PendingIntervention {
  type: string;
  title?: string;
  admin_endpoint?: string;
  [key: string]: unknown;
}

interface PendingUserInput {
  question: string;
  options?: string[];
  step?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  intervention?: PendingIntervention;
}

interface Conversation {
  id: number;
  title: string;
  status: string;
  task_type?: string;
  updated_at: string;
  metadata: {
    task_type?: string;
    github_url?: string;
    paper_url?: string;
    selected_skill?: string;
    workflow_state?: string;
    workflow_name?: string;
    workflow_version?: string;
    workflow_current_step_id?: string | null;
    workflow_steps?: WorkflowStepState[];
    workflow_resources?: Record<string, WorkflowResource>;
    workflow_results?: Record<string, unknown>;
    pending_user_input?: PendingUserInput | null;
  };
  messages: ConversationMessage[];
}

interface StreamPayload {
  seq?: number;
  type: string;
  run_id?: string | null;
  status?: string;
  timestamp?: string;
  delta?: string;
  stage?: string;
  content?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  workflow_step_id?: string;
  ok?: boolean;
  error?: string;
  message?: ConversationMessage;
  step?: WorkflowStepState;
  workflow?: WorkflowState;
}

interface WorkflowStepState {
  id: string;
  name: string;
  status: string;
  output?: string;
  error?: string | null;
  expected_output?: string;
  progress?: string[];
  artifacts?: string[];
}

interface WorkflowState {
  name?: string;
  version?: string;
  project_name?: string;
  current_step_id?: string | null;
  steps?: WorkflowStepState[];
  resources?: Record<string, WorkflowResource>;
  results?: Record<string, unknown>;
}

interface WorkflowResource {
  server_id?: string;
  released?: boolean;
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
  workflow?: WorkflowState;
  streaming?: boolean;
  run_id?: string | null;
}

const REPRO_WORKFLOW_STEPS: WorkflowStepState[] = [
  { id: "step_1_audit", name: "项目与论文双重审计", status: "pending" },
  { id: "step_2_condition_check", name: "复现可行性熔断判断", status: "pending" },
  { id: "step_3_deploy_cpu", name: "创建 CPU 实例", status: "pending" },
  { id: "step_4_cpu_env_setup", name: "SSH探活 + 克隆代码 + 智能环境构建", status: "pending" },
  { id: "step_5_release_cpu", name: "释放 CPU 实例", status: "pending" },
  { id: "step_6_deploy_gpu", name: "创建 GPU 实例", status: "pending" },
  { id: "step_7_gpu_execution", name: "CUDA编译 + 推理/微调测试", status: "pending" },
  { id: "step_8_generate_report", name: "生成工业级报告", status: "pending" },
  { id: "step_9_release_gpu", name: "释放 GPU 实例", status: "pending" },
];

export default function ChatPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [copiedMessageId, setCopiedMessageId] = useState<number | string | null>(null);
  const [credentialForm, setCredentialForm] = useState({ phone: "", password: "" });
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [credentialError, setCredentialError] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastSeqRef = useRef(0);
  const activeAgentMessageIdRef = useRef<number | string | null>(null);
  const currentRoundStartedAtRef = useRef(0);
  const [streamNonce, setStreamNonce] = useState(0);

  const { data: conversation } = useQuery({
    queryKey: ["conversation", taskId],
    queryFn: () => apiFetch<Conversation>(`/api/conversations/${taskId}`),
    enabled: !!taskId,
    refetchInterval: 3000,
  });

  useEffect(() => {
    lastSeqRef.current = 0;
    activeAgentMessageIdRef.current = null;
    currentRoundStartedAtRef.current = 0;
    setMessages([]);
  }, [taskId]);

  useEffect(() => {
    if (!conversation) return;
    const persistedMessages = buildChatMessages(conversation.messages, conversation);
    setMessages((prev) =>
      prev.length === 0 ? persistedMessages : mergePersistedChatMessages(prev, persistedMessages)
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
  }, [taskId, conversation?.id, conversation?.status, streamNonce, queryClient]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (conversation?.metadata?.pending_user_input?.intervention?.type !== "lab4ai_credentials_required") {
      setCredentialError("");
      setCredentialSaving(false);
    }
  }, [conversation?.metadata?.pending_user_input?.intervention?.type]);

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
    if (payload.type === "ask_user") {
      freezeActiveAgentMessage();
      return;
    }
    if (payload.type === "status" && payload.status && payload.status !== "running") {
      freezeActiveAgentMessage();
      return;
    }
    if (payload.type === "progress") {
      appendTimelineEvent(payload, {
        id: `progress-${payload.stage || "general"}`,
        title: progressTitle(payload.stage, payload.content),
        content: progressContent(payload.stage, payload.content),
        created_at: payload.timestamp || new Date().toISOString(),
        status: "info",
      });
      return;
    }
    if (payload.type === "workflow_loaded") {
      updateWorkflowBoard(payload);
      return;
    }
    if (payload.type.startsWith("workflow_step_") && payload.step) {
      updateWorkflowBoard(payload);
      return;
    }
    if (payload.type === "workflow_cleanup_started" || payload.type === "workflow_cleanup_completed") {
      appendTimelineEvent(payload, {
        id: `workflow-cleanup-${payload.type}`,
        title: payload.type === "workflow_cleanup_started" ? "资源兜底释放" : "资源释放检查完成",
        content: payload.content,
        created_at: payload.timestamp || new Date().toISOString(),
        status: payload.type === "workflow_cleanup_started" ? "running" : "done",
      });
      return;
    }
    if (payload.type === "tool_started" && payload.tool_name) {
      appendTimelineEvent(payload, {
        id: `tool-${payload.tool_input?.tool_call_id || payload.seq || Date.now()}`,
        title: toolTitle(payload.tool_name),
        content: toolStartedContent(payload.tool_name, payload.tool_input),
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
        title: toolTitle(toolName),
        content: toolResultContent(payload.message),
        created_at: payload.message.created_at,
        status: payload.ok === false ? "error" : "done",
        tool_name: toolName,
      });
      return;
    }
    if (payload.type === "tool_error" && payload.tool_name) {
      appendTimelineEvent(payload, {
        id: `tool-error-${payload.seq ?? Date.now()}`,
        title: toolTitle(payload.tool_name),
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

  function updateWorkflowBoard(payload: StreamPayload) {
    setMessages((prev) => {
      const { messages: next, id } = ensureActiveAgentMessage(prev, payload);
      activeAgentMessageIdRef.current = id;
      return next.map((msg) =>
        msg.id === id
          ? { ...msg, workflow: mergeWorkflowState(msg.workflow, payload, conversation) }
          : msg
      );
    });
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
    if (existing && !isStaleRoundMessage(existing)) {
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
      if (prev.some((item) => item.id === message.id)) {
        activeAgentMessageIdRef.current = null;
        return prev.map((item) => (item.id === message.id ? { ...item, streaming: false } : item));
      }
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

  function freezeActiveAgentMessage() {
    const activeId = activeAgentMessageIdRef.current;
    if (!activeId) return;
    setMessages((prev) =>
      prev.map((msg) => (msg.id === activeId ? { ...msg, streaming: false } : msg))
    );
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
    const roundStartedAt = Date.now();
    currentRoundStartedAtRef.current = roundStartedAt;
    activeAgentMessageIdRef.current = null;
    setInput("");
    setMessages((prev) => [
      ...prev,
      {
        id: `pending-${roundStartedAt}`,
        role: "user",
        content: trimmed,
        created_at: new Date(roundStartedAt).toISOString(),
      },
    ]);
    try {
      const detail = await apiPost<Conversation>(`/api/conversations/${taskId}/messages`, {
        content: trimmed,
      });
      setMessages((prev) => mergePersistedChatMessages(prev, buildChatMessages(detail.messages, detail)));
      lastSeqRef.current = 0;
      activeAgentMessageIdRef.current = null;
      setStreamNonce((value) => value + 1);
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

  async function saveLab4AICredentialsAndContinue() {
    if (!pendingInput || credentialSaving) return;
    setCredentialError("");
    const phone = credentialForm.phone.trim();
    const password = credentialForm.password;
    if (!phone || !password) {
      setCredentialError("请填写 Lab4AI 手机号和密码。");
      return;
    }
    try {
      setCredentialSaving(true);
      await apiFetch("/api/admin/settings/lab4ai", {
        method: "PUT",
        body: JSON.stringify({ phone, password }),
      });
      setCredentialForm({ phone: "", password: "" });
      await submitMessage("已完成配置，继续执行");
    } catch (error) {
      const message = error instanceof Error ? error.message : "保存失败，请稍后重试。";
      setCredentialError(
        message.includes("管理员权限")
          ? "当前账号没有管理员权限，请使用管理员账号配置 Lab4AI 凭证。"
          : message
      );
    } finally {
      setCredentialSaving(false);
    }
  }

  function isStaleRoundMessage(message: ChatMessage) {
    if (!currentRoundStartedAtRef.current) return false;
    return new Date(message.created_at).getTime() < currentRoundStartedAtRef.current;
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

  const pendingInput = conversation?.metadata?.pending_user_input;
  const isWaitingForUser =
    conversation?.metadata?.workflow_state === "waiting_for_user" && !!pendingInput;
  const isRunning = conversation?.status === "running" && !isWaitingForUser;

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
              <div className="w-full max-w-[85%] rounded-xl border border-amber-200 bg-amber-50 p-4" data-testid="inline-human-decision">
                <div className="text-ui-meta font-bold uppercase text-amber-700">
                  等待你确认
                </div>
                {pendingInput.tool_name && (
                  <div className="mt-1 text-ui-meta text-amber-600">
                    操作：{toolTitle(pendingInput.tool_name)}
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

      {isWaitingForUser && pendingInput && (
        <HumanDecisionModal
          pendingInput={pendingInput}
          credentialForm={credentialForm}
          credentialSaving={credentialSaving}
          credentialError={credentialError}
          onCredentialChange={setCredentialForm}
          onSaveCredentials={saveLab4AICredentialsAndContinue}
          onOption={(option) => submitMessage(option)}
        />
      )}

      <div className="shrink-0 p-3 bg-white border-t border-slate-100">
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto">
          <div className="w-full flex items-end gap-3 rounded-xl border border-slate-200 bg-slate-50 focus-within:border-slate-300 focus-within:bg-white px-4 py-3 transition-colors">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isWaitingForUser
                    ? "请直接回复确认，或点击上方选项..."
                    : isRunning
                      ? "任务执行中，完成后可继续对话..."
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

function buildChatMessages(messages: ConversationMessage[], conversation?: Conversation) {
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
  return attachWorkflowToLastAgent(result, workflowStateFromConversation(conversation), conversation?.updated_at);
}

function mergePersistedChatMessages(current: ChatMessage[], persistedMessages: ChatMessage[]) {
  let next = [...current];
  for (const chatMessage of persistedMessages) {
    const existingIndex = next.findIndex((item) => item.id === chatMessage.id);
    if (existingIndex >= 0) {
      next = next.map((item, index) =>
        index === existingIndex
          ? {
              ...item,
              content: chatMessage.content || item.content,
              created_at: typeof chatMessage.id === "number" ? chatMessage.created_at : item.created_at,
              events: mergeTimelineEvents(item.events, chatMessage.events),
              workflow: chatMessage.workflow || item.workflow,
              streaming: item.streaming && !chatMessage.content ? item.streaming : false,
            }
          : item
      );
      continue;
    }
    const pendingUserIndex =
      chatMessage.role === "user"
        ? next.findIndex(
            (item) =>
              item.role === "user" &&
              String(item.id).startsWith("pending-") &&
              item.content === chatMessage.content
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

function attachWorkflowToLastAgent(
  messages: ChatMessage[],
  workflow: WorkflowState | undefined,
  updatedAt?: string
) {
  if (!workflow) return messages;
  const lastAgentIndex = findLastIndex(messages, (item) => item.role === "agent");
  if (lastAgentIndex >= 0) {
    return messages.map((item, index) =>
      index === lastAgentIndex ? { ...item, workflow: item.workflow || workflow } : item
    );
  }
  return [
    ...messages,
    {
      id: `workflow-${updatedAt || workflow.name || "board"}`,
      role: "agent" as const,
      content: "",
      created_at: updatedAt || new Date().toISOString(),
      type: "text" as const,
      workflow,
    },
  ];
}

function mergeTimelineEvents(current?: TimelineEvent[], incoming?: TimelineEvent[]) {
  if (!current?.length) return incoming;
  if (!incoming?.length) return current;
  const next = [...current];
  for (const event of incoming) {
    const index = next.findIndex((item) => item.id === event.id);
    if (index >= 0) {
      next[index] = { ...next[index], ...event };
    } else {
      next.push(event);
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
    title: toolTitle(toolName),
    content: toolResultContent(msg),
    created_at: msg.created_at,
    status: msg.message_metadata.ok === false ? "error" : "done",
    tool_name: toolName,
  };
}

function workflowStateFromConversation(conversation?: Conversation): WorkflowState | undefined {
  const metadata = conversation?.metadata;
  const selectedSkill = metadata?.selected_skill;
  const isReproduce =
    selectedSkill === "lab4ai-auto-reproduct" ||
    !!metadata?.workflow_name ||
    !!metadata?.workflow_steps;
  if (!isReproduce) return undefined;

  return normalizeWorkflowState({
    name: metadata?.workflow_name,
    version: metadata?.workflow_version,
    project_name: projectNameFromConversation(conversation),
    current_step_id: metadata?.workflow_current_step_id,
    steps: metadata?.workflow_steps,
    resources: metadata?.workflow_resources,
    results: metadata?.workflow_results,
  });
}

function mergeWorkflowState(
  current: WorkflowState | undefined,
  payload: StreamPayload,
  conversation?: Conversation
): WorkflowState {
  const base = current || workflowStateFromConversation(conversation) || normalizeWorkflowState();
  const incoming = payload.workflow ? normalizeWorkflowState(payload.workflow) : undefined;
  const next = normalizeWorkflowState({
    ...base,
    ...incoming,
    project_name: incoming?.project_name || base.project_name || projectNameFromConversation(conversation),
    resources: incoming?.resources || base.resources,
    results: incoming?.results || base.results,
    steps: incoming?.steps || base.steps,
  });

  if (payload.step) {
    next.steps = upsertWorkflowStep(next.steps || [], payload.step);
    next.current_step_id = payload.workflow_step_id || payload.step.id || next.current_step_id;
  }

  return next;
}

function normalizeWorkflowState(state?: WorkflowState): WorkflowState {
  const incomingSteps = state?.steps || [];
  const incomingById = new Map(incomingSteps.map((step) => [step.id, step]));
  const steps = REPRO_WORKFLOW_STEPS.map((template) => ({
    ...template,
    ...(incomingById.get(template.id) || {}),
  }));
  for (const step of incomingSteps) {
    if (!REPRO_WORKFLOW_STEPS.some((template) => template.id === step.id)) {
      steps.push(step);
    }
  }
  return {
    name: state?.name,
    version: state?.version,
    project_name: state?.project_name,
    current_step_id: state?.current_step_id,
    resources: state?.resources || {},
    results: state?.results || {},
    steps,
  };
}

function upsertWorkflowStep(steps: WorkflowStepState[], step: WorkflowStepState) {
  const next = [...steps];
  const index = next.findIndex((item) => item.id === step.id);
  if (index >= 0) {
    next[index] = { ...next[index], ...step };
  } else {
    next.push(step);
  }
  return next;
}

function projectNameFromConversation(conversation?: Conversation) {
  const results = conversation?.metadata?.workflow_results;
  if (typeof results?.repo_name === "string" && results.repo_name.trim()) return results.repo_name;
  const githubUrl = conversation?.metadata?.github_url;
  if (githubUrl) {
    const name = githubUrl.replace(/\.git$/i, "").split("/").filter(Boolean).pop();
    if (name) return name;
  }
  return conversation?.title || "项目";
}

function workflowBoardMarkdown(workflow: WorkflowState) {
  const projectName = workflow.project_name || "项目";
  const rows = (workflow.steps || REPRO_WORKFLOW_STEPS).map((step, index) => {
    const template = REPRO_WORKFLOW_STEPS.find((item) => item.id === step.id);
    const name = step.name || template?.name || step.id;
    return `| ${index + 1} | \`${step.id}\`: ${name} | ${workflowStepMarkdownStatus(step.status)} | ${workflowStepDetail(step)} |`;
  });

  return [
    `#### 复现流水线实时看板: \`${escapeMarkdown(projectName)}\``,
    "",
    "| 序号 | 执行步骤 (对应 YAML Task) | 当前状态 | 核心产出 / 详情 |",
    "| --- | --- | --- | --- |",
    ...rows,
  ].join("\n");
}

function workflowStepMarkdownStatus(status: string) {
  const labels: Record<string, string> = {
    pending: "等待中",
    running: "执行中",
    waiting_for_user: "等待确认",
    completed: "完成",
    failed: "中止",
    skipped: "跳过",
  };
  const prefix: Record<string, string> = {
    pending: "⏳",
    running: "⏳",
    waiting_for_user: "⏸",
    completed: "✅",
    failed: "❌",
    skipped: "↷",
  };
  return `${prefix[status] || "•"} ${labels[status] || status}`;
}

function workflowStepDetail(step: WorkflowStepState) {
  const detail =
    step.output ||
    step.error ||
    step.artifacts?.[step.artifacts.length - 1] ||
    workflowProgressContent(step.progress?.[step.progress.length - 1]) ||
    defaultWorkflowStepDetail(step.id);
  return escapeMarkdownTableCell(detail || "-");
}

function defaultWorkflowStepDetail(stepId: string) {
  const details: Record<string, string> = {
    step_1_audit: "可行性评分 / 论文 Baseline / 超参数",
    step_2_condition_check: "通过 / 熔断原因",
    step_3_deploy_cpu: "serverId / SSH 信息",
    step_4_cpu_env_setup: "clone完成 / 依赖安装结果",
    step_5_release_cpu: "关机确认 / 运行时长",
    step_6_deploy_gpu: "serverId / SSH 信息",
    step_7_gpu_execution: "编译结果 / 实测指标 / VRAM",
    step_8_generate_report: "Word 文件路径",
    step_9_release_gpu: "关机确认 / 运行时长",
  };
  return details[stepId] || "";
}

function finalDeliveryMarkdown(workflow: WorkflowState) {
  const results = workflow.results || {};
  const projectName = workflow.project_name || String(results.repo_name || "项目");
  const reportPath =
    typeof results.word_report_path === "string" && results.word_report_path
      ? results.word_report_path
      : "待生成";
  const metrics = results.smoke_test_metrics;
  const metricRows =
    metrics && typeof metrics === "object" && !Array.isArray(metrics)
      ? Object.entries(metrics as Record<string, unknown>).map(
          ([key, value]) => `| ${escapeMarkdownTableCell(key)} | 待对齐 | ${escapeMarkdownTableCell(String(value))} |`
        )
      : ["| Smoke Test | 待对齐 | 待接入真实 SSH 执行 |"];

  return [
    `## 任务完成：${escapeMarkdown(projectName)} 自动化复现已结项`,
    "",
    "**1. 核心指标对比 (Smoke Test 实测)**",
    "| 评估维度 | 原论文/官方基准 | H100 实测数据 |",
    "| --- | --- | --- |",
    ...metricRows,
    "",
    "**2. H100 架构优化洞察**",
    "> 当前版本会在真实 SSH executor 接入后，根据 step_7 编译与微调日志生成优化建议。",
    "",
    "**3. 工业级复现报告提取**",
    "Word 报告已排版落盘，请前往该绝对路径获取：",
    `\`${reportPath}\``,
    "",
    "资源监控核对：本次流水线调用的 CPU 与 GPU 实例均已触发释放步骤核对。",
  ].join("\n");
}

function shouldShowFinalDelivery(workflow: WorkflowState) {
  const steps = workflow.steps || [];
  return steps.some((step) => step.id === "step_9_release_gpu" && step.status === "completed");
}

function escapeMarkdown(value: string) {
  return value.replace(/([\\`*_{}[\]()#+.!|>])/g, "\\$1");
}

function escapeMarkdownTableCell(value: string) {
  return value.replace(/\|/g, "\\|").replace(/\s*\n+\s*/g, "；");
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
      <div className="flex flex-col gap-2 max-w-[85%] min-w-0">
        <span className="text-ui-small font-medium text-slate-800">LOBSTER Agent</span>
        <div className="border border-slate-200 rounded-xl bg-white p-4 text-chat-body text-slate-600 leading-relaxed whitespace-pre-wrap">
          {message.type === "status" ? (
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
              <span>{message.content}</span>
            </div>
          ) : (
            <div className="space-y-3">
              {message.workflow && (
                <WorkflowBoard workflow={message.workflow} />
              )}
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

function WorkflowBoard({ workflow }: { workflow: WorkflowState }) {
  return (
    <div className="space-y-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
      <MarkdownContent content={workflowBoardMarkdown(workflow)} />
      {shouldShowFinalDelivery(workflow) && (
        <MarkdownContent content={finalDeliveryMarkdown(workflow)} />
      )}
    </div>
  );
}

function HumanDecisionModal({
  pendingInput,
  credentialForm,
  credentialSaving,
  credentialError,
  onCredentialChange,
  onSaveCredentials,
  onOption,
}: {
  pendingInput: PendingUserInput;
  credentialForm: { phone: string; password: string };
  credentialSaving: boolean;
  credentialError: string;
  onCredentialChange: (value: { phone: string; password: string }) => void;
  onSaveCredentials: () => void;
  onOption: (option: string) => void;
}) {
  const isLab4AICredentials =
    pendingInput.intervention?.type === "lab4ai_credentials_required";
  const stopOption = pendingInput.options?.find((option) => /停止|取消|stop/i.test(option));

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/35 px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="human-decision-title"
        className="w-full max-w-lg rounded-xl border border-slate-200 bg-white shadow-xl"
      >
        <div className="border-b border-slate-100 px-5 py-4">
          <div className="text-ui-meta font-bold uppercase text-amber-700">需要用户决策</div>
          <h2 id="human-decision-title" className="mt-1 text-lg font-semibold text-slate-900">
            {isLab4AICredentials
              ? pendingInput.intervention?.title || "需要配置 Lab4AI 平台账号"
              : pendingInput.tool_name
                ? toolTitle(pendingInput.tool_name)
                : "确认下一步"}
          </h2>
          {pendingInput.tool_name && (
            <div className="mt-1 text-ui-small text-slate-500">
              操作：{toolTitle(pendingInput.tool_name)}
            </div>
          )}
        </div>

        <div className="space-y-4 px-5 py-4">
          <p className="text-chat-body leading-relaxed text-slate-700">{pendingInput.question}</p>

          {isLab4AICredentials ? (
            <div className="space-y-3">
              <label className="block text-ui-small font-medium text-slate-700">
                Lab4AI 手机号
                <input
                  value={credentialForm.phone}
                  onChange={(event) =>
                    onCredentialChange({ ...credentialForm, phone: event.target.value })
                  }
                  autoComplete="username"
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-chat-body text-slate-800 outline-none focus:border-slate-400"
                  placeholder="请输入平台账号手机号"
                />
              </label>
              <label className="block text-ui-small font-medium text-slate-700">
                Lab4AI 密码
                <input
                  value={credentialForm.password}
                  onChange={(event) =>
                    onCredentialChange({ ...credentialForm, password: event.target.value })
                  }
                  type="password"
                  autoComplete="current-password"
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-chat-body text-slate-800 outline-none focus:border-slate-400"
                  placeholder="请输入平台账号密码"
                />
              </label>
              {credentialError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-ui-small text-red-700">
                  {credentialError}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-ui-small text-slate-600">
              当前流程已暂停，确认后会从这一轮的等待点继续执行。
            </div>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-5 py-4">
          {isLab4AICredentials ? (
            <>
              {stopOption && (
                <button
                  type="button"
                  onClick={() => onOption(stopOption)}
                  disabled={credentialSaving}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-ui-small text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  {stopOption}
                </button>
              )}
              <button
                type="button"
                onClick={onSaveCredentials}
                disabled={credentialSaving}
                className="rounded-lg bg-slate-900 px-4 py-2 text-ui-small font-medium text-white hover:bg-slate-800 disabled:bg-slate-300"
              >
                {credentialSaving ? "保存中..." : "保存并继续执行"}
              </button>
            </>
          ) : (
            (pendingInput.options || ["继续执行"]).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onOption(option)}
                className={
                  /停止|取消|拒绝|stop|cancel/i.test(option)
                    ? "rounded-lg border border-slate-200 bg-white px-3 py-2 text-ui-small text-slate-600 hover:bg-slate-50"
                    : "rounded-lg bg-slate-900 px-4 py-2 text-ui-small font-medium text-white hover:bg-slate-800"
                }
              >
                {option}
              </button>
            ))
          )}
        </div>
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

function progressTitle(stage?: string, content?: string) {
  if (stage === "skill_selection") return "选择复现流程";
  if (stage === "plan") return content?.startsWith("真实模型调用失败") ? "模型调用降级" : "制定执行计划";
  if (stage?.startsWith("tool_use_iteration_")) return "模型规划工具调用";
  return "任务进度";
}

function progressContent(stage?: string, content?: string) {
  if (!content) return undefined;
  if (stage === "skill_selection") {
    return "已进入项目复现流程，开始按工作流分析仓库并准备后续步骤。";
  }
  return content;
}

function workflowProgressContent(content?: string) {
  if (!content) return undefined;
  if (content.startsWith("Start step:")) return "步骤开始。";
  if (content.startsWith("Invoking tool:")) {
    return `正在${toolActionLabel(content.replace("Invoking tool:", "").trim())}。`;
  }
  if (content.startsWith("Tool waiting for user:")) return "需要你确认后继续。";
  if (content.startsWith("Tool completed:")) {
    return `${toolActionLabel(content.replace("Tool completed:", "").trim())}完成。`;
  }
  if (content.startsWith("Tool failed:")) {
    return `${toolActionLabel(content.replace("Tool failed:", "").trim())}失败。`;
  }
  if (content.startsWith("Cleanup releasing CPU")) return "正在释放 CPU 实例。";
  if (content.startsWith("Cleanup releasing GPU")) return "正在释放 GPU 实例。";
  return content;
}

function toolTitle(toolName: string) {
  const labels: Record<string, string> = {
    analyze_repo: "分析 GitHub 仓库",
    lab4ai_create_instance: "创建 Lab4AI 实例",
    lab4ai_stop_instance: "释放 Lab4AI 实例",
    lab4ai_list_instances: "查询 Lab4AI 实例",
    ssh_execute: "执行远程命令",
    file_write: "写入任务文件",
    repro_report: "生成复现报告",
    ask_user: "等待人工确认",
  };
  return labels[toolName] || toolName;
}

function toolActionLabel(toolName: string) {
  const labels: Record<string, string> = {
    analyze_repo: "分析仓库",
    lab4ai_create_instance: "创建算力实例",
    lab4ai_stop_instance: "释放算力实例",
    lab4ai_list_instances: "查询算力实例",
    ssh_execute: "执行远程命令",
    file_write: "写入任务文件",
    repro_report: "生成复现报告",
    ask_user: "等待确认",
  };
  return labels[toolName] || "执行工具";
}

function toolStartedContent(toolName: string, input?: Record<string, unknown>) {
  if (toolName === "analyze_repo" && typeof input?.github_url === "string") {
    return input.github_url;
  }
  if (toolName === "lab4ai_create_instance") {
    return `${String(input?.resource_kind || "算力").toUpperCase()} 实例`;
  }
  if (toolName === "lab4ai_stop_instance") {
    return typeof input?.server_id === "string" && input.server_id
      ? `实例 ${input.server_id}`
      : "释放当前实例";
  }
  if (toolName === "ssh_execute") return "远程命令已提交到受控执行器。";
  if (toolName === "file_write") return "任务工作区文件写入请求。";
  return undefined;
}

function toolResultContent(message: ConversationMessage) {
  const metadata = message.message_metadata || {};
  const toolName = String(metadata.tool_name || "tool");
  if (toolName === "ask_user") return "流程已暂停，等待你确认。";
  if (metadata.ok === false) return message.content;
  if (toolName === "analyze_repo") return message.content;
  if (toolName === "lab4ai_create_instance") {
    const kind = String(metadata.resource_kind || "Lab4AI").toUpperCase();
    return metadata.server_id ? `${kind} 实例已创建：${metadata.server_id}` : message.content;
  }
  if (toolName === "lab4ai_stop_instance") {
    return metadata.server_id ? `实例已释放：${metadata.server_id}` : message.content;
  }
  if (toolName === "ssh_execute") return "远程命令执行完成。";
  if (toolName === "file_write") return "文件写入步骤已完成。";
  if (toolName === "repro_report") return message.content;
  return message.content;
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
