import { useState, useRef, useEffect, FormEvent } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiPost, getToken } from "../lib/api";

interface ClawInstance {
  id: number;
  status: string;
  task_config: { github_url?: string; paper_url?: string; user_prompt?: string };
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

interface ChatMessage {
  role: "user" | "agent";
  content: string;
  type?: "text" | "status" | "terminal";
}

export default function ChatPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const { data: instance } = useQuery({
    queryKey: ["claw-instance", taskId],
    queryFn: () => apiFetch<ClawInstance>(`/api/claw-instances/${taskId}`),
    enabled: !!taskId,
    refetchInterval: 3000,
  });

  // Build messages from instance
  useEffect(() => {
    if (!instance) return;
    const msgs: ChatMessage[] = [];

    const parts: string[] = [];
    if (instance.task_config.github_url) parts.push(instance.task_config.github_url);
    if (instance.task_config.paper_url) parts.push(`论文: ${instance.task_config.paper_url}`);
    if (instance.task_config.user_prompt) parts.push(instance.task_config.user_prompt);
    if (parts.length > 0) {
      msgs.push({ role: "user", content: parts.join("\n") });
    }

    // Agent responses based on status
    if (instance.status === "pending") {
      msgs.push({ role: "agent", content: "任务已创建，正在排队等待执行...", type: "status" });
    } else if (instance.status === "running") {
      msgs.push({ role: "agent", content: "正在执行复现任务...", type: "status" });
    } else if (instance.status === "completed") {
      msgs.push({ role: "agent", content: "任务执行完成。你可以查看右侧面板的输出文件，或继续提出新的复现需求。", type: "text" });
    } else if (instance.status === "failed") {
      msgs.push({ role: "agent", content: `任务执行失败: ${instance.error_message || "未知错误"}\n\n你可以调整参数后重新提交。`, type: "text" });
    } else if (instance.status === "stopped") {
      msgs.push({ role: "agent", content: "任务已被手动停止。你可以重新提交或修改指令。", type: "text" });
    }

    setMessages(msgs);
  }, [instance]);

  // WebSocket logs
  useEffect(() => {
    if (!taskId) return;
    const token = getToken();
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/claw-instances/${taskId}/logs?token=${token}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    ws.onmessage = (event) => {
      setLogs((prev) => [...prev, event.data]);
    };
    return () => { ws.close(); };
  }, [taskId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, logs]);

  const stopMutation = useMutation({
    mutationFn: () => apiFetch(`/api/claw-instances/${taskId}/stop`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["claw-instance", taskId] }),
  });

  // Submit new task from within conversation
  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;

    const urlMatch = input.match(/(https?:\/\/github\.com\/[^\s]+)/);
    const githubUrl = urlMatch ? urlMatch[1] : "";
    const paperMatch = input.match(/(https?:\/\/arxiv\.org\/[^\s]+)/);
    const paperUrl = paperMatch ? paperMatch[1] : "";
    const userPrompt = input
      .replace(urlMatch?.[0] || "", "")
      .replace(paperMatch?.[0] || "", "")
      .trim();

    if (!githubUrl) {
      setInput("");
      return;
    }

    try {
      const inst = await apiPost<{ id: number }>("/api/claw-instances", {
        github_url: githubUrl,
        paper_url: paperUrl || null,
        user_prompt: userPrompt || null,
      });
      setInput("");
      navigate(`/reproduce/task/${inst.id}`);
    } catch { /* ignore */ }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as FormEvent);
    }
  }

  const isRunning = instance?.status === "running" || instance?.status === "pending";

  return (
    <div className="flex-1 flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-8 py-8">
        <div className="max-w-4xl mx-auto space-y-6">
          {messages.map((msg, i) => (
            <MessageBubble key={i} message={msg} />
          ))}

          {/* Terminal logs inline */}
          {logs.length > 0 && (
            <div className="flex gap-4">
              <AgentAvatar />
              <div className="flex flex-col gap-2 w-full max-w-[85%]">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Execution Terminal</span>
                  {isRunning && <PulsingDot />}
                </div>
                <div className="border border-slate-200 rounded-xl bg-slate-50 p-4 font-mono text-[12px] max-h-[300px] overflow-y-auto">
                  {logs.map((line, i) => (
                    <div key={i} className="text-slate-500">{line}</div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Stop button */}
          {isRunning && (
            <div className="flex justify-center">
              <button
                onClick={() => stopMutation.mutate()}
                disabled={stopMutation.isPending}
                className="px-4 py-2 rounded-xl border border-red-200 bg-red-50 text-red-600 text-[13px] font-medium hover:bg-red-100 transition-colors"
              >
                停止任务
              </button>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input bar (always visible) */}
      <div className="shrink-0 p-3 bg-white border-t border-slate-100">
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto">
          <div className="w-full flex items-end gap-3 rounded-xl border border-slate-200 bg-slate-50 focus-within:border-slate-300 focus-within:bg-white px-4 py-3 transition-colors">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isRunning ? "任务执行中，完成后可继续对话..." : "输入 GitHub URL 和复现指令..."}
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
        <span className="text-[13px] font-medium text-slate-800">OpenClaw Agent</span>
        {message.type === "status" ? (
          <div className="border border-slate-200 rounded-xl bg-white p-4">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
              <span className="text-[13px] text-slate-600">{message.content}</span>
            </div>
          </div>
        ) : (
          <div className="border border-slate-200 rounded-xl bg-white p-4 text-[14px] text-slate-600 leading-relaxed whitespace-pre-wrap">
            {message.content}
          </div>
        )}
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
