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

interface SkillSelectionState {
  selected_skill?: string;
  source?: "model" | "fallback" | string;
  model_choice?: string | null;
  fallback_choice?: string | null;
  reason?: string | null;
  confidence?: number | null;
  error?: string | null;
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
    skill_selection?: SkillSelectionState;
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
  skill_selection?: SkillSelectionState;
  skill_selection_source?: string;
  workflow_path?: string | null;
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
  attempts?: number;
  tool_calls?: WorkflowToolCall[];
  evidence?: Record<string, unknown>;
  validation_failures?: unknown[];
}

interface WorkflowToolCall {
  tool_call_id?: string;
  name?: string;
  status?: string;
  ok?: boolean;
  error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  metadata?: Record<string, unknown>;
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
  kind?: "thinking" | "execution";
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
  skillSelection?: SkillSelectionState;
  workflowPath?: string | null;
  streaming?: boolean;
  run_id?: string | null;
}

interface RunState {
  skillSelection?: SkillSelectionState;
  workflowPath?: string | null;
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

  function handleStreamPayload(payload: StreamPayload) {
    if (payload.type === "assistant_started") {
      setMessages((prev) => {
        const { messages: next, id } = ensureActiveAgentMessage(prev, payload);
        activeAgentMessageIdRef.current = id;
        return next.map((msg) => (msg.id === id ? mergeRunStateIntoMessage(msg, payload) : msg));
      });
      return;
    }
    if (payload.type === "assistant_delta") {
      setMessages((prev) => {
        const { messages: next, id } = ensureActiveAgentMessage(prev, payload);
        activeAgentMessageIdRef.current = id;
        return next.map((msg) =>
          msg.id === id
            ? mergeRunStateIntoMessage(
                { ...msg, content: payload.delta ? `${msg.content}${payload.delta}` : msg.content },
                payload
              )
            : msg
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
        kind: "thinking",
      });
      return;
    }
    if (payload.type === "workflow_loaded") {
      updateWorkflowBoard(payload);
      appendTimelineEvent(payload, {
        id: "workflow-loaded",
        title: "工作流已加载",
        content: "开始执行全自动复现流水线。",
        created_at: payload.timestamp || new Date().toISOString(),
        status: "done",
        kind: "execution",
      });
      return;
    }
    if (payload.type.startsWith("workflow_step_") && payload.step) {
      updateWorkflowBoard(payload);
      const timelineEvent = workflowTimelineEvent(payload);
      if (timelineEvent) {
        appendTimelineEvent(payload, timelineEvent);
      }
      return;
    }
    if (payload.type === "workflow_cleanup_started" || payload.type === "workflow_cleanup_completed") {
      appendTimelineEvent(payload, {
        id: `workflow-cleanup-${payload.type}`,
        title: payload.type === "workflow_cleanup_started" ? "资源兜底释放" : "资源释放检查完成",
        content: payload.content,
        created_at: payload.timestamp || new Date().toISOString(),
        status: payload.type === "workflow_cleanup_started" ? "running" : "done",
        kind: "execution",
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
        kind: "execution",
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
        kind: "execution",
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
        kind: "execution",
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
          ? mergeRunStateIntoMessage(
              { ...msg, workflow: mergeWorkflowState(msg.workflow, payload, conversation) },
              payload
            )
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
    const processOnlyIndex = findCurrentRunProcessMessageIndex(prev);
    if (processOnlyIndex >= 0) {
      const existingProcess = prev[processOnlyIndex];
      activeAgentMessageIdRef.current = existingProcess.id;
      return {
        id: existingProcess.id,
        messages: prev.map((msg, index) =>
          index === processOnlyIndex
            ? {
                ...msg,
                run_id: runId,
                streaming: true,
              }
            : msg
        ),
      };
    }
    const id = `stream-${runId || payload.seq || Date.now()}`;
    activeAgentMessageIdRef.current = id;
    const runState = runStateFromPayload(payload);
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
          skillSelection: runState.skillSelection,
          workflowPath: runState.workflowPath,
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
          return mergeRunStateIntoMessage({ ...msg, events }, payload);
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
        return mergeRunStateIntoMessage({ ...msg, events }, payload);
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
      await navigator.clipboard.writeText(
        cleanFinalAnswer(
          message.content,
          !!message.skillSelection || !!message.workflow || !!message.events?.length
        )
      );
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
  const skillSelection = skillSelectionFromConversation(conversation);
  return attachRunStateToLastAgent(
    result,
    workflowStateFromConversation(conversation),
    skillSelection,
    workflowPathFromSelection(skillSelection),
    conversation?.updated_at
  );
}

function mergePersistedChatMessages(current: ChatMessage[], persistedMessages: ChatMessage[]) {
  let next = [...current];
  for (const chatMessage of persistedMessages) {
    const existingIndex = next.findIndex((item) => item.id === chatMessage.id);
    if (existingIndex >= 0) {
      next = next.map((item, index) =>
        index === existingIndex
          ? mergePersistedMessageState(item, chatMessage)
          : item
      );
      continue;
    }
    if (isProcessOnlyRunMessage(chatMessage)) {
      const currentRunIndex = findCurrentRunProcessMessageIndex(next);
      if (currentRunIndex >= 0) {
        next = next.map((item, index) =>
          index === currentRunIndex ? mergePersistedMessageState(item, chatMessage) : item
        );
        continue;
      }
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

function mergePersistedMessageState(message: ChatMessage, incoming: ChatMessage): ChatMessage {
  return {
    ...message,
    content: incoming.content || message.content,
    created_at: typeof incoming.id === "number" ? incoming.created_at : message.created_at,
    events: mergeTimelineEvents(message.events, incoming.events),
    workflow: mergeWorkflowRunState(message.workflow, incoming.workflow),
    skillSelection: mergeSkillSelectionState(message.skillSelection, incoming.skillSelection),
    workflowPath: message.workflowPath || incoming.workflowPath,
    streaming: message.streaming && !incoming.content ? message.streaming : false,
    run_id: message.run_id || incoming.run_id,
  };
}

function mergeSkillSelectionState(
  current?: SkillSelectionState,
  incoming?: SkillSelectionState
): SkillSelectionState | undefined {
  if (!current) return incoming;
  if (!incoming) return current;
  return {
    selected_skill: incoming.selected_skill ?? current.selected_skill,
    source: incoming.source ?? current.source,
    model_choice: incoming.model_choice !== undefined ? incoming.model_choice : current.model_choice,
    fallback_choice:
      incoming.fallback_choice !== undefined ? incoming.fallback_choice : current.fallback_choice,
    reason: incoming.reason !== undefined ? incoming.reason : current.reason,
    confidence: incoming.confidence !== undefined ? incoming.confidence : current.confidence,
    error: incoming.error !== undefined ? incoming.error : current.error,
  };
}

function mergeWorkflowRunState(
  current?: WorkflowState,
  incoming?: WorkflowState
): WorkflowState | undefined {
  if (!current) return incoming;
  if (!incoming) return current;
  const base = normalizeWorkflowState(current);
  const update = normalizeWorkflowState(incoming);
  let steps = base.steps || [];
  for (const step of update.steps || []) {
    steps = upsertWorkflowStep(steps, step);
  }
  return normalizeWorkflowState({
    ...base,
    name: update.name ?? base.name,
    version: update.version ?? base.version,
    project_name: update.project_name ?? base.project_name,
    current_step_id: update.current_step_id !== undefined ? update.current_step_id : base.current_step_id,
    resources: { ...(base.resources || {}), ...(update.resources || {}) },
    results: { ...(base.results || {}), ...(update.results || {}) },
    steps,
  });
}

function attachRunStateToLastAgent(
  messages: ChatMessage[],
  workflow: WorkflowState | undefined,
  skillSelection: SkillSelectionState | undefined,
  workflowPath: string | null,
  updatedAt?: string
) {
  if (!workflow && !skillSelection) return messages;
  const lastAgentIndex = findLastIndex(messages, (item) => item.role === "agent");
  const lastUserIndex = findLastIndex(messages, (item) => item.role === "user");
  if (lastAgentIndex >= 0 && lastAgentIndex > lastUserIndex) {
    return messages.map((item, index) =>
      index === lastAgentIndex
        ? {
            ...item,
            workflow: mergeWorkflowRunState(item.workflow, workflow),
            skillSelection: mergeSkillSelectionState(item.skillSelection, skillSelection),
            workflowPath: item.workflowPath || workflowPath,
          }
        : item
    );
  }
  return [
    ...messages,
    {
      id: `workflow-${updatedAt || workflow?.name || skillSelection?.selected_skill || "run"}`,
      role: "agent" as const,
      content: "",
      created_at: updatedAt || new Date().toISOString(),
      type: "text" as const,
      workflow,
      skillSelection,
      workflowPath,
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
    kind: "execution",
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

function skillSelectionFromConversation(conversation?: Conversation): SkillSelectionState | undefined {
  const selection = conversation?.metadata?.skill_selection;
  return hasSkillSelectionSignal(selection) ? selection : undefined;
}

function skillSelectionFromPayload(payload: StreamPayload): SkillSelectionState | undefined {
  if (payload.skill_selection) {
    const selection = {
      ...payload.skill_selection,
      source: payload.skill_selection.source || payload.skill_selection_source,
    };
    return hasSkillSelectionSignal(selection) ? selection : undefined;
  }
  if (!payload.skill_selection_source) return undefined;
  return undefined;
}

function hasSkillSelectionSignal(selection?: SkillSelectionState) {
  return !!(
    selection?.selected_skill ||
    selection?.model_choice ||
    selection?.fallback_choice
  );
}

function runStateFromPayload(payload: StreamPayload): RunState {
  const skillSelection = skillSelectionFromPayload(payload);
  return {
    skillSelection,
    workflowPath: workflowPathFromSelection(skillSelection, payload.workflow_path),
  };
}

function mergeRunStateIntoMessage(message: ChatMessage, payload: StreamPayload): ChatMessage {
  const runState = runStateFromPayload(payload);
  if (!runState.skillSelection && !runState.workflowPath) return message;
  return {
    ...message,
    skillSelection: mergeSkillSelectionState(message.skillSelection, runState.skillSelection),
    workflowPath: payload.workflow_path ?? message.workflowPath ?? runState.workflowPath,
  };
}

function isProcessOnlyRunMessage(message: ChatMessage) {
  return (
    message.role === "agent" &&
    message.content === "" &&
    (!!message.skillSelection || !!message.workflow)
  );
}

function findCurrentRunProcessMessageIndex(messages: ChatMessage[]) {
  const lastUserIndex = findLastIndex(messages, (msg) => msg.role === "user");
  return findLastIndex(
    messages,
    (msg, index) =>
      index > lastUserIndex &&
      msg.role === "agent" &&
      (msg.streaming === true || isProcessOnlyRunMessage(msg))
  );
}

function workflowPathFromSelection(selection?: SkillSelectionState, payloadPath?: string | null) {
  if (payloadPath) return payloadPath;
  if (selection?.selected_skill === "lab4ai-auto-reproduct") {
    return "skills/lab4ai-auto-reproduct/project_reproduce.yaml";
  }
  return null;
}

function workflowTimelineEvent(payload: StreamPayload): TimelineEvent | undefined {
  if (!payload.step) return undefined;
  const createdAt = payload.timestamp || new Date().toISOString();
  const base = {
    id: `workflow-${payload.type}-${payload.step.id}`,
    created_at: createdAt,
    kind: "execution" as const,
  };

  if (payload.type === "workflow_step_started") {
    return {
      ...base,
      title: `启动 ${payload.step.id}`,
      content: payload.step.name,
      status: "running",
    };
  }
  if (payload.type === "workflow_step_progress") {
    return {
      ...base,
      id: `workflow-progress-${payload.step.id}-${payload.seq || createdAt}`,
      title: `${payload.step.id} 进展`,
      content: workflowProgressContent(payload.content) || payload.step.name,
      status: "info",
    };
  }
  if (payload.type === "workflow_step_waiting") {
    return {
      ...base,
      title: `${payload.step.id} 等待确认`,
      content: payload.step.name,
      status: "info",
    };
  }
  if (payload.type === "workflow_step_completed") {
    return {
      ...base,
      title: `${payload.step.id} 完成`,
      content: workflowStepDetail(payload.step),
      status: "done",
    };
  }
  if (payload.type === "workflow_step_failed") {
    return {
      ...base,
      title: `${payload.step.id} 失败`,
      content: workflowStepDetail(payload.step),
      status: "error",
    };
  }
  if (payload.type === "workflow_step_recovery_started") {
    return {
      ...base,
      title: `${payload.step.id} 开始自主修复`,
      content: payload.step.name,
      status: "running",
    };
  }
  if (payload.type === "workflow_step_recovery_progress") {
    return {
      ...base,
      id: `workflow-recovery-${payload.step.id}-${payload.seq || createdAt}`,
      title: `${payload.step.id} 修复进展`,
      content: workflowProgressContent(payload.content) || payload.step.name,
      status: "info",
    };
  }
  if (payload.type === "workflow_step_recovery_exhausted") {
    return {
      ...base,
      title: `${payload.step.id} 修复耗尽`,
      content: workflowStepDetail(payload.step),
      status: "error",
    };
  }
  return undefined;
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

function workflowStepStatusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "等待中",
    running: "执行中",
    waiting_for_user: "等待确认",
    completed: "完成",
    failed: "中止",
    skipped: "跳过",
  };
  return labels[status] || status;
}

function workflowStepStatusClass(status: string) {
  if (status === "completed") return "border-emerald-100 bg-emerald-50 text-emerald-700";
  if (status === "running") return "border-blue-100 bg-blue-50 text-blue-700";
  if (status === "waiting_for_user") return "border-amber-100 bg-amber-50 text-amber-700";
  if (status === "failed") return "border-red-100 bg-red-50 text-red-700";
  if (status === "skipped") return "border-slate-100 bg-slate-50 text-slate-500";
  return "border-slate-100 bg-slate-50 text-slate-500";
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

function escapeMarkdownTableCell(value: string) {
  return value.replace(/\|/g, "\\|").replace(/\s*\n+\s*/g, "；");
}

function cleanFinalAnswer(content: string, hasProcess: boolean) {
  const trimmed = content.trim();
  if (!trimmed || !hasProcess) return trimmed;
  const lines = trimmed.split(/\r?\n/);
  const result: string[] = [];
  let skippingWorkflowTable = false;

  for (const line of lines) {
    const normalized = line.trim();
    if (isProcessOnlyLine(normalized)) {
      skippingWorkflowTable =
        normalized === "工具执行结果如下" ||
        normalized.includes("复现流水线实时看板") ||
        normalized.startsWith("| 序号 |");
      continue;
    }
    if (skippingWorkflowTable) {
      if (normalized.startsWith("|") || normalized === "") continue;
      skippingWorkflowTable = false;
    }
    result.push(line);
  }

  const finalStartIndex = result.findIndex((line) => isFinalAnswerStart(line.trim()));
  const finalLines = finalStartIndex > 0 ? result.slice(finalStartIndex) : result;
  return finalLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function isProcessOnlyLine(line: string) {
  if (!line) return false;
  if (/^#{1,6}\s*复现流水线实时看板/.test(line)) return true;
  if (line.startsWith("| 序号 |") || line.startsWith("| ---")) return true;
  if (/^\|?\s*\d+\s*\|\s*`?step_/.test(line)) return true;
  if (/^(工具执行结果如下|调用了子 Claw|使用技能|读取\s|工作流已加载)/.test(line)) return true;
  if (/^(正在启动|Step\s+\d+\s+(完成|通过|失败)|API 超时|任务完成)/.test(line)) return true;
  if (/^(Invoking tool:|Tool completed:|Tool failed:|Start step:)/.test(line)) return true;
  return false;
}

function isFinalAnswerStart(line: string) {
  return /^(最终结论|结论|下一步|需要|请|当前|已完成|我需要|配置完成)/.test(line);
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
    <div className="flex gap-4" data-testid="agent-message">
      <AgentAvatar />
      <div className="flex flex-col gap-2 max-w-[85%] min-w-0">
        <span className="text-ui-small font-medium text-slate-800">LOBSTER Agent</span>
        {message.type === "status" ? (
          <StatusMessage content={message.content} />
        ) : (
          <AgentResponse message={message} />
        )}
        <MessageMeta message={message} copied={copied} onCopy={onCopy} align="left" />
      </div>
    </div>
  );
}

function StatusMessage({ content }: { content: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 text-chat-body leading-relaxed text-slate-600">
      <div className="flex items-center gap-2">
        <div className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
        <span>{content}</span>
      </div>
    </div>
  );
}

function AgentResponse({ message }: { message: ChatMessage }) {
  const hasProcess = !!message.skillSelection || !!message.workflow || !!message.events?.length;
  const finalAnswer = cleanFinalAnswer(message.content, hasProcess);
  return (
    <div className="space-y-3">
      {hasProcess && (
        <div className="space-y-3">
          {message.events && message.events.length > 0 && (
            <AgentProcessTimeline events={message.events} />
          )}
          {message.skillSelection && (
            <SkillSelectionCard
              selection={message.skillSelection}
              workflowPath={message.workflowPath}
            />
          )}
          {message.workflow && <WorkflowBoard workflow={message.workflow} />}
        </div>
      )}
      {finalAnswer ? (
        <FinalAnswer content={finalAnswer} />
      ) : message.streaming ? (
        <RunningState />
      ) : null}
    </div>
  );
}

function FinalAnswer({ content }: { content: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 text-chat-body leading-relaxed text-slate-700">
      <div className="mb-2 text-ui-meta font-semibold uppercase text-slate-400">最终回答</div>
      <MarkdownContent content={content} />
    </div>
  );
}

function RunningState() {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 text-chat-body text-slate-500">
      <div className="flex items-center gap-2">
        <div className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
        <span>正在执行...</span>
      </div>
    </div>
  );
}

function SkillSelectionCard({
  selection,
  workflowPath,
}: {
  selection: SkillSelectionState;
  workflowPath?: string | null;
}) {
  const selected = selection.selected_skill || selection.model_choice || selection.fallback_choice || "未选择";
  const source = skillSelectionSourceMeta(selection.source);
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 bg-slate-50 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
              Skill Selection
            </div>
            <h3 className="mt-1 break-words text-md-h3 font-semibold text-slate-800">
              {source.titlePrefix} {selected}
            </h3>
            {workflowPath && (
              <p className="mt-1 break-words text-ui-small text-slate-500">
                已加载 {workflowPath}
              </p>
            )}
          </div>
          <span className={`shrink-0 rounded-full border px-2.5 py-1 text-ui-micro font-medium ${source.className}`}>
            {source.label}
          </span>
        </div>
      </div>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-ui-small font-medium text-slate-600 hover:bg-slate-50">
          <span>查看选择证据</span>
          <ChevronIcon className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
        </summary>
        <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-3 gap-y-2 border-t border-slate-100 px-4 py-3 text-ui-small">
          <EvidenceRow label="source" value={selection.source || "-"} />
          <EvidenceRow label="selected_skill" value={selection.selected_skill || "-"} />
          <EvidenceRow label="model_choice" value={selection.model_choice || "-"} />
          <EvidenceRow label="fallback_choice" value={selection.fallback_choice || "-"} />
          <EvidenceRow label="workflow" value={workflowPath || "-"} />
          <EvidenceRow label="reason" value={selection.reason || "-"} />
          {selection.error && <EvidenceRow label="error" value={selection.error} />}
        </div>
      </details>
    </section>
  );
}

function skillSelectionSourceMeta(source?: string) {
  if (source === "model") {
    return {
      label: "模型选择",
      titlePrefix: "模型选择了",
      className: "border-blue-100 bg-blue-50 text-blue-700",
    };
  }
  if (source === "fallback") {
    return {
      label: "规则兜底",
      titlePrefix: "规则兜底选择了",
      className: "border-amber-100 bg-amber-50 text-amber-700",
    };
  }
  return {
    label: "已选择",
    titlePrefix: "已选择",
    className: "border-slate-200 bg-slate-50 text-slate-600",
  };
}

function EvidenceRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <span className="font-mono text-slate-400">{label}</span>
      <span className="min-w-0 break-words font-mono text-slate-700">{value}</span>
    </>
  );
}

function WorkflowBoard({ workflow }: { workflow: WorkflowState }) {
  const steps = workflow.steps || REPRO_WORKFLOW_STEPS;
  const completedCount = steps.filter((step) => step.status === "completed").length;
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50 px-4 py-3">
        <div className="min-w-0">
          <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
            执行看板
          </div>
          <h3 className="truncate text-md-h3 font-semibold text-slate-800">
            复现流水线实时看板: {workflow.project_name || "项目"}
          </h3>
        </div>
        <span className="shrink-0 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-ui-micro font-medium text-slate-500">
          {completedCount}/{steps.length} 完成
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full table-fixed border-collapse text-ui-small">
          <thead className="bg-white">
            <tr className="border-b border-slate-100 text-left text-slate-500">
              <th className="w-14 px-4 py-3 font-semibold">序号</th>
              <th className="w-[34%] px-4 py-3 font-semibold">执行步骤</th>
              <th className="w-32 px-4 py-3 font-semibold">当前状态</th>
              <th className="px-4 py-3 font-semibold">执行过程与结果</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step, index) => {
              const template = REPRO_WORKFLOW_STEPS.find((item) => item.id === step.id);
              const name = step.name || template?.name || step.id;
              return (
                <tr key={step.id} className="border-b border-slate-100 last:border-b-0">
                  <td className="px-4 py-3 align-top text-slate-500">{index + 1}</td>
                  <td className="px-4 py-3 align-top">
                    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                      <code className="rounded bg-slate-100 px-1.5 py-0.5 text-ui-small font-semibold text-slate-700">
                        {step.id}
                      </code>
                      <span className="break-words font-medium text-slate-700">{name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <span
                      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-ui-micro font-medium ${workflowStepStatusClass(
                        step.status
                      )}`}
                    >
                      {workflowStepStatusLabel(step.status)}
                    </span>
                  </td>
                  <td className="px-4 py-3 align-top text-slate-600">
                    <WorkflowStepRuntime step={step} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function WorkflowStepRuntime({ step }: { step: WorkflowStepState }) {
  const progressItems = (step.progress || []).slice(-3);
  const toolCalls = (step.tool_calls || []).slice(-3);
  const outcome = workflowStepOutcome(step);
  const startLabel = workflowStepStartLabel(step);
  const hasDetails = progressItems.length > 0 || toolCalls.length > 0 || !!outcome;

  if (!hasDetails) {
    return <span className="break-words">{workflowStepDetail(step)}</span>;
  }

  return (
    <div className="space-y-2">
      {startLabel && <div className="text-ui-small text-slate-500">{startLabel}</div>}
      {progressItems.length > 0 && (
        <div className="space-y-1">
          {progressItems.map((item, index) => (
            <div key={`${step.id}-progress-${index}`} className="flex gap-2 text-ui-small text-slate-500">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-400" />
              <span className="break-words">{workflowProgressContent(item) || item}</span>
            </div>
          ))}
        </div>
      )}
      {toolCalls.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {toolCalls.map((call, index) => (
            <span
              key={call.tool_call_id || `${step.id}-tool-${index}`}
              className={`inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-ui-micro ${toolCallStatusClass(
                call
              )}`}
              title={call.error || undefined}
            >
              <span className="truncate">{toolTitle(String(call.name || "tool"))}</span>
              <span>{toolCallStatusLabel(call)}</span>
            </span>
          ))}
        </div>
      )}
      {outcome && (
        <div className={`rounded-lg border px-2.5 py-2 text-ui-small ${workflowOutcomeClass(step.status)}`}>
          {outcome}
        </div>
      )}
    </div>
  );
}

function workflowStepStartLabel(step: WorkflowStepState) {
  if (step.status === "pending") return "";
  const attempt = step.attempts && step.attempts > 1 ? `第 ${step.attempts} 次尝试` : "开始执行";
  return `${attempt}: ${step.name || step.id}`;
}

function workflowStepOutcome(step: WorkflowStepState) {
  if (step.status === "completed") return workflowStepDetail(step);
  if (step.status === "failed") {
    return step.error || workflowValidationFailureText(step) || workflowStepDetail(step) || "执行失败，等待检查原因。";
  }
  if (step.status === "waiting_for_user") {
    return step.error || step.output || workflowValidationFailureText(step) || "需要用户确认或补充信息后继续。";
  }
  if (step.status === "running") return step.output || "正在执行当前步骤。";
  if (step.status === "skipped") return step.output || "该步骤已跳过。";
  return "";
}

function workflowValidationFailureText(step: WorkflowStepState) {
  const failure = step.validation_failures?.[step.validation_failures.length - 1];
  if (!failure) return "";
  if (typeof failure === "string") return failure;
  if (typeof failure !== "object") return String(failure);

  const record = failure as Record<string, unknown>;
  const reason = record.reason || record.message || record.error || record.postcondition;
  if (typeof reason === "string") return reason;
  if (reason !== undefined) return String(reason);
  return "";
}

function workflowOutcomeClass(status: string) {
  if (status === "completed") return "border-emerald-100 bg-emerald-50 text-emerald-700";
  if (status === "failed") return "border-red-100 bg-red-50 text-red-700";
  if (status === "waiting_for_user") return "border-amber-100 bg-amber-50 text-amber-700";
  if (status === "running") return "border-blue-100 bg-blue-50 text-blue-700";
  return "border-slate-100 bg-slate-50 text-slate-500";
}

function toolCallStatusLabel(call: WorkflowToolCall) {
  if (call.status === "waiting_for_user") return "待确认";
  if (call.status === "completed" && call.ok !== false) return "完成";
  if (call.status === "failed" || call.ok === false) return "失败";
  if (call.status === "running") return "执行中";
  return call.status || "记录";
}

function toolCallStatusClass(call: WorkflowToolCall) {
  if (call.status === "waiting_for_user") return "border-amber-100 bg-amber-50 text-amber-700";
  if (call.status === "completed" && call.ok !== false) return "border-emerald-100 bg-emerald-50 text-emerald-700";
  if (call.status === "failed" || call.ok === false) return "border-red-100 bg-red-50 text-red-700";
  if (call.status === "running") return "border-blue-100 bg-blue-50 text-blue-700";
  return "border-slate-100 bg-slate-50 text-slate-500";
}

function AgentProcessTimeline({ events }: { events: TimelineEvent[] }) {
  const thinkingEvents = events.filter((event) => event.kind === "thinking");
  const executionEvents = events.filter((event) => event.kind !== "thinking");
  return (
    <div className="space-y-3">
      {thinkingEvents.length > 0 && (
        <TimelineSection title="思考过程" events={thinkingEvents} />
      )}
      {executionEvents.length > 0 && (
        <TimelineSection title="执行过程" events={executionEvents} />
      )}
    </div>
  );
}

function TimelineSection({ title, events }: { title: string; events: TimelineEvent[] }) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 bg-slate-50 px-4 py-3">
        <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
          {title}
        </div>
        <span className="rounded-full bg-white px-2 py-0.5 text-ui-micro text-slate-400">
          {events.length} 项
        </span>
      </div>
      <div className="divide-y divide-slate-100">
        {events.map((event) => (
          <TimelineEventCard key={event.id} event={event} />
        ))}
      </div>
    </section>
  );
}

function TimelineEventCard({ event }: { event: TimelineEvent }) {
  const hasContent = !!event.content?.trim();
  return (
    <details className="group" open={event.status === "running" || event.status === "error" || hasContent}>
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3 text-ui-small transition-colors hover:bg-slate-50">
        <span
          className={`h-2.5 w-2.5 shrink-0 rounded-full ${eventDotClass(event.status)}`}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1 truncate font-medium text-slate-700">
          {event.title}
        </span>
        <span className="shrink-0 text-ui-micro text-slate-400">
          {formatMessageTime(event.created_at)}
        </span>
        <ChevronIcon className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
      </summary>
      {hasContent && (
        <div className="px-4 pb-3 pl-[42px] text-ui-small leading-relaxed text-slate-500">
          {event.content}
        </div>
      )}
    </details>
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

function findLastIndex<T>(items: T[], predicate: (item: T, index: number) => boolean) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index], index)) return index;
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

function ChevronIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="m6 9 6 6 6-6" />
    </svg>
  );
}
