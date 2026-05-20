import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../lib/api";

interface Conversation {
  id: number;
  title: string;
  status: string;
  task_type: string;
  metadata: {
    github_url?: string;
    paper_url?: string;
    intent_hint?: string;
    workflow_state?: string;
    pending_user_input?: {
      question: string;
      tool_name?: string;
    } | null;
    memory?: {
      decisions?: Array<{ step?: string; outcome?: string; answer?: string }>;
      artifacts?: string[];
    };
  };
  created_at: string;
  updated_at: string;
}

interface WorkspaceFile {
  path: string;
  name: string;
  kind: "file" | "directory" | "symlink";
  size: number | null;
  modified_at: string | null;
  depth: number;
}

interface WorkspaceFilesResponse {
  exists: boolean;
  root: string;
  files: WorkspaceFile[];
}

export default function RightPanel() {
  const { taskId: id } = useParams();

  const { data: conversation } = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => apiFetch<Conversation>(`/api/conversations/${id}`),
    enabled: !!id,
    refetchInterval: 3000,
  });

  const { data: workspaceFiles, isLoading: filesLoading } = useQuery({
    queryKey: ["workspace-files", id],
    queryFn: () => apiFetch<WorkspaceFilesResponse>(`/api/conversations/${id}/workspace-files`),
    enabled: !!id,
    refetchInterval: 5000,
  });

  if (!id) {
    return (
      <aside className="h-full w-full min-h-0 bg-white flex flex-col z-10 overflow-hidden">
        <div className="flex-1 flex items-center justify-center px-6 text-center">
          <p className="text-ui-small text-slate-400">选择或创建任务查看详情</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="h-full w-full min-h-0 bg-white flex flex-col z-10 overflow-hidden">
      <section className="h-[44%] min-h-[280px] shrink-0 flex flex-col border-b border-slate-200">
        <PanelHeader title="权限与环境配置" subtitle={conversation?.status || "loading"} />
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-5">
          <EnvironmentSection conversation={conversation} />
          <PermissionSection conversation={conversation} />
        </div>
      </section>

      <section className="flex-1 min-h-0 flex flex-col">
        <PanelHeader
          title="工作区文件"
          subtitle={workspaceFiles?.exists ? workspaceFiles.root : "未创建"}
        />
        <WorkspaceFileList data={workspaceFiles} loading={filesLoading} />
      </section>
    </aside>
  );
}

function EnvironmentSection({ conversation }: { conversation?: Conversation }) {
  const metadata = conversation?.metadata || {};
  return (
    <div>
      <SectionTitle label="环境" />
      <div className="space-y-2">
        <InfoRow label="Agent" value="V2 Agent Loop" />
        <InfoRow label="工具层" value="Lab4AI / SSH / Repo Analysis" />
        <InfoRow label="任务类型" value={taskTypeLabel(conversation?.task_type)} />
        <InfoRow label="运行状态" value={statusLabel(conversation?.status)} tone={statusTone(conversation?.status)} />
        {metadata.github_url && <LinkRow label="GitHub" href={metadata.github_url} />}
        {metadata.paper_url && <LinkRow label="论文" href={metadata.paper_url} />}
      </div>
    </div>
  );
}

function PermissionSection({ conversation }: { conversation?: Conversation }) {
  const metadata = conversation?.metadata || {};
  const pendingTool = metadata.pending_user_input?.tool_name;
  const decisions = metadata.memory?.decisions || [];
  const resourceApproved = decisions.some(
    (item) => item.step === "confirm_resource_creation" && item.outcome === "approved"
  );
  const isWaiting = metadata.workflow_state === "waiting_for_user";

  return (
    <div>
      <SectionTitle label="权限" />
      <div className="space-y-2">
        <PermissionRow
          label="创建算力实例"
          value={pendingTool === "lab4ai_create_instance" && isWaiting ? "等待确认" : resourceApproved ? "已确认" : "需要时确认"}
          tone={pendingTool === "lab4ai_create_instance" && isWaiting ? "warning" : resourceApproved ? "ok" : "neutral"}
        />
        <PermissionRow label="高风险 SSH 命令" value="按策略确认" tone="neutral" />
        <PermissionRow label="文件写入" value="后端工具受控" tone="neutral" />
        <PermissionRow label="凭证暴露" value="隐藏敏感文件" tone="ok" />
      </div>
    </div>
  );
}

function WorkspaceFileList({
  data,
  loading,
}: {
  data?: WorkspaceFilesResponse;
  loading: boolean;
}) {
  if (loading) {
    return <EmptyState text="正在读取工作区文件..." />;
  }

  if (!data?.exists) {
    return <EmptyState text="工作区尚未创建，任务开始执行后会在这里显示文件。" />;
  }

  if (data.files.length === 0) {
    return <EmptyState text="工作区暂无可显示文件。" />;
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto py-2">
      {data.files.map((file) => (
        <FileRow key={file.path} file={file} />
      ))}
    </div>
  );
}

function FileRow({ file }: { file: WorkspaceFile }) {
  return (
    <div
      className="group flex items-center gap-2 px-4 py-2 text-ui-meta hover:bg-slate-50"
      title={file.path}
      style={{ paddingLeft: `${16 + file.depth * 14}px` }}
    >
      <FileIcon kind={file.kind} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-slate-700">{file.name}</div>
        {file.kind === "file" && (
          <div className="mt-0.5 text-ui-micro text-slate-400">
            {formatSize(file.size)}
            {file.modified_at ? ` · ${formatPanelTime(file.modified_at)}` : ""}
          </div>
        )}
      </div>
    </div>
  );
}

function PanelHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="shrink-0 px-5 py-4 bg-slate-50/70 border-b border-slate-100">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-ui-title font-semibold text-slate-800">{title}</h3>
        <span className="truncate text-ui-micro uppercase tracking-wide text-slate-400">{subtitle}</span>
      </div>
    </div>
  );
}

function SectionTitle({ label }: { label: string }) {
  return <div className="mb-2 text-ui-meta font-semibold uppercase tracking-wide text-slate-400">{label}</div>;
}

function InfoRow({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "warning" | "danger";
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="shrink-0 text-ui-small text-slate-400">{label}</span>
      <span className={`min-w-0 break-words text-right text-ui-small ${toneClass(tone)}`}>{value}</span>
    </div>
  );
}

function LinkRow({ label, href }: { label: string; href: string }) {
  return (
    <div className="space-y-1">
      <div className="text-ui-small text-slate-400">{label}</div>
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="block break-all text-ui-small leading-relaxed text-blue-600 hover:underline"
      >
        {href}
      </a>
    </div>
  );
}

function PermissionRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "neutral" | "ok" | "warning" | "danger";
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-slate-100 px-3 py-2">
      <span className="text-ui-small text-slate-600">{label}</span>
      <span className={`shrink-0 text-ui-meta font-medium ${toneClass(tone)}`}>{value}</span>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex-1 min-h-0 flex items-center justify-center px-6 text-center">
      <p className="text-ui-small leading-relaxed text-slate-400">{text}</p>
    </div>
  );
}

function FileIcon({ kind }: { kind: WorkspaceFile["kind"] }) {
  if (kind === "directory") {
    return (
      <svg className="h-4 w-4 shrink-0 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M3 7h6l2 2h10v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
      </svg>
    );
  }
  if (kind === "symlink") {
    return (
      <svg className="h-4 w-4 shrink-0 text-violet-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M10 13a5 5 0 0 0 7.07 0l2-2a5 5 0 0 0-7.07-7.07l-1.15 1.15" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M14 11a5 5 0 0 0-7.07 0l-2 2A5 5 0 0 0 12 20.07l1.15-1.15" />
      </svg>
    );
  }
  return (
    <svg className="h-4 w-4 shrink-0 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M7 3h7l5 5v13H7V3Z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M14 3v5h5" />
    </svg>
  );
}

function toneClass(tone: "neutral" | "ok" | "warning" | "danger") {
  if (tone === "ok") return "text-green-600";
  if (tone === "warning") return "text-amber-600";
  if (tone === "danger") return "text-red-600";
  return "text-slate-600";
}

function statusTone(status?: string): "neutral" | "ok" | "warning" | "danger" {
  if (status === "completed") return "ok";
  if (status === "running" || status === "active") return "warning";
  if (status === "failed") return "danger";
  return "neutral";
}

function statusLabel(status?: string) {
  const labels: Record<string, string> = {
    active: "待执行",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    stopped: "已停止",
  };
  return status ? labels[status] || status : "-";
}

function taskTypeLabel(taskType?: string) {
  const labels: Record<string, string> = {
    reproduce: "代码与论文复现",
    search: "论文检索",
    paper_only: "纯论文分析",
    experiments: "实验设计",
    polish: "论文润色",
    general: "通用任务",
  };
  return taskType ? labels[taskType] || taskType : "-";
}

function formatSize(value: number | null) {
  if (value === null) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatPanelTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
