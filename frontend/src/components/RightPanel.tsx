import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../lib/api";
import { MarkdownContent } from "./MarkdownContent";

interface Conversation {
  id: number;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
}

interface RuntimeCredentialInstance {
  id: number;
  server_id: string;
  instance_id?: string | null;
  instance_type: string;
  status: string;
  username?: string | null;
  password?: string | null;
  ssh_host?: string | null;
  ssh_port?: number | null;
  ssh_command?: string | null;
  started_at: string;
  stopped_at?: string | null;
}

interface RuntimeLab4AICredentials {
  configured: boolean;
  phone_masked: string;
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

interface WorkspaceFileContentResponse {
  path: string;
  name: string;
  kind: "markdown";
  content: string;
}

interface RuntimeCredentialsResponse {
  lab4ai_credentials?: RuntimeLab4AICredentials;
  instances: RuntimeCredentialInstance[];
}

export default function RightPanel() {
  const { taskId: id } = useParams();
  const [previewPath, setPreviewPath] = useState<string | null>(null);

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

  const {
    data: workspacePreview,
    isLoading: previewLoading,
    isError: previewError,
    refetch: refetchPreview,
  } = useQuery({
    queryKey: ["workspace-file-preview", id, previewPath],
    queryFn: () =>
      apiFetch<WorkspaceFileContentResponse>(
        `/api/conversations/${id}/workspace-files/content?path=${encodeURIComponent(
          previewPath || ""
        )}`
      ),
    enabled: !!id && !!previewPath,
  });

  const { data: runtimeCredentials, isLoading: credentialsLoading } = useQuery({
    queryKey: ["runtime-credentials", id],
    queryFn: () => apiFetch<RuntimeCredentialsResponse>(`/api/conversations/${id}/runtime-credentials`),
    enabled: !!id,
    refetchInterval: 3000,
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
        <PanelHeader title="权限与环境配置" subtitle={statusLabel(conversation?.status)} />
        <RuntimeCredentialsSection data={runtimeCredentials} loading={credentialsLoading} />
      </section>

      <section className="flex-1 min-h-0 flex flex-col">
        <PanelHeader
          title="工作区文件"
          subtitle={workspaceFiles?.exists ? workspaceFiles.root : "未创建"}
        />
        {previewPath ? (
          <WorkspaceMarkdownPreview
            data={workspacePreview}
            loading={previewLoading}
            error={previewError}
            fallbackPath={previewPath}
            onBack={() => setPreviewPath(null)}
            onRefresh={() => refetchPreview()}
          />
        ) : (
          <WorkspaceFileList
            data={workspaceFiles}
            loading={filesLoading}
            onPreview={(file) => setPreviewPath(file.path)}
          />
        )}
      </section>
    </aside>
  );
}

function RuntimeCredentialsSection({
  data,
  loading,
}: {
  data?: RuntimeCredentialsResponse;
  loading: boolean;
}) {
  if (loading) {
    return <EmptyState text="正在读取 Lab4AI 实例连接信息..." />;
  }

  const instances = data?.instances || [];
  const lab4aiCredentials = data?.lab4ai_credentials;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4">
      <div className="space-y-4">
        <Lab4AILoginCredentialBlock credentials={lab4aiCredentials} />
        <div>
          <SectionTitle label="Lab4AI 实例" />
          {instances.length > 0 ? (
            <div className="space-y-3">
              {instances.map((instance) => (
                <InstanceCredentialBlock key={instance.id} instance={instance} />
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-ui-small text-slate-500">
              当前任务暂无 Lab4AI 实例连接信息。
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Lab4AILoginCredentialBlock({
  credentials,
}: {
  credentials?: RuntimeLab4AICredentials;
}) {
  const configured = !!credentials?.configured;
  return (
    <div
      data-testid="lab4ai-login-credentials"
      className="rounded-lg border border-slate-200 bg-white px-3 py-3"
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-ui-small font-semibold text-slate-800">Lab4AI 登录凭证</div>
          <div className="mt-0.5 text-ui-micro text-slate-400">
            平台统一账号，仅展示脱敏信息
          </div>
        </div>
        <span
          className={`shrink-0 rounded-md border px-2 py-0.5 text-ui-micro font-medium ${
            configured
              ? "border-emerald-100 bg-emerald-50 text-emerald-700"
              : "border-amber-100 bg-amber-50 text-amber-700"
          }`}
        >
          {configured ? "已登录" : "未配置"}
        </span>
      </div>
      <div className="space-y-2">
        <CredentialRow label="账号" value={credentials?.phone_masked || "-"} />
        <CredentialRow label="密码" value={configured ? "已安全保存" : "-"} />
      </div>
    </div>
  );
}

function InstanceCredentialBlock({ instance }: { instance: RuntimeCredentialInstance }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-ui-small font-semibold text-slate-800">
            {instanceTypeLabel(instance.instance_type)} · {instance.server_id}
          </div>
          {instance.instance_id && (
            <div className="mt-0.5 truncate text-ui-micro text-slate-400">
              {instance.instance_id}
            </div>
          )}
        </div>
        <span
          className={`shrink-0 rounded-md border px-2 py-0.5 text-ui-micro font-medium ${instanceStatusClass(
            instance.status
          )}`}
        >
          {instanceStatusLabel(instance.status)}
        </span>
      </div>
      <div className="space-y-2">
        <CredentialRow label="用户名" value={instance.username || "-"} />
        <CredentialRow label="密码" value={instance.password || "-"} />
        <CredentialRow label="SSH Host" value={instance.ssh_host || "-"} />
        <CredentialRow label="SSH Port" value={instance.ssh_port ? String(instance.ssh_port) : "-"} />
        <CredentialRow label="SSH 命令" value={instance.ssh_command || "-"} />
      </div>
    </div>
  );
}

function WorkspaceFileList({
  data,
  loading,
  onPreview,
}: {
  data?: WorkspaceFilesResponse;
  loading: boolean;
  onPreview: (file: WorkspaceFile) => void;
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
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="border-b border-slate-100 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-ui-small font-semibold text-slate-800">Workspace Artifacts</div>
            <div className="mt-0.5 text-ui-micro text-slate-400">
              Markdown 文件可直接预览，最终报告会优先展示。
            </div>
          </div>
          <span className="shrink-0 rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-ui-micro font-medium text-slate-500">
            {data.files.length} 项
          </span>
        </div>
      </div>
      <div className="py-2">
        {sortWorkspaceFiles(data.files).map((file) => (
          <FileRow key={file.path} file={file} onPreview={onPreview} />
        ))}
      </div>
    </div>
  );
}

function WorkspaceMarkdownPreview({
  data,
  loading,
  error,
  fallbackPath,
  onBack,
  onRefresh,
}: {
  data?: WorkspaceFileContentResponse;
  loading: boolean;
  error: boolean;
  fallbackPath: string;
  onBack: () => void;
  onRefresh: () => void;
}) {
  const displayPath = data?.path || fallbackPath;
  const isFinalReport = isFinalMarkdownReport(displayPath);

  return (
    <div
      data-testid="workspace-markdown-preview"
      className="flex-1 min-h-0 flex flex-col bg-slate-50/50"
    >
      <div className="shrink-0 border-b border-slate-200 bg-white px-4 py-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-ui-micro font-medium text-slate-600 hover:bg-slate-50"
            aria-label="返回文件列表"
          >
            <BackIcon />
            返回
          </button>
          <button
            type="button"
            onClick={onRefresh}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-ui-micro font-medium text-slate-600 hover:bg-slate-50"
            aria-label="刷新预览"
          >
            <RefreshIcon />
            刷新
          </button>
        </div>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md border border-blue-100 bg-blue-50 px-2 py-0.5 text-ui-micro font-semibold text-blue-700">
                Markdown 预览
              </span>
              {isFinalReport && (
                <span className="rounded-md border border-emerald-100 bg-emerald-50 px-2 py-0.5 text-ui-micro font-semibold text-emerald-700">
                  最终报告
                </span>
              )}
            </div>
            <div className="mt-2 truncate text-ui-small font-semibold text-slate-800">
              {data?.name || fileNameFromPath(fallbackPath)}
            </div>
            <div className="mt-0.5 break-all text-ui-micro text-slate-400">
              {displayPath}
            </div>
          </div>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {loading ? (
          <div className="rounded-lg border border-slate-100 bg-white px-3 py-3 text-ui-small text-slate-500">
            正在读取 Markdown 预览...
          </div>
        ) : error ? (
          <div className="rounded-lg border border-red-100 bg-red-50 px-3 py-3 text-ui-small text-red-700">
            Markdown 文件读取失败，请返回文件列表后重试。
          </div>
        ) : (
          <article className="mx-auto max-w-[760px] rounded-lg border border-slate-200 bg-white px-4 py-4 shadow-sm">
            <MarkdownContent content={data?.content || ""} variant="workspace" />
          </article>
        )}
      </div>
    </div>
  );
}

function FileRow({
  file,
  onPreview,
}: {
  file: WorkspaceFile;
  onPreview: (file: WorkspaceFile) => void;
}) {
  const isMarkdown = file.kind === "file" && isMarkdownFile(file.name);
  const isFinalReport = isFinalMarkdownReport(file.path);
  const rowClass = `group flex w-full items-center gap-2 px-4 py-2.5 text-left text-ui-meta ${
    isFinalReport ? "bg-emerald-50/70 hover:bg-emerald-50" : "hover:bg-slate-50"
  }`;
  const content = (
    <>
      <FileIcon kind={file.kind} markdown={isMarkdown} finalReport={isFinalReport} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <div className="truncate font-medium text-slate-700">{file.name}</div>
          {isFinalReport ? (
            <span className="shrink-0 rounded-md border border-emerald-100 bg-white px-1.5 py-0.5 text-ui-micro font-semibold text-emerald-700">
              最终报告
            </span>
          ) : isMarkdown ? (
            <span className="shrink-0 rounded-md border border-blue-100 bg-blue-50 px-1.5 py-0.5 text-ui-micro font-semibold text-blue-700">
              MD
            </span>
          ) : null}
        </div>
        {file.kind === "file" && (
          <div className="mt-0.5 text-ui-micro text-slate-400">
            {formatSize(file.size)}
            {file.modified_at ? ` · ${formatPanelTime(file.modified_at)}` : ""}
          </div>
        )}
      </div>
    </>
  );

  if (isMarkdown) {
    return (
      <button
        type="button"
        aria-label={isFinalReport ? `预览最终报告 ${file.name}` : file.name}
        onClick={() => onPreview(file)}
        className={rowClass}
        title={file.path}
        style={{ paddingLeft: `${16 + file.depth * 14}px` }}
      >
        {content}
      </button>
    );
  }

  return (
    <div
      className={rowClass}
      title={file.path}
      style={{ paddingLeft: `${16 + file.depth * 14}px` }}
    >
      {content}
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

function CredentialRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-3 text-ui-small">
      <span className="text-slate-400">{label}</span>
      <span className="min-w-0 break-all font-mono text-slate-700">{value}</span>
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

function FileIcon({
  kind,
  markdown = false,
  finalReport = false,
}: {
  kind: WorkspaceFile["kind"];
  markdown?: boolean;
  finalReport?: boolean;
}) {
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
  if (finalReport) {
    return (
      <svg className="h-4 w-4 shrink-0 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M7 3h7l5 5v13H7V3Z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M14 3v5h5" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M9 14h6M9 17h4" />
      </svg>
    );
  }
  if (markdown) {
    return (
      <svg className="h-4 w-4 shrink-0 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M4 5h16v14H4V5Z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M7 15V9l3 4 3-4v6M16 9v6m0 0 2-2m-2 2-2-2" />
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

function BackIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M15 6 9 12l6 6" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M20 6v5h-5" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M4 18v-5h5" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M18 9a7 7 0 0 0-11.9-2M6 15a7 7 0 0 0 11.9 2" />
    </svg>
  );
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

function instanceTypeLabel(value: string) {
  const normalized = value.toUpperCase();
  if (normalized === "CPU") return "CPU 实例";
  if (normalized === "GPU") return "GPU 实例";
  return `${value} 实例`;
}

function instanceStatusLabel(status: string) {
  const labels: Record<string, string> = {
    running: "运行中",
    stopped: "已停止",
  };
  return labels[status] || status;
}

function instanceStatusClass(status: string) {
  if (status === "running") return "border-emerald-100 bg-emerald-50 text-emerald-700";
  if (status === "stopped") return "border-slate-100 bg-slate-50 text-slate-500";
  return "border-amber-100 bg-amber-50 text-amber-700";
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

function isMarkdownFile(name: string) {
  const lower = name.toLowerCase();
  return lower.endsWith(".md") || lower.endsWith(".markdown");
}

function isFinalMarkdownReport(path: string) {
  const lower = path.toLowerCase();
  return isMarkdownFile(lower) && lower.includes("final_repro_report");
}

function sortWorkspaceFiles(files: WorkspaceFile[]) {
  return [...files].sort((a, b) => {
    const aFinal = isFinalMarkdownReport(a.path);
    const bFinal = isFinalMarkdownReport(b.path);
    if (aFinal !== bFinal) return aFinal ? -1 : 1;
    return 0;
  });
}

function fileNameFromPath(path: string) {
  return path.split("/").pop() || path;
}
