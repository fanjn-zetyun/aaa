import { Link, useLocation, useNavigate } from "react-router-dom";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch, clearToken } from "../lib/api";

interface Conversation {
  id: number;
  status: string;
  title: string;
  metadata: { github_url?: string };
  created_at: string;
}

interface QuotaInfo {
  gpu_quota_hours: number;
  cpu_quota_hours: number;
  gpu_used_hours: number;
  cpu_used_hours: number;
}

const NAV_ITEMS = [
  {
    path: "/search",
    label: "智能论文检索",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    ),
  },
  {
    path: "/reproduce",
    label: "代码与论文复现",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
      </svg>
    ),
  },
  {
    path: "/paper-only",
    label: "纯论文(无代码)复现",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    path: "/experiments",
    label: "自动化实验矩阵",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
      </svg>
    ),
  },
  { path: "divider", label: "", icon: null },
  {
    path: "/polish",
    label: "智能论文润色",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
      </svg>
    ),
  },
  {
    path: "/model-settings",
    label: "模型设置",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      </svg>
    ),
  },
];

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [historyOpen, setHistoryOpen] = useState(false);

  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: () => apiFetch<Conversation[]>("/api/conversations"),
    refetchInterval: 5000,
  });

  const { data: quota } = useQuery({
    queryKey: ["quota"],
    queryFn: () => apiFetch<QuotaInfo>("/api/cloud-instances/quota"),
    refetchInterval: 30000,
  });

  function logout() {
    clearToken();
    navigate("/login");
  }

  function extractRepoName(url?: string) {
    if (!url) return "未命名任务";
    const match = url.match(/github\.com\/[^/]+\/([^/]+)/);
    return match ? match[1] : url.slice(0, 24);
  }

  return (
    <aside className="h-full w-full bg-[#FCFCFC] flex flex-col z-10 overflow-hidden">
      {/* Logo */}
      <div className="h-[72px] flex items-center px-6 border-b border-transparent">
        <Link to="/" className="flex items-center gap-2 font-bold tracking-wide text-slate-800 text-ui-title">
          <svg className="w-5 h-5 text-orange-600" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v1.85c2.95 1.3 5 4.25 5 7.65 0 1.61-.46 3.1-1.2 4.36z" />
          </svg>
          AutoResearch24
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-4 py-4 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map((item, i) => {
          if (item.path === "divider") {
            return <div key={i} className="my-3 border-t border-slate-100 mx-2" />;
          }
          const isActive = location.pathname.startsWith(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-ui-body transition-colors ${
                isActive
                  ? "bg-slate-100 font-medium text-slate-800"
                  : "text-slate-500 hover:bg-slate-100"
              }`}
            >
              <span className={isActive ? "text-slate-700" : "text-slate-400"}>
                {item.icon}
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* History (collapsible) */}
      <div className="border-t border-slate-100">
        <button
          onClick={() => setHistoryOpen(!historyOpen)}
          className="w-full px-6 py-3 flex items-center justify-between text-ui-small text-slate-500 hover:text-slate-700 transition-colors"
        >
          <span className="font-medium">历史任务</span>
          <svg
            className={`w-3.5 h-3.5 transition-transform ${historyOpen ? "rotate-180" : ""}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {historyOpen && (
          <div className="px-4 pb-3 max-h-[200px] overflow-y-auto space-y-0.5">
            {conversations?.map((inst) => (
              <Link
                key={inst.id}
                to={`/reproduce/task/${inst.id}`}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-ui-meta text-slate-500 hover:bg-slate-50 transition-colors"
              >
                <StatusDot status={inst.status} />
                <span className="truncate">{inst.title || extractRepoName(inst.metadata.github_url)}</span>
              </Link>
            ))}
            {(!conversations || conversations.length === 0) && (
              <p className="text-ui-meta text-slate-400 px-3 py-2">暂无历史任务</p>
            )}
          </div>
        )}
      </div>

      {/* Quota Display */}
      {quota && (quota.gpu_quota_hours > 0 || quota.cpu_quota_hours > 0) && (
        <div className="px-4 py-3 border-t border-slate-100">
          <QuotaBar label="GPU" used={quota.gpu_used_hours} total={quota.gpu_quota_hours} />
          <QuotaBar label="CPU" used={quota.cpu_used_hours} total={quota.cpu_quota_hours} />
        </div>
      )}

      {/* User Profile */}
      <div className="p-4 border-t border-slate-100">
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center text-slate-500 text-ui-meta font-medium">
              U
            </div>
            <div className="flex flex-col">
              <span className="text-ui-small font-medium text-slate-700">Researcher</span>
              <span className="text-ui-micro text-slate-400">Pro Plan</span>
            </div>
          </div>
          <button
            onClick={logout}
            className="text-slate-400 hover:text-slate-600 transition-colors"
            title="退出登录"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
          </button>
        </div>
      </div>
    </aside>
  );
}

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-amber-400",
    running: "bg-blue-500 animate-pulse",
    completed: "bg-green-500",
    stopped: "bg-slate-400",
    failed: "bg-red-500",
  };
  return <span className={`w-2 h-2 rounded-full shrink-0 ${colors[status] || "bg-slate-300"}`} />;
}

function QuotaBar({ label, used, total }: { label: string; used: number; total: number }) {
  if (total <= 0) return null;
  const pct = Math.min((used / total) * 100, 100);
  const isExhausted = used >= total;
  return (
    <div className="mb-2 last:mb-0">
      <div className="flex justify-between text-ui-micro mb-1">
        <span className={isExhausted ? "text-red-500 font-medium" : "text-slate-500"}>{label}</span>
        <span className="text-slate-400">{used.toFixed(1)}/{total.toFixed(0)}h</span>
      </div>
      <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${isExhausted ? "bg-red-400" : pct > 80 ? "bg-amber-400" : "bg-blue-400"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
