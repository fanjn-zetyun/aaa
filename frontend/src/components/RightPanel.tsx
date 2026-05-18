import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../lib/api";

interface ClawInstance {
  id: number;
  status: string;
  pid: number | null;
  task_config: { github_url?: string; paper_url?: string; user_prompt?: string };
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export default function RightPanel() {
  const { taskId: id } = useParams();

  const { data: instance } = useQuery({
    queryKey: ["claw-instance", id],
    queryFn: () => apiFetch<ClawInstance>(`/api/claw-instances/${id}`),
    enabled: !!id,
    refetchInterval: 3000,
  });

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
      {/* Section: Environment */}
      <div className="flex flex-col border-b border-slate-100">
        <div className="px-5 py-4 bg-slate-50/50 flex items-center justify-between">
          <h3 className="text-[13px] font-semibold text-slate-700">环境与状态</h3>
          <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* Task Status */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div>
                <div className="text-[12px] font-medium text-slate-700">任务状态</div>
                <div className="text-[10px] text-slate-400 capitalize">{instance?.status || "—"}</div>
              </div>
            </div>
            {instance?.status && <TaskStatusBadge status={instance.status} />}
          </div>

          {/* Compute Node */}
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-orange-50 flex items-center justify-center text-orange-600">
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clipRule="evenodd" />
              </svg>
            </div>
            <div>
              <div className="text-[12px] font-medium text-slate-700">Compute Node</div>
              <div className="text-[10px] text-slate-400">Lab4AI Cluster</div>
            </div>
          </div>

          {/* Agent Engine */}
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-slate-100 flex items-center justify-center text-slate-600">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
              </svg>
            </div>
            <div>
              <div className="text-[12px] font-medium text-slate-700">Agent Engine</div>
              <div className="text-[10px] text-slate-400">OpenClaw (Active)</div>
            </div>
          </div>
        </div>
      </div>

      {/* Section: Task Info */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-5 py-4 bg-slate-50/50 flex items-center justify-between border-b border-slate-100">
          <h3 className="text-[13px] font-semibold text-slate-700">任务信息</h3>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 text-[12px]">
          {instance?.task_config.github_url && (
            <div>
              <div className="text-slate-400 mb-1">GitHub</div>
              <a
                href={instance.task_config.github_url}
                target="_blank"
                rel="noreferrer"
                className="text-blue-600 hover:underline break-all"
              >
                {instance.task_config.github_url.replace("https://github.com/", "")}
              </a>
            </div>
          )}
          {instance?.task_config.paper_url && (
            <div>
              <div className="text-slate-400 mb-1">论文</div>
              <a
                href={instance.task_config.paper_url}
                target="_blank"
                rel="noreferrer"
                className="text-blue-600 hover:underline break-all"
              >
                {instance.task_config.paper_url}
              </a>
            </div>
          )}
          {instance?.task_config.user_prompt && (
            <div>
              <div className="text-slate-400 mb-1">指令</div>
              <p className="text-slate-600">{instance.task_config.user_prompt}</p>
            </div>
          )}
          {instance?.created_at && (
            <div>
              <div className="text-slate-400 mb-1">创建时间</div>
              <p className="text-slate-600">{new Date(instance.created_at).toLocaleString()}</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

function TaskStatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-amber-100 text-amber-700",
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
