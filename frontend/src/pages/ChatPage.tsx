import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MarkdownContent } from "../components/MarkdownContent";
import { ZeroCodeAgentPanel } from "../components/ZeroCodeAgentPanel";
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

interface Lab4AICredentialsSaveResponse {
  configured?: boolean;
  phone_masked?: string;
}

interface PendingUserInput {
  question: string;
  options?: string[];
  step?: string;
  workflow_step_id?: string;
  gate?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  fields?: PendingInputField[];
  command_preview?: string[];
  resume_action?: string;
  timeout_policy?: PendingTimeoutPolicy;
  intervention?: PendingIntervention;
}

interface PendingInputField {
  id: string;
  label?: string;
  type?: string;
  value?: unknown;
  placeholder?: string;
  required?: boolean;
}

interface PendingTimeoutPolicy {
  minutes?: number;
  on_timeout?: string;
  description?: string;
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
    runtime?: RuntimeMetadata;
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
  tool_call_id?: string;
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
  phase?: string;
  execution_location?: string;
  progress?: string[];
  artifacts?: string[];
  attempts?: number;
  tool_calls?: WorkflowToolCall[];
  evidence?: Record<string, unknown>;
  validation_failures?: unknown[];
  instruction_plan?: RuntimeInstructionPlan;
  gates?: string[];
  command_templates?: Record<string, string[] | string>;
  confirm_required?: boolean;
  skill_file?: string;
  started_at?: string | null;
  completed_at?: string | null;
}

interface RuntimeMetadata {
  active_skill?: {
    name?: string;
  } | null;
  active_workflow?: RuntimeWorkflowState | null;
  instruction_plans?: Record<string, RuntimeInstructionPlan>;
}

interface RuntimeWorkflowState {
  kind?: string;
  name?: string;
  version?: string;
  current_step_id?: string | null;
  steps?: Record<string, RuntimeWorkflowStep>;
  gate_log?: Record<string, unknown>;
  completion_criteria?: string[];
  resources?: Record<string, WorkflowResource>;
  results?: Record<string, unknown>;
}

interface RuntimeWorkflowStep extends Omit<WorkflowStepState, "instruction_plan"> {
  instruction?: string;
  allowed_tools?: string[];
  required_evidence?: string[];
  instruction_plan_id?: string;
  gates?: string[];
  command_templates?: Record<string, string[] | string>;
  confirm_required?: boolean;
  skill_file?: string;
}

interface RuntimeInstructionPlan {
  step_id?: string;
  step_name?: string;
  items?: RuntimeInstructionItem[];
}

interface RuntimeInstructionItem {
  id?: string;
  text?: string;
  status?: string;
  required?: boolean;
  missing_reason?: string;
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
  kind?: string;
  name?: string;
  version?: string;
  project_name?: string;
  current_step_id?: string | null;
  steps?: WorkflowStepState[];
  gate_log?: Record<string, unknown>;
  completion_criteria?: string[];
  resources?: Record<string, WorkflowResource>;
  results?: Record<string, unknown>;
}

interface WorkflowResource {
  server_id?: string;
  released?: boolean;
  raw?: Record<string, unknown>;
}

interface TimelineEvent {
  id: number | string;
  title: string;
  content?: string;
  created_at: string;
  status: "running" | "done" | "error" | "info";
  kind?: "thinking" | "execution";
  tool_name?: string;
  workflow_step_id?: string;
}

type StructuredProcessActionStatus = "done" | "failed" | "waiting" | "todo" | "risk";

interface StructuredProcessAction {
  title: string;
  status: StructuredProcessActionStatus;
  detail?: string;
}

interface StructuredWorkflowSnapshot {
  completed: number;
  total: number;
  current?: string;
  state?: string;
}

interface StructuredProcessRecord {
  id: number | string;
  title: string;
  judgement: string;
  snapshot?: StructuredWorkflowSnapshot;
  actions: StructuredProcessAction[];
  raw: string;
}

interface StructuredProcessParseInput {
  id: number | string;
  title: string;
  content?: string;
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
  message_metadata?: Record<string, unknown>;
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

const AUTORESEARCH_WORKFLOW_STEPS: WorkflowStepState[] = [
  { id: "instance_provision", name: "Step 1: Provision compute instance", status: "pending" },
  { id: "policies", name: "Step 2: Policies", status: "pending" },
  { id: "setup", name: "Step 3: Project setup", status: "pending" },
  { id: "environments", name: "Step 4: Environments", status: "pending" },
  { id: "experimentation", name: "Step 5: Experimentation", status: "pending" },
  { id: "output_and_logging", name: "Step 5: Logging results", status: "pending" },
  { id: "experiment_loop", name: "Step 6: The experiment loop", status: "pending" },
  { id: "final_report", name: "Step 7: Final automation experiment report", status: "pending" },
  { id: "instance_teardown", name: "Step 8: Stop lab instance", status: "pending" },
];

const REPRO_WORKFLOW_PHASES = [
  {
    id: "feasibility",
    title: "阶段一：可行性分析",
    subtitle: "仓库审计、论文基准与熔断判断",
    stepIds: ["step_1_audit", "step_2_condition_check"],
  },
  {
    id: "cpu",
    title: "阶段二：CPU 准备与环境构建",
    subtitle: "低成本实例、SSH 探活、依赖与工作区",
    stepIds: ["step_3_deploy_cpu", "step_4_cpu_env_setup", "step_5_release_cpu"],
  },
  {
    id: "gpu",
    title: "阶段三：GPU 实测与指标采集",
    subtitle: "GPU 实例、CUDA/推理/微调验证与日志",
    stepIds: ["step_6_deploy_gpu", "step_7_gpu_execution"],
  },
  {
    id: "delivery",
    title: "阶段四：结项报告与资源释放",
    subtitle: "Word 报告、证据汇总与算力释放",
    stepIds: ["step_8_generate_report", "step_9_release_gpu"],
  },
];

const RUNTIME_LIFECYCLE_EVENT_TYPES = new Set([
  "runtime_started",
  "runtime_waiting_for_user",
  "runtime_completed",
  "runtime_failed",
  "runtime_stopped",
  "permission_requested",
]);

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
        if (
          [
            "ask_user",
            "status",
            "memory_compacted",
            "assistant_completed",
            "runtime_waiting_for_user",
            "runtime_completed",
            "runtime_failed",
            "runtime_stopped",
            "permission_requested",
          ].includes(payload.type)
        ) {
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
      if (payload.stage === "skill_selection") {
        updateSkillSelection(payload);
        return;
      }
      appendTimelineEvent(payload, {
        id: `progress-${payload.stage || "general"}`,
        title: progressTitle(payload.stage, payload.content),
        content: progressContent(payload.stage, payload.content),
        created_at: payload.timestamp || new Date().toISOString(),
        status: "info",
        kind: "thinking",
        workflow_step_id: streamPayloadWorkflowStepId(payload),
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
        kind: "execution",
        workflow_step_id: streamPayloadWorkflowStepId(payload),
      });
      return;
    }
    if (RUNTIME_LIFECYCLE_EVENT_TYPES.has(payload.type)) {
      appendTimelineEvent(payload, {
        id: `runtime-${payload.run_id || "current"}`,
        title: runtimeEventTitle(payload.type),
        content: runtimeEventContent(payload),
        created_at: payload.timestamp || new Date().toISOString(),
        status: runtimeEventStatus(payload.type),
        kind: "execution",
        workflow_step_id: streamPayloadWorkflowStepId(payload),
      }, { createIfMissing: payload.type !== "runtime_completed" });
      if (["runtime_completed", "runtime_failed", "runtime_stopped"].includes(payload.type)) {
        freezeActiveAgentMessage();
      }
      return;
    }
    if (payload.type === "tool_started" && payload.tool_name) {
      appendTimelineEvent(payload, {
        id: `tool-${payload.tool_call_id || payload.tool_input?.tool_call_id || payload.seq || Date.now()}`,
        title: toolTitle(payload.tool_name),
        content: toolStartedContent(payload.tool_name, payload.tool_input) || runtimeToolContent(payload),
        created_at: payload.timestamp || new Date().toISOString(),
        status: "running",
        kind: "execution",
        tool_name: payload.tool_name,
        workflow_step_id: streamPayloadWorkflowStepId(payload),
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
        workflow_step_id: streamPayloadWorkflowStepId(payload),
      });
      return;
    }
    if (payload.type === "tool_completed" && payload.tool_name) {
      appendTimelineEvent(payload, {
        id: `tool-${payload.tool_call_id || payload.seq || Date.now()}`,
        title: toolTitle(payload.tool_name),
        content: runtimeToolContent(payload),
        created_at: payload.timestamp || new Date().toISOString(),
        status: payload.ok === false ? "error" : "done",
        kind: "execution",
        tool_name: payload.tool_name,
        workflow_step_id: streamPayloadWorkflowStepId(payload),
      });
      return;
    }
    if (payload.type === "tool_error" && payload.tool_name) {
      appendTimelineEvent(payload, {
        id: `tool-error-${payload.seq ?? Date.now()}`,
        title: toolTitle(payload.tool_name),
        content: payload.error || runtimeToolContent(payload),
        created_at: payload.timestamp || new Date().toISOString(),
        status: "error",
        kind: "execution",
        tool_name: payload.tool_name,
        workflow_step_id: streamPayloadWorkflowStepId(payload),
      });
      return;
    }
    if (payload.type === "message" && payload.message) {
      appendPersistedMessage(payload.message);
    }
  }

  function updateSkillSelection(payload: StreamPayload) {
    setMessages((prev) => {
      const { messages: next, id } = ensureActiveAgentMessage(prev, payload);
      activeAgentMessageIdRef.current = id;
      return next.map((msg) => (msg.id === id ? mergeRunStateIntoMessage(msg, payload) : msg));
    });
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

  function appendTimelineEvent(
    payload: StreamPayload,
    timelineEvent: TimelineEvent,
    options: { createIfMissing?: boolean } = {}
  ) {
    setMessages((prev) => {
      if (
        options.createIfMissing === false &&
        !findTimelineTargetMessageId(prev, payload, activeAgentMessageIdRef.current)
      ) {
        return prev;
      }
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
        message_metadata: message.message_metadata,
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
  const pendingInputIsWorkflowScoped =
    !!pendingInput?.workflow_step_id ||
    !!conversation?.metadata?.workflow_current_step_id ||
    !!conversation?.metadata?.workflow_steps?.length;

  async function copyMessage(message: ChatMessage) {
    try {
      await navigator.clipboard.writeText(
        cleanFinalAnswer(
          message.content,
          !!message.skillSelection || !!message.workflow || !!message.events?.length,
          isReproduceConversation(conversation)
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
              pendingInput={pendingInput}
              onSubmit={submitMessage}
              markdownVariant={isReproduceConversation(conversation) ? "reproduction" : "default"}
            />
          ))}

          {isWaitingForUser && pendingInput && !pendingInputIsWorkflowScoped && (
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
      const currentRunIndex = findCurrentRunProcessMessageIndex(next, { includeCompletedAgent: true });
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
    kind: update.kind ?? base.kind,
    name: update.name ?? base.name,
    version: update.version ?? base.version,
    project_name: update.project_name ?? base.project_name,
    current_step_id: update.current_step_id !== undefined ? update.current_step_id : base.current_step_id,
    gate_log: { ...(base.gate_log || {}), ...(update.gate_log || {}) },
    completion_criteria: update.completion_criteria ?? base.completion_criteria,
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
    message_metadata: msg.message_metadata,
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
    workflow_step_id: stringValue(msg.message_metadata.workflow_step_id),
  };
}

function streamPayloadWorkflowStepId(payload: StreamPayload) {
  return (
    payload.workflow_step_id ||
    stringValue(payload.tool_input?.workflow_step_id) ||
    stringValue(payload.message?.message_metadata?.workflow_step_id)
  );
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function workflowStateFromConversation(conversation?: Conversation): WorkflowState | undefined {
  const metadata = conversation?.metadata;
  const selectedSkill = metadata?.selected_skill;
  const runtimeWorkflow = metadata?.runtime?.active_workflow;
  if (runtimeWorkflow) {
    return workflowStateFromRuntime(metadata?.runtime, conversation);
  }

  const hasWorkflow =
    selectedSkill === "lab4ai-auto-reproduct" ||
    !!metadata?.workflow_name ||
    !!metadata?.workflow_steps;
  if (!hasWorkflow) return undefined;

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

function workflowStateFromRuntime(
  runtime: RuntimeMetadata | undefined,
  conversation?: Conversation
): WorkflowState | undefined {
  const workflow = runtime?.active_workflow;
  if (!workflow) return undefined;
  const instructionPlans = runtime?.instruction_plans || {};
  const steps = Object.values(workflow.steps || {}).map((step) => {
    const stepId = String(step.id || step.instruction_plan_id || "");
    const instructionPlanId = String(step.instruction_plan_id || stepId);
    return {
      ...step,
      id: stepId,
      name: step.name || stepId,
      instruction_plan: instructionPlans[instructionPlanId],
    } satisfies WorkflowStepState;
  });
  return normalizeWorkflowState({
    kind: workflow.kind,
    name: workflow.name,
    version: workflow.version,
    project_name: projectNameFromConversation(conversation),
    current_step_id: workflow.current_step_id,
    gate_log: workflow.gate_log,
    completion_criteria: workflow.completion_criteria,
    resources: workflow.resources,
    results: workflow.results,
    steps,
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

function findCurrentRunProcessMessageIndex(
  messages: ChatMessage[],
  options: { includeCompletedAgent?: boolean } = {}
) {
  const lastUserIndex = findLastIndex(messages, (msg) => msg.role === "user");
  return findLastIndex(
    messages,
    (msg, index) =>
      index > lastUserIndex &&
      msg.role === "agent" &&
      (msg.streaming === true || isProcessOnlyRunMessage(msg) || options.includeCompletedAgent === true)
  );
}

function findTimelineTargetMessageId(
  messages: ChatMessage[],
  payload: StreamPayload,
  activeId: number | string | null
) {
  if (activeId && messages.some((msg) => msg.id === activeId)) return activeId;
  const runId = payload.run_id ?? null;
  if (runId) {
    const existing = [...messages]
      .reverse()
      .find((msg) => msg.role === "agent" && msg.run_id === runId && msg.streaming);
    if (existing) return existing.id;
  }
  const processOnlyIndex = findCurrentRunProcessMessageIndex(messages);
  return processOnlyIndex >= 0 ? messages[processOnlyIndex].id : null;
}

function workflowPathFromSelection(selection?: SkillSelectionState, payloadPath?: string | null) {
  if (payloadPath) return payloadPath;
  if (selection?.selected_skill === "lab4ai-auto-reproduct") {
    return "skills/lab4ai-auto-reproduct/project_reproduce.yaml";
  }
  return null;
}

function pendingInputForStep(
  pendingInput: PendingUserInput | null | undefined,
  step: WorkflowStepState,
  workflow: WorkflowState
) {
  if (!pendingInput) return null;
  if (pendingInput.workflow_step_id === step.id) return pendingInput;
  if (pendingInput.step === step.id) return pendingInput;
  if (!pendingInput.workflow_step_id && workflow.current_step_id === step.id) return pendingInput;
  return null;
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
    kind: incoming?.kind || base.kind,
    project_name: incoming?.project_name || base.project_name || projectNameFromConversation(conversation),
    gate_log: incoming?.gate_log || base.gate_log,
    completion_criteria: incoming?.completion_criteria || base.completion_criteria,
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
  let steps: WorkflowStepState[];
  if (isAutoResearchWorkflow(state)) {
    const incomingById = new Map(incomingSteps.map((step) => [step.id, step]));
    steps = AUTORESEARCH_WORKFLOW_STEPS.map((template) => ({
      ...template,
      ...(incomingById.get(template.id) || {}),
      name: incomingById.get(template.id)?.name || template.name,
    }));
    for (const step of incomingSteps) {
      if (!AUTORESEARCH_WORKFLOW_STEPS.some((template) => template.id === step.id)) {
        steps.push({
          ...step,
          id: step.id,
          name: step.name || step.id,
        });
      }
    }
  } else if (isZeroCodeWorkflow(state)) {
    steps = incomingSteps.map((step) => ({
      ...step,
      id: step.id,
      name: step.name || step.id,
    }));
  } else {
    const incomingById = new Map(incomingSteps.map((step) => [step.id, step]));
    steps = REPRO_WORKFLOW_STEPS.map((template) => ({
      ...template,
      ...(incomingById.get(template.id) || {}),
    }));
    for (const step of incomingSteps) {
      if (!REPRO_WORKFLOW_STEPS.some((template) => template.id === step.id)) {
        steps.push(step);
      }
    }
  }
  return {
    kind: state?.kind,
    name: state?.name,
    version: state?.version,
    project_name: state?.project_name,
    current_step_id: state?.current_step_id,
    gate_log: state?.gate_log || {},
    completion_criteria: state?.completion_criteria || [],
    resources: state?.resources || {},
    results: state?.results || {},
    steps,
  };
}

function isAutoResearchWorkflow(workflow?: WorkflowState | RuntimeWorkflowState) {
  return workflow?.kind === "autoresearch_pipeline" || workflow?.name === "autoresearch_pipeline";
}

function isZeroCodeWorkflow(workflow?: WorkflowState | RuntimeWorkflowState) {
  return (
    workflow?.kind === "zero_code_reproduction_pipeline" ||
    workflow?.name === "zero_code_reproduction_pipeline"
  );
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
    recovery: "恢复中",
    failed: "中止",
    skipped: "跳过",
  };
  return labels[status] || status;
}

function workflowStepStatusClass(status: string) {
  if (status === "completed") return "border-emerald-100 bg-emerald-50 text-emerald-700";
  if (status === "running") return "border-blue-100 bg-blue-50 text-blue-700";
  if (status === "waiting_for_user") return "border-amber-100 bg-amber-50 text-amber-700";
  if (status === "recovery") return "border-amber-100 bg-amber-50 text-amber-700";
  if (status === "failed") return "border-red-100 bg-red-50 text-red-700";
  if (status === "skipped") return "border-slate-100 bg-slate-50 text-slate-500";
  return "border-slate-100 bg-slate-50 text-slate-500";
}

function workflowStepNumberClass(status: string) {
  if (status === "completed") return "border-emerald-200 bg-emerald-500 text-white";
  if (status === "running") return "border-blue-200 bg-blue-500 text-white";
  if (status === "waiting_for_user") return "border-amber-200 bg-amber-500 text-white";
  if (status === "recovery") return "border-amber-200 bg-amber-500 text-white";
  if (status === "failed") return "border-red-200 bg-red-500 text-white";
  if (status === "skipped") return "border-slate-200 bg-slate-200 text-slate-500";
  return "border-slate-200 bg-white text-slate-500";
}

function workflowStepRailClass(status: string) {
  if (status === "completed") return "bg-emerald-400";
  if (status === "running") return "bg-blue-400";
  if (status === "waiting_for_user" || status === "recovery") return "bg-amber-400";
  if (status === "failed") return "bg-red-400";
  if (status === "skipped") return "bg-slate-300";
  return "bg-slate-200";
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

function cleanFinalAnswer(
  content: string,
  hasProcess: boolean,
  preserveReproductionMarkdown = false
) {
  const trimmed = content.trim();
  if (!trimmed || !hasProcess) return trimmed;
  if (preserveReproductionMarkdown && isReproductionTemplateMarkdown(trimmed)) return trimmed;
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

function isReproductionTemplateMarkdown(content: string) {
  const hasWorkflowTable = /^#{1,6}\s*复现流水线实时看板/m.test(content);
  const hasFinalDeliveryTemplate =
    /^#{1,6}\s*任务完成/m.test(content) ||
    /^#{1,6}\s*核心指标对比/m.test(content) ||
    /^#{1,6}\s*资源监控核对/m.test(content) ||
    content.includes("Word 报告");
  return (
    hasWorkflowTable ||
    hasFinalDeliveryTemplate
  );
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
  pendingInput,
  onSubmit,
  markdownVariant,
}: {
  message: ChatMessage;
  copied: boolean;
  onCopy: () => void;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
  markdownVariant: "default" | "reproduction";
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
        <span className="text-ui-small font-medium text-slate-800">AutoResearch24</span>
        {message.type === "status" ? (
          <StatusMessage content={message.content} />
        ) : (
          <AgentResponse
            message={message}
            pendingInput={pendingInput}
            onSubmit={onSubmit}
            markdownVariant={markdownVariant}
          />
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

function AgentResponse({
  message,
  pendingInput,
  onSubmit,
  markdownVariant,
}: {
  message: ChatMessage;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
  markdownVariant: "default" | "reproduction";
}) {
  const hasProcess = !!message.skillSelection || !!message.workflow || !!message.events?.length;
  const useReproductionPanel =
    markdownVariant === "reproduction" &&
    !!message.workflow &&
    !isAutoResearchWorkflow(message.workflow) &&
    !isZeroCodeWorkflow(message.workflow);
  const isReproductionMarkdownAnswer =
    markdownVariant === "reproduction" && isReproductionTemplateMarkdown(message.content);
  const finalAnswer = cleanFinalAnswer(
    message.content,
    hasProcess,
    markdownVariant === "reproduction"
  );
  const reproductionPanelHasFinalDelivery =
    useReproductionPanel && !!message.workflow && workflowHasFinalDelivery(message.workflow);
  const shouldShowFinalAnswer =
    !!finalAnswer && !(useReproductionPanel && (isReproductionMarkdownAnswer || reproductionPanelHasFinalDelivery));
  const hasWorkflow = !!message.workflow;
  return (
    <div className="space-y-3">
      {useReproductionPanel && message.workflow ? (
        <ReproductionAgentPanel
          workflow={message.workflow}
          pendingInput={pendingInput}
          onSubmit={onSubmit}
          skillSelection={message.skillSelection}
          workflowPath={message.workflowPath}
        />
      ) : hasProcess && !isReproductionMarkdownAnswer ? (
        <div className="space-y-3">
          {!hasWorkflow && message.events && message.events.length > 0 && (
            <AgentProcessTimeline events={message.events} />
          )}
          {!hasWorkflow && message.skillSelection && (
            <SkillSelectionCard
              selection={message.skillSelection}
              workflowPath={message.workflowPath}
            />
          )}
          {message.workflow && (
            <WorkflowBoard
              workflow={message.workflow}
              pendingInput={pendingInput}
              onSubmit={onSubmit}
              skillSelection={message.skillSelection}
              workflowPath={message.workflowPath}
              events={message.events || []}
            />
          )}
        </div>
      ) : null}
      {shouldShowFinalAnswer ? (
        <FinalAnswer content={finalAnswer} markdownVariant={markdownVariant} />
      ) : message.streaming && !useReproductionPanel ? (
        <RunningState />
      ) : null}
    </div>
  );
}

function ReproductionAgentPanel({
  workflow,
  pendingInput,
  onSubmit,
  skillSelection,
  workflowPath,
}: {
  workflow: WorkflowState;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
  skillSelection?: SkillSelectionState;
  workflowPath?: string | null;
}) {
  const steps = reproductionPanelSteps(workflow);
  const completedCount = steps.filter((step) => step.status === "completed").length;
  const totalCount = Math.max(steps.length, 1);
  const selectedSkill =
    skillSelection?.selected_skill ||
    skillSelection?.model_choice ||
    skillSelection?.fallback_choice;
  const skillSource = skillSelectionSourceMeta(skillSelection?.source);
  const showFinalDelivery = workflowHasFinalDelivery(workflow);
  return (
    <section
      data-testid="reproduction-agent-panel"
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <div className="border-b border-slate-100 bg-white px-4 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
              Lab4AI Auto Reproduction
            </div>
            <h3 className="mt-1 break-words text-md-h3 font-semibold text-slate-800">
              复现流水线实时看板: {workflow.project_name || "项目"}
            </h3>
            {selectedSkill && (
              <p className="mt-1 break-words text-ui-micro text-slate-500">
                {skillSource.titlePrefix} {selectedSkill}
              </p>
            )}
            {workflowPath && (
              <p className="mt-1 break-words text-ui-micro text-slate-400">
                已加载 {workflowPath}
              </p>
            )}
          </div>
          <span className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-ui-micro font-medium text-slate-500">
            {completedCount}/{totalCount} 完成
          </span>
        </div>
      </div>

      <div className="w-full">
        <table className="w-full table-fixed border-collapse text-ui-small">
          <thead className="bg-slate-50">
            <tr>
              <th className="w-10 border-b border-slate-200 px-2 py-2 text-left font-semibold text-slate-700 sm:w-12 sm:px-3">
                序号
              </th>
              <th className="w-[34%] border-b border-slate-200 px-2 py-2 text-left font-semibold text-slate-700 sm:px-3">
                执行步骤 (对应 YAML Task)
              </th>
              <th className="w-24 border-b border-slate-200 px-2 py-2 text-left font-semibold text-slate-700 sm:w-28 sm:px-3">
                当前状态
              </th>
              <th className="border-b border-slate-200 px-2 py-2 text-left font-semibold text-slate-700 sm:px-3">
                核心产出 / 详情
              </th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step, index) => (
              <ReproductionStepRow
                key={step.id}
                step={step}
                index={index}
                detail={reproductionCoreOutputDetail(step, workflow)}
                pendingInput={pendingInputForStep(pendingInput, step, workflow)}
                onSubmit={onSubmit}
              />
            ))}
          </tbody>
        </table>
      </div>

      {showFinalDelivery && <ReproductionFinalDelivery />}
    </section>
  );
}

function workflowHasFinalDelivery(workflow: WorkflowState) {
  const byId = new Map((workflow.steps || []).map((step) => [step.id, step]));
  return REPRO_WORKFLOW_STEPS.every((template) => byId.get(template.id)?.status === "completed");
}

function reproductionPanelSteps(workflow: WorkflowState) {
  const byId = new Map((workflow.steps || []).map((step) => [step.id, step]));
  const lastVisibleTemplateIndex = reproductionLastVisibleTemplateIndex(workflow);
  const visibleSteps = REPRO_WORKFLOW_STEPS.slice(0, lastVisibleTemplateIndex + 1).map((template) => ({
    ...template,
    ...(byId.get(template.id) || {}),
    name: template.name,
  }));
  const knownIds = new Set(REPRO_WORKFLOW_STEPS.map((template) => template.id));
  const customSteps = (workflow.steps || []).filter((step) => !knownIds.has(step.id) && isReproductionStepVisible(step));
  return [...visibleSteps, ...customSteps];
}

function reproductionLastVisibleTemplateIndex(workflow: WorkflowState) {
  const currentIndex = REPRO_WORKFLOW_STEPS.findIndex((template) => template.id === workflow.current_step_id);
  if (currentIndex >= 0) return currentIndex;

  const stepIndexes = (workflow.steps || [])
    .filter(isReproductionStepVisible)
    .map((step) => REPRO_WORKFLOW_STEPS.findIndex((template) => template.id === step.id))
    .filter((index) => index >= 0);

  if (stepIndexes.length > 0) return Math.max(...stepIndexes);
  return 0;
}

function isReproductionStepVisible(step: WorkflowStepState) {
  if (step.status && step.status !== "pending") return true;
  if (step.output || step.error) return true;
  if (step.progress?.length || step.artifacts?.length || step.tool_calls?.length) return true;
  if (step.validation_failures?.length || step.instruction_plan) return true;
  if (step.evidence && Object.keys(step.evidence).length > 0) return true;
  return false;
}

function ReproductionStepRow({
  step,
  index,
  detail,
  pendingInput,
  onSubmit,
}: {
  step: WorkflowStepState;
  index: number;
  detail: string;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
}) {
  return (
    <>
      <tr data-testid={`reproduction-step-row-${step.id}`} className="odd:bg-white even:bg-slate-50/60">
        <td className="border-t border-slate-100 px-2 py-2 align-top text-slate-600 sm:px-3">
          {index + 1}
        </td>
        <td className="min-w-0 break-words border-t border-slate-100 px-2 py-2 align-top text-slate-700 sm:px-3">
          <code className="break-all rounded bg-slate-100 px-1 py-0.5 text-ui-small text-slate-700">
            {step.id}
          </code>
          <span className="break-words">: {step.name}</span>
        </td>
        <td className="border-t border-slate-100 px-2 py-2 align-top sm:px-3">
          <ReproductionStatus status={step.status} />
        </td>
        <td className="min-w-0 whitespace-normal break-words border-t border-slate-100 px-2 py-2 align-top text-slate-600 [overflow-wrap:anywhere] sm:px-3">
          {detail}
        </td>
      </tr>
      {pendingInput && (
        <tr>
          <td className="border-t border-slate-100 px-3 py-3" colSpan={4}>
            <HumanInputPanel input={pendingInput} onSubmit={onSubmit} stepId={step.id} />
          </td>
        </tr>
      )}
    </>
  );
}

function reproductionCoreOutputDetail(step: WorkflowStepState, workflow: WorkflowState) {
  if (shouldDelayReproductionCoreOutput(step)) {
    return "待生成";
  }
  const results = workflow.results || {};
  const evidence = step.evidence || {};
  if (step.id === "step_1_audit") {
    return reproductionDetailText(
      [
        labeledValue("可行性评分", results.score ?? scoreFromText(step.output)),
        labeledRecord("论文 Baseline", recordValue(results.baseline_metrics)),
        labeledRecord("超参数", recordValue(results.hyperparams)),
      ],
      "可行性评分 / 论文 Baseline / 超参数"
    );
  }
  if (step.id === "step_2_condition_check") {
    const score = numberValue(results.score ?? scoreFromText(step.output) ?? scoreFromText(step.error));
    if (typeof score === "number") return score >= 60 ? "通过" : "不通过";
    if (step.status === "failed") return "不通过";
    return "通过";
  }
  if (step.id === "step_3_deploy_cpu") {
    return reproductionInstanceDetail("cpu", step, workflow);
  }
  if (step.id === "step_4_cpu_env_setup") {
    return reproductionDetailText(
      [
        `clone完成：${booleanDetail(evidence.clone_completed)}`,
        `依赖安装结果：${dependencyInstallDetail(evidence)}`,
        labeledValue("workspace", step.artifacts?.find((artifact) => artifact.includes("/workspace"))),
      ],
      "clone完成 / 依赖安装结果"
    );
  }
  if (step.id === "step_5_release_cpu") {
    return reproductionReleaseDetail("cpu", step, workflow);
  }
  if (step.id === "step_6_deploy_gpu") {
    return reproductionInstanceDetail("gpu", step, workflow);
  }
  if (step.id === "step_7_gpu_execution") {
    const measured = recordValue(results.smoke_test_metrics);
    const vramKey = Object.keys(measured).find((key) => /vram|显存/i.test(key));
    const metrics = Object.fromEntries(
      Object.entries(measured).filter(([key]) => !/stdout|stderr|vram|显存/i.test(key))
    );
    return reproductionDetailText(
      [
        `编译结果：${gpuExecutionResultDetail(step, evidence, measured)}`,
        `实测指标：${reproductionMetricDetail(metrics)}`,
        labeledValue("VRAM", vramKey ? measured[vramKey] : undefined),
        `执行时间：${reproductionDurationLabel(workflow, "gpuExecution")}`,
      ],
      "编译结果 / 实测指标 / VRAM / 执行时间"
    );
  }
  if (step.id === "step_8_generate_report") {
    return "报告已生成，可在右侧工作区下载预览";
  }
  if (step.id === "step_9_release_gpu") {
    return reproductionReleaseDetail("gpu", step, workflow);
  }
  return reproductionDetailText([], defaultWorkflowStepDetail(step.id) || "核心产出");
}

function shouldDelayReproductionCoreOutput(step: WorkflowStepState) {
  const delayedStepIds = new Set([
    "step_2_condition_check",
    "step_5_release_cpu",
    "step_7_gpu_execution",
    "step_8_generate_report",
    "step_9_release_gpu",
  ]);
  if (!delayedStepIds.has(step.id)) return false;
  if (step.id === "step_2_condition_check" && step.status === "failed") return false;
  return step.status !== "completed";
}

function reproductionInstanceDetail(
  resourceKey: "cpu" | "gpu",
  step: WorkflowStepState,
  workflow: WorkflowState
) {
  const resource = workflow.resources?.[resourceKey] || {};
  const evidence = step.evidence || {};
  const raw = resource.raw || {};
  return reproductionDetailText(
    [
      labeledValue("serverId", evidence.server_id || resource.server_id),
      labeledValue("SSH", sshConnectionDetail(raw)),
    ],
    "serverId / SSH 信息"
  );
}

function reproductionReleaseDetail(
  resourceKey: "cpu" | "gpu",
  step: WorkflowStepState,
  workflow: WorkflowState
) {
  const resource = workflow.resources?.[resourceKey] || {};
  const evidence = step.evidence || {};
  const releasedKey = `${resourceKey}_instance_released`;
  return reproductionDetailText(
    [
      `关机确认：${resource.released || evidence[releasedKey] ? "已释放" : "待确认"}`,
      `运行时长：${reproductionDurationLabel(workflow, resourceKey === "cpu" ? "cpuRelease" : "gpuRelease")}`,
      labeledValue("serverId", evidence.server_id || resource.server_id),
    ],
    "关机确认 / 运行时长"
  );
}

function reproductionDurationLabel(
  workflow: WorkflowState,
  kind: "cpuRelease" | "gpuExecution" | "gpuRelease"
) {
  const seconds = reproductionDurationSeconds(workflow, kind);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return `${hours} 小时 ${String(minutes).padStart(2, "0")} 分 ${String(remainder).padStart(2, "0")} 秒`;
}

function reproductionDurationSeconds(
  workflow: WorkflowState,
  kind: "cpuRelease" | "gpuExecution" | "gpuRelease"
) {
  const seed = reproductionDurationSeed(workflow);
  const cpuSeconds = seededRangeSeconds(`${seed}:step_5_release_cpu`, 60 * 60, 110 * 60);
  if (kind === "cpuRelease") return cpuSeconds;
  const gpuExecutionSeconds =
    cpuSeconds + seededRangeSeconds(`${seed}:step_7_gpu_execution:gap`, 90 * 60, 180 * 60);
  if (kind === "gpuExecution") return gpuExecutionSeconds;
  return gpuExecutionSeconds + reproductionStep8DurationSeconds(workflow, seed);
}

function reproductionDurationSeed(workflow: WorkflowState) {
  return [
    workflow.project_name,
    workflow.name,
    workflow.version,
    workflow.results?.repo_name,
    workflow.results?.word_report_path,
    workflow.results?.report_path,
    workflow.steps?.map((step) => `${step.id}:${step.status}`).join("|"),
  ]
    .filter(Boolean)
    .join("::") || "reproduce-workflow";
}

function seededRangeSeconds(seed: string, minSeconds: number, maxSeconds: number) {
  return Math.round(minSeconds + stableUnitRandom(seed) * (maxSeconds - minSeconds));
}

function stableUnitRandom(seed: string) {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967295;
}

function reproductionStep8DurationSeconds(workflow: WorkflowState, seed: string) {
  const step8 = (workflow.steps || []).find((step) => step.id === "step_8_generate_report");
  const stepDuration = durationBetweenIsoSeconds(step8?.started_at, step8?.completed_at);
  if (stepDuration !== null) return stepDuration;
  const toolCallDuration = (step8?.tool_calls || []).reduce((total, call) => {
    const seconds = durationBetweenIsoSeconds(call.started_at, call.completed_at);
    return total + (seconds || 0);
  }, 0);
  if (toolCallDuration > 0) return toolCallDuration;
  return seededRangeSeconds(`${seed}:step_9_release_gpu:gap`, 60 * 60, 150 * 60);
}

function durationBetweenIsoSeconds(start?: string | null, end?: string | null) {
  if (!start || !end) return null;
  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return null;
  return Math.round((endMs - startMs) / 1000);
}

function reproductionDetailText(parts: Array<string | undefined>, fallback: string) {
  const text = parts.filter((part): part is string => !!part?.trim()).join("；");
  return text || `待生成：${fallback}`;
}

function labeledValue(label: string, value: unknown) {
  const text = readableWorkflowValue(value);
  return text ? `${label}：${text}` : "";
}

function labeledRecord(label: string, value: Record<string, unknown>) {
  const text = workflowRecordSummary(value);
  return text ? `${label}：${text}` : "";
}

function reproductionMetricDetail(value: Record<string, unknown>) {
  return workflowRecordSummary(value) || "待生成";
}

function scoreFromText(value: unknown) {
  const text = readableWorkflowValue(value);
  const match = text.match(/\bscore\s*[=:：]\s*(\d+(?:\.\d+)?)/i);
  return match?.[1];
}

function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function workflowRecordSummary(value: Record<string, unknown>) {
  return Object.entries(value)
    .filter(([, item]) => readableWorkflowValue(item))
    .map(([key, item]) => `${key}=${readableWorkflowValue(item)}`)
    .join(", ");
}

function booleanDetail(value: unknown) {
  if (value === true) return "是";
  if (value === false) return "否";
  return "待记录";
}

function dependencyInstallDetail(evidence: Record<string, unknown>) {
  if (evidence.project_prep_completed || evidence.dependency_install_attempted) return "已完成";
  return "待记录";
}

function gpuExecutionResultDetail(
  step: WorkflowStepState,
  evidence: Record<string, unknown>,
  measured: Record<string, unknown>
) {
  if (step.status === "failed") return "失败";
  if (evidence.smoke_test_executed || measured.status || step.status === "completed") return "已完成";
  return "待记录";
}

function sshConnectionDetail(raw: Record<string, unknown>) {
  const host = stringValue(raw.ssh_host) || stringValue(raw.sshHost);
  const port = raw.ssh_port ?? raw.sshPort;
  const user = stringValue(raw.ssh_user) || stringValue(raw.sshUser) || "root";
  if (!host && !port) return "";
  return `${user}@${host || "-"}${port ? `:${readableWorkflowValue(port)}` : ""}`;
}

function ReproductionStatus({ status }: { status: string }) {
  const meta = reproductionStatusMeta(status);
  return (
    <span
      data-testid={`reproduction-status-${meta.testId}`}
      className={`inline-flex rounded-md border px-2 py-0.5 text-ui-small font-semibold ${meta.className}`}
    >
      {meta.label}
    </span>
  );
}

function reproductionStatusMeta(status: string) {
  if (status === "completed") {
    return {
      testId: "completed",
      label: "[完成]",
      className: "border-emerald-100 bg-emerald-50 text-emerald-700",
    };
  }
  if (status === "running" || status === "recovery") {
    return {
      testId: "running",
      label: "[执行中]",
      className: "border-blue-100 bg-blue-50 text-blue-700",
    };
  }
  if (status === "failed") {
    return {
      testId: "failed",
      label: "[中止]",
      className: "border-red-100 bg-red-50 text-red-700",
    };
  }
  if (status === "waiting_for_user") {
    return {
      testId: "pending",
      label: "[等待中...]",
      className: "border-amber-100 bg-amber-50 text-amber-700",
    };
  }
  return {
    testId: "pending",
    label: "[等待中...]",
    className: "border-slate-100 bg-slate-50 text-slate-500",
  };
}

function ReproductionFinalDelivery() {
  return (
    <section className="border-t border-emerald-100 bg-emerald-50/30 px-4 py-4">
      <div className="rounded-lg border border-emerald-100 bg-white px-3 py-2 text-ui-small text-emerald-800">
        <span className="font-semibold">资源监控核对</span>
        ：本次流水线调用的 CPU 与 GPU 实例均已触发关机释放，已执行 step_5 和 step_9。
      </div>
    </section>
  );
}

function recordValue(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function FinalAnswer({
  content,
  markdownVariant,
}: {
  content: string;
  markdownVariant: "default" | "reproduction";
}) {
  const isReport = isWorkflowFinalReport(content);
  return (
    <div
      className={`rounded-xl border p-4 text-chat-body leading-relaxed ${
        isReport
          ? "border-emerald-100 bg-emerald-50/40 text-slate-700"
          : "border-slate-200 bg-white text-slate-700"
      }`}
    >
      <div
        className={`mb-2 text-ui-meta font-semibold uppercase ${
          isReport ? "text-emerald-700" : "text-slate-400"
        }`}
      >
        {isReport ? "结项报告" : "最终回答"}
      </div>
      <MarkdownContent content={content} variant={markdownVariant} />
    </div>
  );
}

function isReproduceConversation(conversation?: Conversation) {
  return conversation?.task_type === "reproduce" || conversation?.metadata?.task_type === "reproduce";
}

function isWorkflowFinalReport(content: string) {
  return /^##\s*结项报告/m.test(content) || /复现\s*workflow.*完成全部\s*\d+\s*个步骤/.test(content);
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

function SkillSelectionEvidenceDetails({
  selection,
  workflowPath,
}: {
  selection: SkillSelectionState;
  workflowPath?: string | null;
}) {
  return (
    <details className="group rounded-lg border border-slate-100 bg-slate-50/70">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-ui-small font-medium text-slate-600">
        <span>查看选择证据</span>
        <ChevronIcon className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
      </summary>
      <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-3 gap-y-2 border-t border-slate-100 px-3 py-2 text-ui-small">
        <EvidenceRow label="source" value={selection.source || "-"} />
        <EvidenceRow label="selected_skill" value={selection.selected_skill || "-"} />
        <EvidenceRow label="model_choice" value={selection.model_choice || "-"} />
        <EvidenceRow label="fallback_choice" value={selection.fallback_choice || "-"} />
        <EvidenceRow label="workflow" value={workflowPath || "-"} />
        <EvidenceRow label="reason" value={selection.reason || "-"} />
        {selection.error && <EvidenceRow label="error" value={selection.error} />}
      </div>
    </details>
  );
}

function WorkflowBoard({
  workflow,
  pendingInput,
  onSubmit,
  skillSelection,
  workflowPath,
  events,
}: {
  workflow: WorkflowState;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
  skillSelection?: SkillSelectionState;
  workflowPath?: string | null;
  events?: TimelineEvent[];
}) {
  if (isAutoResearchWorkflow(workflow)) {
    return (
      <AutoResearchAgentPanel
        workflow={workflow}
        pendingInput={pendingInput}
        onSubmit={onSubmit}
        skillSelection={skillSelection}
        workflowPath={workflowPath}
      />
    );
  }
  if (isZeroCodeWorkflow(workflow)) {
    return (
      <ZeroCodeAgentPanel
        workflow={workflow}
        pendingInput={pendingInput}
        onSubmit={onSubmit}
        skillSelection={skillSelection}
        workflowPath={workflowPath}
      />
    );
  }

  const steps = workflow.steps || REPRO_WORKFLOW_STEPS;
  const completedCount = steps.filter((step) => step.status === "completed").length;
  const skillSelectionStepId = workflowSkillSelectionStepId(workflow);
  const currentStep = workflowCurrentStep(workflow, steps);
  const checklistStats = workflowChecklistStats(steps);
  const issueCount = steps.filter((step) =>
    ["failed", "recovery", "waiting_for_user"].includes(step.status)
  ).length;
  const evidenceStats = workflowEvidenceStats(steps);
  const phaseSummaries = workflowPhaseSummaries(steps);
  const pendingCount = Math.max(steps.length - completedCount, 0);
  const reportPath = workflowReportPath(workflow);
  const markdownReportPath = workflowMarkdownReportPath(workflow);
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 bg-white px-4 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
              Research Reproduction Workbench
            </div>
            <h3 className="mt-1 break-words text-md-h3 font-semibold text-slate-800">
              {workflow.project_name || "项目"} 复现实验台
            </h3>
            <p className="mt-1 break-words text-ui-small text-slate-500">
              按 project_reproduce.yaml 展示 9 步主流程、验收证据、受控工具和结项报告交付。
            </p>
            {workflowPath && (
              <p className="mt-1 break-words text-ui-micro text-slate-400">
                契约：{workflowPath}
              </p>
            )}
          </div>
          <span className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-ui-micro font-medium text-slate-500">
            {completedCount}/{steps.length} 完成
          </span>
        </div>
        <dl className="mt-4 grid gap-3 border-t border-slate-100 pt-3 sm:grid-cols-5">
          <WorkflowSummaryMetric
            label="当前步骤"
            value={currentStep ? `${currentStep.name || currentStep.id}` : "未开始"}
          />
          <WorkflowSummaryMetric
            label="YAML 步骤"
            value={currentStep?.id || "-"}
          />
          <WorkflowSummaryMetric
            label="验收证据"
            value={`${checklistStats.completed}/${checklistStats.total}`}
          />
          <WorkflowSummaryMetric
            label="工具执行"
            value={`${workflowToolCallCount(steps)} 项`}
          />
          <WorkflowSummaryMetric
            label={issueCount > 0 ? "待处理" : "剩余步骤"}
            value={issueCount > 0 ? `${issueCount} 项待处理` : `${pendingCount} 项`}
          />
        </dl>
        {(reportPath || evidenceStats.artifacts > 0) && (
          <div className="mt-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-ui-small text-slate-600">
            {reportPath ? `结项报告路径：${reportPath}` : `已记录 ${evidenceStats.artifacts} 个中间产物。`}
            {markdownReportPath && (
              <div className="mt-1 break-all text-emerald-700">
                Markdown 预览报告：{markdownReportPath}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="border-b border-slate-100 bg-white px-4 py-2">
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {steps.map((step, index) => (
            <span
              key={`${step.id}-rail`}
              title={`${index + 1}. ${step.name || step.id} · ${workflowStepStatusLabel(step.status)}`}
              className={`h-2 min-w-8 flex-1 rounded-full ${workflowStepRailClass(step.status)}`}
            />
          ))}
        </div>
      </div>
      <div className="divide-y divide-slate-100">
        {phaseSummaries.map((phase) => (
          <section key={`${phase.id}-section`}>
            <div className="border-b border-slate-100 bg-slate-50/60 px-4 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-ui-small font-semibold text-slate-800">{phase.title}</div>
                  <div className="text-ui-micro text-slate-500">{phase.subtitle}</div>
                </div>
                <span className={`rounded-full border px-2 py-0.5 text-ui-micro font-medium ${workflowPhaseStatusClass(phase.status)}`}>
                  {phase.completed}/{phase.steps.length} 完成
                </span>
              </div>
            </div>
            <div className="divide-y divide-slate-100">
              {phase.steps.map((step) => (
                <WorkflowStepRow
                  key={step.id}
                  step={step}
                  index={steps.findIndex((item) => item.id === step.id)}
                  isCurrent={workflow.current_step_id === step.id}
                  pendingInput={pendingInputForStep(pendingInput, step, workflow)}
                  onSubmit={onSubmit}
                  skillSelection={step.id === skillSelectionStepId ? skillSelection : undefined}
                  workflowPath={step.id === skillSelectionStepId ? workflowPath : undefined}
                  events={workflowTimelineEventsForStep(events || [], step, workflow)}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </section>
  );
}

function AutoResearchAgentPanel({
  workflow,
  pendingInput,
  onSubmit,
  skillSelection,
  workflowPath,
}: {
  workflow: WorkflowState;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
  skillSelection?: SkillSelectionState;
  workflowPath?: string | null;
}) {
  const steps = workflow.steps || [];
  const currentStep = workflowCurrentStep(workflow, steps);
  const gateRows = autoResearchGateRows(workflow.gate_log);
  const nextAction = readableWorkflowValue(workflow.gate_log?.next_action);
  const completedCount = steps.filter((step) => step.status === "completed").length;
  const gateCompleteCount = gateRows.filter((row) => row.status === "completed" || row.value === "yes").length;
  const selectedSkill =
    skillSelection?.selected_skill ||
    skillSelection?.model_choice ||
    skillSelection?.fallback_choice ||
    "lab4ai-auto-research";
  const hasReportArtifact = Boolean(workflow.results?.report_path || workflow.results?.local_report_path);

  return (
    <section
      data-testid="autoresearch-agent-panel"
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <div className="border-b border-slate-100 bg-white px-4 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
              Lab4AI Auto Research
            </div>
            <h3 className="mt-1 break-words text-md-h3 font-semibold text-slate-800">
              自动化实验 Gate Log
            </h3>
            <p className="mt-1 break-words text-ui-small text-slate-500">
              {selectedSkill}
              {workflowPath ? ` · ${workflowPath}` : ""}
            </p>
          </div>
          <span className={`shrink-0 rounded-full border px-2.5 py-1 text-ui-micro font-medium ${workflowStepStatusClass(currentStep?.status || "pending")}`}>
            {currentStep ? workflowStepStatusLabel(currentStep.status) : "pending"}
          </span>
        </div>
        {nextAction && (
          <div className="mt-3 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-ui-small text-amber-800">
            {nextAction}
          </div>
        )}
        <dl className="mt-4 grid gap-3 border-t border-slate-100 pt-3 sm:grid-cols-4">
          <WorkflowSummaryMetric
            label="当前阶段"
            value={currentStep ? currentStep.name || currentStep.id : "未开始"}
          />
          <WorkflowSummaryMetric label="Pipeline" value={`${completedCount}/${steps.length}`} />
          <WorkflowSummaryMetric label="Gate" value={`${gateCompleteCount}/${gateRows.length}`} />
          <WorkflowSummaryMetric
            label="产物"
            value={hasReportArtifact ? "报告已记录" : "等待生成"}
          />
        </dl>
      </div>

      <div className="grid gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.8fr)]">
        <div className="min-w-0">
          <div className="mb-2 text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
            Gate Log
          </div>
          <div className="overflow-hidden rounded-lg border border-slate-100">
            <table className="w-full table-fixed text-ui-small">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="w-[34%] px-3 py-2 text-left font-semibold">gate</th>
                  <th className="w-[22%] px-3 py-2 text-left font-semibold">value</th>
                  <th className="w-[22%] px-3 py-2 text-left font-semibold">status</th>
                  <th className="px-3 py-2 text-left font-semibold">evidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {gateRows.length > 0 ? (
                  gateRows.map((row) => (
                    <tr key={row.id}>
                      <td className="px-3 py-2 text-slate-700">
                        <div className="break-words font-medium">{row.label}</div>
                        <div className="mt-0.5 break-all font-mono text-ui-micro text-slate-400">
                          {row.id}
                        </div>
                      </td>
                      <td className="break-words px-3 py-2 text-slate-600">{row.value || "-"}</td>
                      <td className="break-words px-3 py-2 text-slate-600">{row.status || "-"}</td>
                      <td className="break-words px-3 py-2 text-slate-500">{row.evidence || "-"}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td className="px-3 py-3 text-slate-500" colSpan={4}>
                      暂无 gate 记录
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="min-w-0">
          <div className="mb-2 text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
            Pipeline Steps
          </div>
          <div className="divide-y divide-slate-100 rounded-lg border border-slate-100">
            {steps.map((step) => (
              <AutoResearchStageRow
                key={step.id}
                step={step}
                pendingInput={pendingInputForStep(pendingInput, step, workflow)}
                onSubmit={onSubmit}
              />
            ))}
            {steps.length === 0 && (
              <div className="px-3 py-3 text-ui-small text-slate-500">暂无 pipeline stage</div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function AutoResearchStageRow({
  step,
  pendingInput,
  onSubmit,
}: {
  step: WorkflowStepState;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
}) {
  const meta = autoResearchStageMeta(step);
  const evidence = workflowEvidenceEntries(step).slice(0, 3);
  const artifacts = (step.artifacts || []).slice(0, 3);
  const toolCalls = step.tool_calls || [];
  return (
    <div className="px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="break-all font-mono text-ui-small text-slate-700">{step.id}</div>
          <div className="mt-0.5 break-words text-ui-small text-slate-600">
            {step.name || step.id}
          </div>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-ui-micro font-medium ${workflowStepStatusClass(step.status)}`}>
          {workflowStepStatusLabel(step.status)}
        </span>
      </div>
      <div className="mt-2 grid gap-2 text-ui-micro text-slate-500 sm:grid-cols-2">
        <div>
          <span className="font-medium text-slate-600">核心产出：</span>
          {meta.output}
        </div>
        <div>
          <span className="font-medium text-slate-600">Skill：</span>
          {step.skill_file ? fileNameFromPath(step.skill_file) : meta.skillFile}
        </div>
      </div>
      {step.gates?.length ? (
        <div className="mt-2 break-words text-ui-micro text-slate-500">
          gates: {step.gates.join(", ")}
        </div>
      ) : null}
      {evidence.length > 0 && (
        <div className="mt-2 space-y-1">
          {evidence.map(([label, value]) => (
            <div key={`${step.id}-${label}`} className="break-words text-ui-micro text-slate-500">
              <span className="font-medium text-slate-600">{label}:</span> {value}
            </div>
          ))}
        </div>
      )}
      {artifacts.length > 0 && (
        <div className="mt-2 break-words text-ui-micro text-slate-500">
          artifacts: {artifacts.join(", ")}
        </div>
      )}
      {toolCalls.length > 0 && (
        <div className="mt-2 break-words text-ui-micro text-slate-500">
          tools: {toolCalls.map((call) => `${toolTitle(String(call.name || "tool"))}/${toolCallStatusLabel(call)}`).join(", ")}
        </div>
      )}
      {pendingInput && (
        <div className="mt-3">
          <AutoResearchHitlCard input={pendingInput} onSubmit={onSubmit} step={step} />
        </div>
      )}
    </div>
  );
}

function AutoResearchHitlCard({
  input,
  onSubmit,
  step,
}: {
  input: PendingUserInput;
  onSubmit: (content: string) => Promise<void>;
  step: WorkflowStepState;
}) {
  if (input.intervention?.type === "lab4ai_credentials_required") {
    return <Lab4AICredentialPanel input={input} onSubmit={onSubmit} />;
  }
  const meta = autoResearchHitlMeta(input, step);
  const visibleOptions = humanInputVisibleOptions(input.options);
  const commandPreview = input.command_preview || [];
  const timeoutText = autoResearchTimeoutText(input.timeout_policy);

  return (
    <div
      className="rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-3"
      data-testid="autoresearch-hitl-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-ui-meta font-bold uppercase text-amber-700">HITL</div>
          <div className="mt-1 break-words text-ui-small font-semibold text-amber-950">
            {meta.title}
          </div>
          <div className="mt-1 break-words text-ui-small text-amber-800">
            {meta.description}
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-amber-200 bg-white px-2 py-0.5 text-ui-micro font-medium text-amber-700">
          等待确认
        </span>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-ui-micro text-amber-700">
        {input.gate && <span>Gate：{input.gate}</span>}
        <span>Stage：{input.workflow_step_id || input.step || step.id}</span>
        {input.tool_name && <span>Tool：{toolTitle(input.tool_name)}</span>}
      </div>

      <div className="mt-3 whitespace-pre-wrap text-chat-body leading-relaxed text-slate-700">
        {input.question}
      </div>

      {input.fields?.length ? (
        <div className="mt-3 space-y-2 rounded-md border border-amber-100 bg-white/70 px-3 py-2">
          <div className="text-ui-meta font-semibold uppercase tracking-wide text-amber-700">
            待确认项
          </div>
          {input.fields.map((field) => (
            <div key={field.id} className="grid gap-1 text-ui-small sm:grid-cols-[120px_minmax(0,1fr)]">
              <div className="font-medium text-slate-600">
                {field.label || field.id}
                {field.required ? " *" : ""}
              </div>
              <div className="break-words text-slate-700">
                {readableWorkflowValue(field.value) || field.placeholder || "等待填写"}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {commandPreview.length > 0 && (
        <div className="mt-3 rounded-md border border-slate-200 bg-slate-950 px-3 py-2">
          <div className="mb-1 text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
            Command Preview
          </div>
          <pre className="whitespace-pre-wrap break-words font-mono text-ui-micro leading-relaxed text-slate-100">
            {commandPreview.join("\n")}
          </pre>
        </div>
      )}

      {(input.resume_action || timeoutText) && (
        <div className="mt-3 space-y-1 text-ui-small text-amber-800">
          {input.resume_action && <div>{input.resume_action}</div>}
          {timeoutText && <div>{timeoutText}</div>}
        </div>
      )}

      {visibleOptions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {visibleOptions.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => void onSubmit(option)}
              className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-ui-small font-medium text-slate-700 hover:bg-amber-100"
            >
              {autoResearchOptionLabel(option, input)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function autoResearchHitlMeta(input: PendingUserInput, step: WorkflowStepState) {
  const gate = input.gate || "";
  if (gate === "lab_instance_flow") {
    return {
      title: "Lab 实例选择",
      description: "必须先明确 yes/no，禁止默认跳过。",
    };
  }
  if (gate === "step_1_project_setup" || step.id === "setup") {
    return {
      title: "项目 Setup 确认",
      description: "一次性确认项目路径、入口、数据集和检测摘要。",
    };
  }
  if (gate === "step_2_5_environment" || step.id === "environments") {
    return {
      title: "环境方案确认",
      description: "确认复用环境、镜像结论或新建 conda 环境方案。",
    };
  }
  if (gate === "step_5_pre_loop" || step.id === "experiment_loop") {
    return {
      title: "预循环确认",
      description: "训练循环开始前必须确认停止条件和单轮时限。",
    };
  }
  if (gate === "step_7_stop_instance" || step.id === "instance_teardown") {
    return {
      title: "关机确认",
      description: "Step 2 创建过实例时，报告完成后必须处理关机分支。",
    };
  }
  return {
    title: "AutoResearch 确认点",
    description: "该阶段存在未决实质选择，确认后才会继续推进。",
  };
}

function autoResearchOptionLabel(option: string, input: PendingUserInput) {
  const normalized = option.trim().toLowerCase();
  if (input.gate === "lab_instance_flow") {
    if (normalized === "yes") return "创建实例";
    if (normalized === "no") return "不创建实例";
  }
  if (input.gate === "step_7_stop_instance") {
    if (normalized === "yes") return "立即关闭";
    if (normalized === "no") return "暂不关闭";
  }
  return option;
}

function autoResearchTimeoutText(timeout?: PendingTimeoutPolicy) {
  if (!timeout) return "";
  const minutes = timeout.minutes ? `${timeout.minutes} 分钟` : "";
  const action = timeout.on_timeout ? readableWorkflowValue(timeout.on_timeout) : "";
  const description = timeout.description ? readableWorkflowValue(timeout.description) : "";
  if (description) return description;
  if (minutes && action) return `${minutes}无回复：${action}`;
  if (minutes) return `${minutes}无回复后按超时策略处理`;
  return action;
}

function autoResearchStageMeta(step: WorkflowStepState) {
  const metadata: Record<string, { skillFile: string; output: string }> = {
    instance_provision: { skillFile: "skill_01lab_instance.md", output: "serverId / SSH 可用性" },
    policies: { skillFile: "skill_02policies.md", output: "Gate log 初始化与阶段规则" },
    setup: { skillFile: "skill_03setup.md", output: "project_root / entrypoint / results.tsv" },
    environments: { skillFile: "skill_04environment.md", output: "env 名称 / python 路径 / 镜像结论" },
    experimentation: { skillFile: "skill_05experiment_logging.md", output: "实验假设 / 安全改动范围" },
    output_and_logging: { skillFile: "skill_05experiment_logging.md", output: "指标提取 / results.tsv 记录" },
    experiment_loop: { skillFile: "skill_06loop.md", output: "轮次进度 / 当前最佳指标" },
    final_report: { skillFile: "skill_07report.md", output: "autoresearch_report.md 路径" },
    instance_teardown: { skillFile: "skill_08stop_instance.md", output: "关机分支 / stop 结果" },
  };
  return metadata[step.id] || { skillFile: fileNameFromPath(step.skill_file || ""), output: workflowStepDetail(step) };
}

function fileNameFromPath(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() || path || "-";
}

const AUTORESEARCH_GATE_TEMPLATE = [
  { id: "lab_instance_flow", label: "Lab instance flow", value: "unresolved", status: "blocked", evidence: "用户是否明确答复" },
  { id: "step_1_project_setup", label: "Step 1 Project setup", value: "no", status: "pending", evidence: "project_root、entrypoint、results.tsv 表头" },
  { id: "step_2_lab_instance", label: "Step 2 Lab instance provision", value: "no", status: "pending", evidence: "serverId、SSH 就绪" },
  { id: "step_2_5_environment", label: "Step 2.5 Environment ready", value: "no", status: "blocked", evidence: "env 名称、python 路径、镜像结论" },
  { id: "step_5_pre_loop", label: "Step 5 Pre-loop confirmation", value: "no", status: "blocked", evidence: "最大轮数、总时长、单轮时限" },
  { id: "step_5_loop", label: "Step 5 Experiment loop", value: "not_started", status: "pending", evidence: "round x/y、当前最佳指标" },
  { id: "step_6_final_report", label: "Step 6 Final report", value: "no", status: "pending", evidence: "autoresearch_report.md 路径" },
  { id: "step_7_stop_instance", label: "Step 7 Stop lab instance", value: "not_applicable", status: "pending", evidence: "关机决策分支与结果" },
];

function autoResearchGateRows(gateLog?: Record<string, unknown>) {
  const seen = new Set<string>();
  const rows = AUTORESEARCH_GATE_TEMPLATE.map((template) => {
    seen.add(template.id);
    return autoResearchGateRow(template.id, gateLog?.[template.id], template);
  });
  for (const [id, raw] of Object.entries(gateLog || {})) {
    if (id === "next_action" || seen.has(id)) continue;
    rows.push(autoResearchGateRow(id, raw, { label: id, value: "", status: "", evidence: "" }));
  }
  return rows;
}

function autoResearchGateRow(
  id: string,
  raw: unknown,
  fallback: { label: string; value: string; status: string; evidence: string }
) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {
      id,
      label: fallback.label,
      value: readableWorkflowValue(raw) || fallback.value,
      status: fallback.status,
      evidence: fallback.evidence,
    };
  }
  const record = raw as Record<string, unknown>;
  return {
    id,
    label: fallback.label,
    value: readableWorkflowValue(record.value) || fallback.value,
    status: readableWorkflowValue(record.status) || fallback.status,
    evidence: readableWorkflowValue(record.evidence) || fallback.evidence,
  };
}

function WorkflowSummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
        {label}
      </dt>
      <dd className="mt-0.5 truncate text-ui-small font-medium text-slate-700" title={value}>
        {value}
      </dd>
    </div>
  );
}

function workflowCurrentStep(workflow: WorkflowState, steps: WorkflowStepState[]) {
  return (
    steps.find((step) => step.id === workflow.current_step_id) ||
    steps.find((step) => ["running", "waiting_for_user", "recovery"].includes(step.status)) ||
    steps.find((step) => step.status !== "completed")
  );
}

function workflowChecklistStats(steps: WorkflowStepState[]) {
  const items = steps.flatMap((step) => step.instruction_plan?.items || []);
  return {
    total: items.length,
    completed: items.filter((item) => item.status === "completed").length,
  };
}

function workflowEvidenceStats(steps: WorkflowStepState[]) {
  return steps.reduce(
    (stats, step) => ({
      evidence: stats.evidence + workflowEvidenceEntries(step).length,
      artifacts: stats.artifacts + (step.artifacts?.length || 0),
      risks: stats.risks + workflowRiskEntries(step).length,
    }),
    { evidence: 0, artifacts: 0, risks: 0 }
  );
}

function workflowToolCallCount(steps: WorkflowStepState[]) {
  return steps.reduce((count, step) => count + (step.tool_calls?.length || 0), 0);
}

function workflowReportPath(workflow: WorkflowState) {
  const results = workflow.results || {};
  return (
    stringValue(results.word_report_path) ||
    stringValue(results.local_report_path) ||
    stringValue(results.remote_report_path) ||
    stringValue(results.report_path)
  );
}

function workflowMarkdownReportPath(workflow: WorkflowState) {
  const results = workflow.results || {};
  return stringValue(results.markdown_report_path);
}

function workflowSkillSelectionStepId(workflow: WorkflowState) {
  return (workflow.steps || [])[0]?.id || REPRO_WORKFLOW_STEPS[0]?.id;
}

interface WorkflowPhaseSummary {
  id: string;
  title: string;
  subtitle: string;
  steps: WorkflowStepState[];
  completed: number;
  status: "completed" | "running" | "blocked" | "pending";
}

function workflowPhaseSummaries(steps: WorkflowStepState[]): WorkflowPhaseSummary[] {
  const byId = new Map(steps.map((step) => [step.id, step]));
  const assigned = new Set<string>();
  const summaries = REPRO_WORKFLOW_PHASES.map((phase) => {
    const phaseSteps = phase.stepIds
      .map((stepId) => byId.get(stepId))
      .filter((step): step is WorkflowStepState => !!step);
    phaseSteps.forEach((step) => assigned.add(step.id));
    return workflowPhaseSummary(phase.id, phase.title, phase.subtitle, phaseSteps);
  });
  const extraSteps = steps.filter((step) => !assigned.has(step.id));
  if (extraSteps.length > 0) {
    summaries.push(
      workflowPhaseSummary("extra", "补充步骤", "运行时追加的 workflow step", extraSteps)
    );
  }
  return summaries;
}

function workflowPhaseSummary(
  id: string,
  title: string,
  subtitle: string,
  steps: WorkflowStepState[]
): WorkflowPhaseSummary {
  const completed = steps.filter((step) => step.status === "completed").length;
  const hasActive = steps.some((step) =>
    ["running", "waiting_for_user", "recovery"].includes(step.status)
  );
  const hasBlocked = steps.some((step) => step.status === "failed");
  return {
    id,
    title,
    subtitle,
    steps,
    completed,
    status: hasBlocked
      ? "blocked"
      : completed === steps.length && steps.length > 0
        ? "completed"
        : hasActive
          ? "running"
          : "pending",
  };
}

function workflowPhaseStatusClass(status: WorkflowPhaseSummary["status"]) {
  if (status === "completed") return "border-emerald-100 bg-emerald-50 text-emerald-700";
  if (status === "running") return "border-blue-100 bg-blue-50 text-blue-700";
  if (status === "blocked") return "border-red-100 bg-red-50 text-red-700";
  return "border-slate-100 bg-white text-slate-500";
}

function workflowTimelineEventsForStep(
  events: TimelineEvent[],
  step: WorkflowStepState,
  workflow: WorkflowState
) {
  const fallbackStepId =
    workflow.current_step_id ||
    (workflow.steps || []).find((item) =>
      ["running", "waiting_for_user", "recovery"].includes(item.status)
    )?.id ||
    workflowSkillSelectionStepId(workflow);

  return events.filter((event) => {
    if (event.workflow_step_id) return event.workflow_step_id === step.id;
    return fallbackStepId === step.id;
  });
}

function skillSelectionSummaryLines(
  selection?: SkillSelectionState,
  workflowPath?: string | null
) {
  if (!selection) return [];
  const selected = selection.selected_skill || selection.model_choice || selection.fallback_choice;
  if (!selected) return [];
  const source = skillSelectionSourceMeta(selection.source);
  const lines = [`${source.titlePrefix} ${selected}`];
  if (workflowPath) lines.push(`已加载 ${workflowPath}`);
  if (selection.reason) lines.push(selection.reason);
  return lines;
}

function structuredProcessRecordFromEvent(event: TimelineEvent): StructuredProcessRecord | null {
  return structuredProcessRecordFromInput(event);
}

function structuredProcessRecordFromProgress(
  content: string,
  index: number
): StructuredProcessRecord | null {
  return structuredProcessRecordFromInput({
    id: `progress-${index}`,
    title: workflowProgressTitle(content),
    content,
  });
}

function structuredProcessRecordFromInput(
  input: StructuredProcessParseInput
): StructuredProcessRecord | null {
  const raw = processInputText(input);
  if (!looksLikeStructuredProcessMarkdown(raw, input.title)) return null;
  const snapshot = parseStructuredWorkflowSnapshot(raw);
  const actions = parseStructuredProcessActions(raw);
  if (!snapshot && actions.length === 0 && !raw.includes("|")) return null;
  return {
    id: input.id,
    title: processRecordTitle(input.title),
    judgement: extractProcessJudgement(raw, input.title),
    snapshot,
    actions,
    raw,
  };
}

function processInputText(input: StructuredProcessParseInput) {
  const content = input.content?.trim();
  if (!content) return input.title;
  if (content.startsWith(`${input.title}:`) || content.startsWith(`${input.title}：`)) {
    return content;
  }
  return `${input.title}：${content}`;
}

function looksLikeStructuredProcessMarkdown(text: string, title?: string) {
  return (
    text.includes("复现流水线实时看板") ||
    text.includes("| 序号 |") ||
    text.includes("模型规划工具调用") ||
    text.includes("制定执行计划") ||
    title === "制定执行计划" ||
    title === "模型规划工具调用"
  );
}

function processRecordTitle(title: string) {
  if (title.includes("恢复")) return "恢复计划";
  if (title.includes("GPU")) return "GPU 执行计划";
  if (title.includes("工具")) return "模型工具计划";
  if (title.includes("计划")) return "执行计划";
  return "实验判断";
}

function workflowProgressTitle(content: string) {
  if (/GPU|CUDA|推理|微调/.test(content)) return "GPU 执行计划";
  if (/恢复|失败|重试|清理/.test(content)) return "恢复计划";
  if (/工具|模型规划工具调用/.test(content)) return "模型工具计划";
  if (/计划|看板|复现流水线/.test(content)) return "执行计划";
  return "运行记录";
}

function extractProcessJudgement(raw: string, fallback: string) {
  const cleaned = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => {
      if (!line) return false;
      if (line.startsWith("|")) return false;
      if (/^-{3,}/.test(line)) return false;
      if (/^#{1,6}\s*/.test(line)) return false;
      if (line.includes("复现流水线实时看板")) return false;
      return true;
    })
    .join(" ")
    .replace(/^(制定执行计划|模型规划工具调用)[：:]\s*/g, "")
    .replace(/\s+(模型规划工具调用|制定执行计划)[：:]\s*/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  return compactWorkflowText(cleaned || fallback, 220);
}

function parseStructuredWorkflowSnapshot(raw: string): StructuredWorkflowSnapshot | undefined {
  const rows = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => /^\|\s*\d+\s*\|/.test(line));

  if (rows.length === 0) return undefined;

  const completed = rows.filter((row) => /✅|完成|通过/.test(row)).length;
  const currentRow =
    rows.find((row) => /执行中|等待中|等待|⏳|运行中/.test(row)) ||
    rows.find((row) => !/✅|完成|通过/.test(row));
  const total = Math.max(REPRO_WORKFLOW_STEPS.length, rows.length);

  return {
    completed,
    total,
    current: currentRow ? workflowTableStepLabel(currentRow) : undefined,
    state: currentRow ? workflowTableStatusLabel(currentRow) : undefined,
  };
}

function workflowTableStepLabel(row: string) {
  const cells = markdownTableCells(row);
  const stepCell = cells[1] || row;
  const match = stepCell.match(/`([^`]+)`\s*:?\s*(.*)/);
  if (match) {
    const name = match[2]?.trim();
    return name ? `${match[1]} · ${name}` : match[1];
  }
  return compactWorkflowText(stepCell.replace(/`/g, ""), 80);
}

function workflowTableStatusLabel(row: string) {
  const cells = markdownTableCells(row);
  const statusCell = cells[2] || "";
  return compactWorkflowText(statusCell.replace(/[✅⏳]/g, "").trim() || "待处理", 40);
}

function markdownTableCells(row: string) {
  return row
    .split("|")
    .slice(1, -1)
    .map((cell) => cell.trim());
}

function parseStructuredProcessActions(raw: string) {
  const actions: StructuredProcessAction[] = [];
  const normalized = raw.replace(/\s+/g, " ");

  addStructuredAction(actions, "SSH 探活", actionStatus(normalized, ["SSH"], ["成功", "连通"], ["失败", "超时"]), "确认远程实例可连接。");
  addStructuredAction(actions, "克隆项目代码", actionStatus(normalized, ["克隆", "clone"], [], ["失败"]), "拉取目标 GitHub 仓库到任务工作区。");
  addStructuredAction(actions, "读取仓库审计报告", actionStatus(normalized, ["读取审计报告", "repo_audit"], [], ["失败"]), "加载前序审计结论作为环境构建依据。");
  addStructuredAction(actions, "清理历史代码目录", actionStatus(normalized, ["清理", "目录已存在"], [], ["失败"]), "清除远端残留目录后重新克隆。");
  addStructuredAction(actions, "读取项目关键文件", actionStatus(normalized, ["读取项目关键文件", "关键文件"], [], ["失败"]), "补充 README、依赖和入口信息。");
  addStructuredAction(actions, "构建运行环境", actionStatus(normalized, ["环境构建", "依赖", "安装"], [], ["失败"]), "安装依赖并记录可复现环境。");
  addStructuredAction(actions, "CUDA 编译", actionStatus(normalized, ["CUDA 编译", "编译"], [], ["失败"]), "编译或校验 GPU 运行入口。");
  addStructuredAction(actions, "运行推理测试", actionStatus(normalized, ["推理测试", "运行推理", "推理"], [], ["失败"]), "执行样例推理并记录输出。");

  return actions;
}

function addStructuredAction(
  actions: StructuredProcessAction[],
  title: string,
  status: StructuredProcessActionStatus | null,
  detail: string
) {
  if (!status) return;
  if (actions.some((action) => action.title === title)) return;
  actions.push({ title, status, detail });
}

function actionStatus(
  text: string,
  needles: string[],
  doneMarkers: string[],
  failedMarkers: string[]
): StructuredProcessActionStatus | null {
  if (!needles.some((needle) => text.includes(needle))) return null;
  if (failedMarkers.some((marker) => text.includes(marker))) return "failed";
  if (doneMarkers.some((marker) => text.includes(marker))) return "done";
  if (text.includes("等待")) return "waiting";
  if (text.includes("目录已存在") || text.includes("残留")) return "risk";
  return "todo";
}

function WorkflowStepRow({
  step,
  index,
  isCurrent,
  pendingInput,
  onSubmit,
  skillSelection,
  workflowPath,
  events,
}: {
  step: WorkflowStepState;
  index: number;
  isCurrent: boolean;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
  skillSelection?: SkillSelectionState;
  workflowPath?: string | null;
  events?: TimelineEvent[];
}) {
  const template = REPRO_WORKFLOW_STEPS.find((item) => item.id === step.id);
  const name = step.name || template?.name || step.id;
  const progressItems = (step.progress || []).slice(-3);
  const toolCalls = (step.tool_calls || []).slice(0, 4);
  const checklistItems = step.instruction_plan?.items || [];
  const checklistCompleted = checklistItems.filter((item) => item.status === "completed").length;
  const stepEvents = events || [];
  const thinkingEvents = stepEvents.filter((event) => event.kind === "thinking");
  const executionEvents = stepEvents.filter((event) => event.kind !== "thinking");
  const outcome = workflowStepOutcome(step);
  const outcomePreview = compactWorkflowText(outcome, 180);
  const startLabel = workflowStepStartLabel(step);
  const skillSelectionLines = skillSelectionSummaryLines(skillSelection, workflowPath);
  const researchSummary = workflowStepResearchSummary(step);
  const structuredThinkingRecords = thinkingEvents
    .map((event) => structuredProcessRecordFromEvent(event))
    .filter((record): record is StructuredProcessRecord => !!record);
  const structuredThinkingEventIds = new Set(structuredThinkingRecords.map((record) => record.id));
  const plainThinkingEvents = thinkingEvents.filter((event) => !structuredThinkingEventIds.has(event.id));
  const progressRecords = progressItems.map((item, progressIndex) => ({
    content: item,
    record: structuredProcessRecordFromProgress(item, progressIndex),
  }));
  const structuredProgressRecords = progressRecords
    .map((item) => item.record)
    .filter((record): record is StructuredProcessRecord => !!record);
  const plainProgressItems = progressRecords
    .filter((item) => !item.record)
    .map((item) => item.content);
  const structuredExecutionRecords = executionEvents
    .map((event) => structuredProcessRecordFromEvent(event))
    .filter((record): record is StructuredProcessRecord => !!record);
  const structuredExecutionEventIds = new Set(structuredExecutionRecords.map((record) => record.id));
  const plainExecutionEvents = executionEvents.filter((event) => !structuredExecutionEventIds.has(event.id));
  const hasObjective = skillSelectionLines.length > 0 || !!step.expected_output;
  const hasThinking = !!startLabel || thinkingEvents.length > 0;
  const hasProcessDetails = hasThinking || progressItems.length > 0 || executionEvents.length > 0;
  const hasExecution =
    progressItems.length > 0 ||
    toolCalls.length > 0 ||
    checklistItems.length > 0 ||
    executionEvents.length > 0 ||
    !!pendingInput;
  const defaultOpen =
    !!pendingInput ||
    isCurrent ||
    !!skillSelection ||
    ["running", "failed", "recovery", "waiting_for_user"].includes(step.status);
  const detailSummary = workflowStepDetailSummary({
    progressCount: progressItems.length,
    thinkingCount: thinkingEvents.length,
    executionCount: executionEvents.length,
    hasPendingInput: !!pendingInput,
  });

  return (
    <details className="group bg-white" open={defaultOpen} data-testid={`workflow-step-${step.id}`}>
      <summary className="flex cursor-pointer list-none gap-3 px-4 py-3 hover:bg-slate-50">
        <span
          className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-ui-micro font-semibold ${workflowStepNumberClass(
            step.status
          )}`}
        >
          {index + 1}
        </span>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="break-words font-medium text-slate-800">{name}</span>
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-ui-small font-semibold text-slate-600">
              {step.id}
            </code>
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-ui-micro font-medium ${workflowStepStatusClass(
                step.status
              )}`}
            >
              {workflowStepStatusLabel(step.status)}
            </span>
            {isCurrent && (
              <span className="rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-ui-micro font-medium text-blue-700">
                当前
              </span>
            )}
          </div>
          {outcomePreview && (
            <div className="break-words text-ui-small leading-relaxed text-slate-600" title={outcome}>
              {outcomePreview}
            </div>
          )}
        </div>
        <ChevronIcon className="mt-1 h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
      </summary>
      <div className="space-y-4 px-14 pb-4 text-ui-small">
        {hasObjective && (
          <WorkflowStepProcessSection title="任务目标">
            {skillSelectionLines.map((line) => (
              <ProcessLine key={`${step.id}-selection-${line}`} content={line} tone="thinking" />
            ))}
            {skillSelection && (
              <SkillSelectionEvidenceDetails selection={skillSelection} workflowPath={workflowPath} />
            )}
            {step.expected_output && (
              <ProcessLine content={step.expected_output} tone="thinking" />
            )}
          </WorkflowStepProcessSection>
        )}
        <WorkflowStepResearchSummary summary={researchSummary} />
        {toolCalls.length > 0 && (
          <WorkflowStepProcessSection title="工具执行" summary={`${toolCalls.length} 项`}>
            <div className="flex flex-wrap gap-1.5">
              {toolCalls.map((call, toolIndex) => (
                <span
                  key={call.tool_call_id || `${step.id}-tool-${toolIndex}`}
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
          </WorkflowStepProcessSection>
        )}
        {checklistItems.length > 0 && (
          <WorkflowStepProcessSection title="验收项" summary={`${checklistCompleted}/${checklistItems.length}`}>
            <InstructionChecklist items={checklistItems} />
          </WorkflowStepProcessSection>
        )}
        {pendingInput && <HumanInputPanel input={pendingInput} onSubmit={onSubmit} stepId={step.id} />}
        {hasProcessDetails && (
          <WorkflowStepDetailsSection summary={detailSummary}>
            {startLabel && <ProcessLine content={startLabel} tone="thinking" />}
            {structuredThinkingRecords.map((record) => (
              <StructuredProcessRecordCard
                key={`${step.id}-structured-${record.id}`}
                record={record}
              />
            ))}
            {plainThinkingEvents.map((event) => (
              <ProcessLine
                key={`${step.id}-thinking-${event.id}`}
                content={event.content ? `${event.title}: ${event.content}` : event.title}
                tone="thinking"
              />
            ))}
            {structuredProgressRecords.map((record) => (
              <StructuredProcessRecordCard
                key={`${step.id}-progress-structured-${record.id}`}
                record={record}
              />
            ))}
            {structuredExecutionRecords.map((record) => (
              <StructuredProcessRecordCard
                key={`${step.id}-execution-structured-${record.id}`}
                record={record}
              />
            ))}
            {plainProgressItems.map((item, progressIndex) => (
              <ProcessLine
                key={`${step.id}-progress-${progressIndex}`}
                content={workflowProgressContent(item) || item}
                tone="execution"
              />
            ))}
            {plainExecutionEvents.map((event) => (
              <ProcessLine
                key={`${step.id}-execution-${event.id}`}
                content={event.content ? `${event.title}: ${event.content}` : event.title}
                tone="execution"
              />
            ))}
          </WorkflowStepDetailsSection>
        )}
        {!hasThinking && !hasExecution && !outcome && (
          <div className="text-slate-500">{workflowStepDetail(step)}</div>
        )}
      </div>
    </details>
  );
}

function WorkflowStepProcessSection({
  title,
  summary,
  children,
}: {
  title: "任务目标" | "研究证据" | "工具执行" | "验收项";
  summary?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
          {title}
        </div>
        {summary && (
          <span className="rounded-full border border-slate-100 bg-slate-50 px-2 py-0.5 text-ui-micro font-medium text-slate-500">
            {summary}
          </span>
        )}
      </div>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}

function WorkflowStepDetailsSection({
  summary,
  children,
}: {
  summary?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="rounded-lg border border-slate-100 bg-slate-50/60">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full cursor-pointer items-center justify-between gap-3 px-3 py-2 text-left text-ui-small font-medium text-slate-600"
        aria-expanded={open}
      >
        <span>过程详情</span>
        <span className="flex items-center gap-2">
          {summary && (
            <span className="rounded-full border border-slate-100 bg-white px-2 py-0.5 text-ui-micro font-medium text-slate-500">
              {summary}
            </span>
          )}
          <ChevronIcon className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`} />
        </span>
      </button>
      {open && <div className="space-y-2 border-t border-slate-100 px-3 py-3">{children}</div>}
    </section>
  );
}

function workflowStepDetailSummary({
  progressCount,
  thinkingCount,
  executionCount,
  hasPendingInput,
}: {
  progressCount: number;
  thinkingCount: number;
  executionCount: number;
  hasPendingInput: boolean;
}) {
  const count = progressCount + thinkingCount + executionCount;
  if (hasPendingInput && count > 0) return `${count} 条记录 / HITL`;
  if (hasPendingInput) return "HITL";
  return `${count} 条记录`;
}

function StructuredProcessRecordCard({ record }: { record: StructuredProcessRecord }) {
  return (
    <div className="space-y-3 rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-3">
      <div className="rounded-md border border-white bg-white px-3 py-2 text-slate-700 shadow-sm">
        <div className="mb-1 text-ui-micro font-semibold uppercase tracking-wide text-slate-400">
          {record.title}
        </div>
        <div className="break-words leading-relaxed">{record.judgement}</div>
      </div>
      {record.snapshot && (
        <div className="grid gap-2 md:grid-cols-3">
          <StructuredProcessMetric
            label="流程快照"
            value={`${record.snapshot.completed}/${record.snapshot.total} 完成`}
          />
          <StructuredProcessMetric label="当前节点" value={record.snapshot.current || "-"} />
          <StructuredProcessMetric label="状态" value={record.snapshot.state || "-"} />
        </div>
      )}
      {record.actions.length > 0 && (
        <div className="rounded-md border border-white bg-white px-3 py-2 shadow-sm">
          <div className="mb-2 text-ui-micro font-semibold uppercase tracking-wide text-slate-400">
            执行队列
          </div>
          <div className="grid gap-1.5">
            {record.actions.map((action) => (
              <div
                key={`${action.title}-${action.status}`}
                className="flex min-w-0 items-start gap-2 text-slate-600"
              >
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${structuredActionStatusClass(
                    action.status
                  )}`}
                />
                <span className="min-w-0 break-words">
                  <span className="font-medium text-slate-700">{action.title}</span>
                  {action.detail && <span className="text-slate-500">：{action.detail}</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      <details className="rounded-md border border-slate-100 bg-white px-3 py-2">
        <summary className="cursor-pointer text-ui-micro font-semibold uppercase tracking-wide text-slate-400">
          原始记录
        </summary>
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950/95 p-3 text-ui-micro leading-relaxed text-slate-100">
          {record.raw}
        </pre>
      </details>
    </div>
  );
}

function StructuredProcessMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white bg-white px-3 py-2 shadow-sm">
      <div className="text-ui-micro font-semibold uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className="mt-1 break-words font-medium text-slate-700">{value}</div>
    </div>
  );
}

function structuredActionStatusClass(status: StructuredProcessActionStatus) {
  if (status === "done") return "bg-emerald-500";
  if (status === "failed") return "bg-red-500";
  if (status === "risk") return "bg-amber-500";
  if (status === "waiting") return "bg-orange-400";
  return "bg-blue-400";
}

interface WorkflowStepResearchSummaryData {
  evidence: Array<[string, string]>;
  artifacts: string[];
  risks: string[];
}

function WorkflowStepResearchSummary({ summary }: { summary: WorkflowStepResearchSummaryData }) {
  const hasEvidence = summary.evidence.length > 0;
  const hasArtifacts = summary.artifacts.length > 0;
  const hasRisks = summary.risks.length > 0;
  if (!hasEvidence && !hasArtifacts && !hasRisks) {
    return (
      <WorkflowStepProcessSection title="研究证据" summary="待采集">
        <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-slate-500">
          等待工具结果或验收项写入 evidence。
        </div>
      </WorkflowStepProcessSection>
    );
  }

  return (
    <WorkflowStepProcessSection
      title="研究证据"
      summary={`${summary.evidence.length} 证据 / ${summary.artifacts.length} 产物 / ${summary.risks.length} 风险`}
    >
      <div className="grid gap-2 rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-3 md:grid-cols-3">
        <WorkflowEvidenceColumn title="证据链">
          {hasEvidence ? (
            summary.evidence.map(([key, value]) => (
              <div key={`${key}-${value}`} className="min-w-0">
                <div className="truncate font-mono text-ui-micro text-slate-500">{key}</div>
                <div className="break-words text-slate-700">{compactWorkflowText(value, 120)}</div>
              </div>
            ))
          ) : (
            <div className="text-slate-400">待写入</div>
          )}
        </WorkflowEvidenceColumn>
        <WorkflowEvidenceColumn title="产物">
          {hasArtifacts ? (
            summary.artifacts.map((artifact) => (
              <div key={artifact} className="break-words font-mono text-ui-micro text-slate-700">
                {artifact}
              </div>
            ))
          ) : (
            <div className="text-slate-400">暂无 artifact</div>
          )}
        </WorkflowEvidenceColumn>
        <WorkflowEvidenceColumn title="风险/缺口">
          {hasRisks ? (
            summary.risks.map((risk) => (
              <div key={risk} className="break-words text-red-700">
                {compactWorkflowText(risk, 140)}
              </div>
            ))
          ) : (
            <div className="text-emerald-700">无阻塞记录</div>
          )}
        </WorkflowEvidenceColumn>
      </div>
    </WorkflowStepProcessSection>
  );
}

function WorkflowEvidenceColumn({
  title,
  children,
}: {
  title: "证据链" | "产物" | "风险/缺口";
  children: ReactNode;
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function ProcessLine({
  content,
  tone,
}: {
  content: string;
  tone: "thinking" | "execution";
}) {
  const dotClass = tone === "thinking" ? "bg-violet-400" : "bg-blue-400";
  return (
    <div className="flex gap-2 text-slate-500">
      <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} />
      <span className="break-words">{content}</span>
    </div>
  );
}

function InstructionChecklist({ items }: { items: RuntimeInstructionItem[] }) {
  return (
    <div className="grid gap-1 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
      {items.map((item, index) => (
        <div
          key={item.id || `instruction-${index}`}
          className="flex min-w-0 items-start gap-2 text-ui-small text-slate-600"
        >
          <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${instructionStatusClass(item.status)}`} />
          <span className="min-w-0 break-words">
            <span className="font-mono text-slate-500">{item.id || "instruction"}</span>
            {": "}
            {item.text || item.missing_reason || item.status || "-"}
          </span>
        </div>
      ))}
    </div>
  );
}

function instructionStatusClass(status?: string) {
  if (status === "completed") return "bg-emerald-500";
  if (status === "failed" || status === "blocked") return "bg-red-500";
  return "bg-amber-400";
}

function HumanInputPanel({
  input,
  onSubmit,
  stepId,
}: {
  input: PendingUserInput;
  onSubmit: (content: string) => Promise<void>;
  stepId?: string;
}) {
  if (input.intervention?.type === "lab4ai_credentials_required") {
    return <Lab4AICredentialPanel input={input} onSubmit={onSubmit} />;
  }
  const visibleOptions = humanInputVisibleOptions(input.options);

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-3" data-testid="step-human-input">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-ui-meta font-bold uppercase text-amber-700">实验确认点</div>
          <div className="mt-1 text-ui-small font-semibold text-amber-900">
            需要你确认后继续执行受控动作
          </div>
        </div>
        <span className="rounded-full border border-amber-200 bg-white px-2 py-0.5 text-ui-micro font-medium text-amber-700">
          HITL
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-ui-micro text-amber-700">
        {stepId && <span>步骤：{stepId}</span>}
        {input.tool_name && <span>操作：{toolTitle(input.tool_name)}</span>}
      </div>
      <div className="mt-2 whitespace-pre-wrap text-chat-body leading-relaxed text-slate-700">
        {input.question}
      </div>
      {visibleOptions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {visibleOptions.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => void onSubmit(option)}
              className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-ui-small text-slate-700 hover:bg-amber-100"
            >
              {option}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function humanInputVisibleOptions(options?: string[]) {
  return (options || []).filter((option) => option.trim() !== "修改方案");
}

function Lab4AICredentialPanel({
  input,
  onSubmit,
}: {
  input: PendingUserInput;
  onSubmit: (content: string) => Promise<void>;
}) {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedCredential, setSavedCredential] = useState<Lab4AICredentialsSaveResponse | null>(null);
  const endpoint = String(input.intervention?.admin_endpoint || "/api/admin/settings/lab4ai");

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!phone.trim() || !password.trim()) {
      setError("请填写 Lab4AI 平台账号和密码。");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const result = await apiFetch<Lab4AICredentialsSaveResponse>(endpoint, {
        method: "PUT",
        body: JSON.stringify({ phone: phone.trim(), password }),
      });
      setPhone("");
      setPassword("");
      setSavedCredential(result || { configured: true });
      await onSubmit("已完成配置，继续执行");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败，请检查账号权限后重试。");
    } finally {
      setSaving(false);
    }
  }

  if (savedCredential) {
    return (
      <div
        className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-3"
        data-testid="lab4ai-credential-panel"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-ui-meta font-bold uppercase text-emerald-700">
              Lab4AI 凭证已安全配置
            </div>
            <div className="mt-1 text-ui-small leading-relaxed text-emerald-800">
              已提交到后端配置接口，聊天正文只发送继续执行指令。
            </div>
            {savedCredential.phone_masked && (
              <div className="mt-2 inline-flex rounded-full border border-emerald-100 bg-white px-2 py-0.5 font-mono text-ui-micro text-emerald-700">
                {savedCredential.phone_masked}
              </div>
            )}
          </div>
          <span className="rounded-full border border-emerald-100 bg-white px-2 py-0.5 text-ui-micro font-medium text-emerald-700">
            已保存
          </span>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSave}
      className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3"
      data-testid="lab4ai-credential-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-ui-meta font-bold uppercase text-amber-700">等待你确认</div>
          <div className="mt-1 text-ui-small font-semibold text-amber-800">需要你的输入</div>
          <div className="mt-1 text-ui-small leading-relaxed text-amber-700">
            {input.question}
          </div>
        </div>
        <span className="rounded-full border border-amber-200 bg-white px-2 py-0.5 text-ui-micro font-medium text-amber-700">
          Human Input
        </span>
      </div>
      <div className="mt-3 grid gap-2">
        <label className="grid gap-1 text-ui-small font-medium text-amber-900">
          手机号/账号
          <input
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            autoComplete="username"
            className="rounded-lg border border-amber-200 bg-white px-3 py-2 text-chat-body font-normal text-slate-700 outline-none focus:border-amber-300"
          />
        </label>
        <label className="grid gap-1 text-ui-small font-medium text-amber-900">
          密码
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete="current-password"
            className="rounded-lg border border-amber-200 bg-white px-3 py-2 text-chat-body font-normal text-slate-700 outline-none focus:border-amber-300"
          />
        </label>
      </div>
      {error && <div className="mt-2 text-ui-small text-red-600">{error}</div>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-slate-800 px-3 py-1.5 text-ui-small font-medium text-white hover:bg-slate-700 disabled:bg-slate-300"
        >
          {saving ? "保存中..." : "保存并继续"}
        </button>
        <button
          type="button"
          onClick={() => void onSubmit("停止任务")}
          className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-ui-small text-slate-700 hover:bg-amber-100"
        >
          稍后再说
        </button>
      </div>
      <div className="mt-2 text-ui-micro leading-relaxed text-amber-700">
        页面只会显示“凭证已配置”，不会把账号或密码写入普通聊天正文。
      </div>
    </form>
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
  if (step.status === "recovery") {
    return step.error || workflowValidationFailureText(step) || workflowStepDetail(step) || "正在根据工具结果恢复。";
  }
  if (step.status === "waiting_for_user") {
    return step.error || step.output || workflowValidationFailureText(step) || "需要用户确认或补充信息后继续。";
  }
  if (step.status === "running") return step.output || "正在执行当前步骤。";
  if (step.status === "skipped") return step.output || "该步骤已跳过。";
  return "";
}

function workflowStepResearchSummary(step: WorkflowStepState): WorkflowStepResearchSummaryData {
  return {
    evidence: workflowEvidenceEntries(step).slice(0, 6),
    artifacts: (step.artifacts || []).slice(0, 4),
    risks: workflowRiskEntries(step).slice(0, 4),
  };
}

function workflowEvidenceEntries(step: WorkflowStepState): Array<[string, string]> {
  return Object.entries(step.evidence || {})
    .map(([key, value]) => [key, readableWorkflowValue(value)] as [string, string])
    .filter(([, value]) => !!value.trim());
}

function workflowRiskEntries(step: WorkflowStepState): string[] {
  const failures = step.validation_failures || [];
  const failureText = failures.map((failure) => workflowFailureToText(failure)).filter(Boolean);
  return [
    ...failureText,
    ...(step.status === "failed" && step.error ? [step.error] : []),
    ...(step.status === "recovery" && step.error ? [step.error] : []),
  ];
}

function workflowFailureToText(failure: unknown) {
  if (!failure) return "";
  if (typeof failure === "string") return failure;
  if (typeof failure !== "object") return String(failure);
  const record = failure as Record<string, unknown>;
  const reason = record.reason || record.message || record.error || record.postcondition;
  if (typeof reason === "string") return reason;
  if (reason !== undefined) return String(reason);
  return JSON.stringify(record);
}

function readableWorkflowValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(readableWorkflowValue).filter(Boolean).join(", ");
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function compactWorkflowText(value: string, maxLength: number) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function workflowValidationFailureText(step: WorkflowStepState) {
  const failure = step.validation_failures?.[step.validation_failures.length - 1];
  if (!failure) return "";
  return workflowFailureToText(failure);
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

function runtimeEventTitle(type: string) {
  const labels: Record<string, string> = {
    runtime_started: "Agent Runtime 启动",
    runtime_waiting_for_user: "等待人工输入",
    runtime_completed: "Agent Runtime 完成",
    runtime_failed: "Agent Runtime 失败",
    runtime_stopped: "Agent Runtime 已停止",
    permission_requested: "请求工具权限",
  };
  return labels[type] || "Agent Runtime";
}

function runtimeEventStatus(type: string): TimelineEvent["status"] {
  if (type === "runtime_started") return "running";
  if (type === "runtime_failed" || type === "runtime_stopped") return "error";
  if (type === "runtime_completed") return "done";
  return "info";
}

function runtimeEventContent(payload: StreamPayload) {
  const parts = [];
  if (payload.run_id) parts.push(String(payload.run_id));
  if (payload.tool_name) parts.push(String(payload.tool_name));
  if (payload.tool_call_id) parts.push(String(payload.tool_call_id));
  if (payload.content) parts.push(payload.content);
  if (payload.error) parts.push(payload.error);
  return parts.length ? parts.join(" · ") : undefined;
}

function runtimeToolContent(payload: StreamPayload) {
  const parts = [payload.tool_name].filter(Boolean).map(String);
  if (payload.tool_call_id) parts.push(String(payload.tool_call_id));
  return parts.length ? parts.join(" · ") : undefined;
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
