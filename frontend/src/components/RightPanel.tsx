import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../lib/api";

interface Conversation {
  id: number;
  title: string;
  status: string;
  task_type: string;
  metadata: { github_url?: string; paper_url?: string; intent_hint?: string };
  created_at: string;
  updated_at: string;
  messages: ConversationMessage[];
}

interface ConversationMessage {
  id: number;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  message_metadata: Record<string, unknown>;
  created_at: string;
}

export default function RightPanel() {
  const { taskId: id } = useParams();

  const { data: conversation } = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => apiFetch<Conversation>(`/api/conversations/${id}`),
    enabled: !!id,
    refetchInterval: 3000,
  });

  const toolEvents = (conversation?.messages || []).filter((message) => message.role === "tool");

  if (!id) {
    return (
      <aside className="w-[280px] bg-white border-l border-slate-200 flex flex-col z-10 shrink-0">
        <div className="flex-1 flex items-center justify-center">
          <p className="text-[13px] text-slate-400">选择或创建任务查看详情</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="w-[280px] bg-white border-l border-slate-200 flex flex-col z-10 shrink-0">
      <div className="flex flex-col border-b border-slate-100">
        <div className="px-5 py-4 bg-slate-50/50 flex items-center justify-between">
          <h3 className="text-[13px] font-semibold text-slate-700">环境与状态</h3>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[12px] font-medium text-slate-700">对话状态</div>
              <div className="text-[10px] text-slate-400 capitalize">
                {conversation?.status || "-"}
              </div>
            </div>
            {conversation?.status && <TaskStatusBadge status={conversation.status} />}
          </div>

          <PanelItem label="Agent Engine" value="V2 Agent Loop" />
          <PanelItem label="Tool Layer" value="Lab4AI / SSH / Repo Analysis" />
        </div>
      </div>

      <div className="min-h-[220px] flex flex-col overflow-hidden border-b border-slate-100">
        <div className="px-5 py-4 bg-slate-50/50 flex items-center justify-between border-b border-slate-100">
          <h3 className="text-[13px] font-semibold text-slate-700">Tool Events</h3>
          {conversation?.status === "running" && <PulsingDot />}
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {toolEvents.length === 0 ? (
            <div className="text-[12px] text-slate-400">暂无工具事件</div>
          ) : (
            toolEvents.map((event) => <ToolEventItem key={event.id} event={event} />)
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-5 py-4 bg-slate-50/50 flex items-center justify-between border-b border-slate-100">
          <h3 className="text-[13px] font-semibold text-slate-700">任务信息</h3>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 text-[12px]">
          <PanelItem label="标题" value={conversation?.title || "-"} />
          <PanelItem label="类型" value={conversation?.task_type || "-"} />
          {conversation?.metadata.github_url && (
            <LinkItem label="GitHub" href={conversation.metadata.github_url} />
          )}
          {conversation?.metadata.paper_url && (
            <LinkItem label="论文" href={conversation.metadata.paper_url} />
          )}
          {conversation?.created_at && (
            <PanelItem label="创建时间" value={new Date(conversation.created_at).toLocaleString()} />
          )}
        </div>
      </div>
    </aside>
  );
}

function ToolEventItem({ event }: { event: ConversationMessage }) {
  const toolName = String(event.message_metadata.tool_name || "tool");
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[11px] font-semibold text-slate-600">
          {toolName}
        </span>
        <span className="shrink-0 text-[10px] text-slate-400">
          {formatPanelTime(event.created_at)}
        </span>
      </div>
      <div className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-slate-500">
        {event.content}
      </div>
    </div>
  );
}

function PanelItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate-400 mb-1">{label}</div>
      <div className="text-slate-600 break-all">{value}</div>
    </div>
  );
}

function LinkItem({ label, href }: { label: string; href: string }) {
  return (
    <div>
      <div className="text-slate-400 mb-1">{label}</div>
      <a href={href} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline break-all">
        {href}
      </a>
    </div>
  );
}

function TaskStatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    active: "bg-slate-100 text-slate-600",
    running: "bg-blue-100 text-blue-700",
    completed: "bg-green-100 text-green-700",
    stopped: "bg-slate-100 text-slate-600",
    failed: "bg-red-100 text-red-700",
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${styles[status] || "bg-slate-100 text-slate-600"}`}>
      {status}
    </span>
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

function formatPanelTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
