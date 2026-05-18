import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { apiFetch, clearToken } from "../lib/api";

interface ClawInstance {
  id: number;
  status: string;
  task_config: { github_url?: string };
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { data: instances, isLoading } = useQuery({
    queryKey: ["claw-instances"],
    queryFn: () => apiFetch<ClawInstance[]>("/api/claw-instances"),
    refetchInterval: 5000,
  });

  function logout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div style={{ maxWidth: 900, margin: "40px auto", padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>我的任务</h1>
        <div>
          <Link to="/tasks/new" style={{ marginRight: 16 }}>
            + 新建任务
          </Link>
          <button onClick={logout} style={{ cursor: "pointer" }}>
            退出
          </button>
        </div>
      </div>

      {isLoading && <p>加载中...</p>}

      {instances && instances.length === 0 && (
        <p style={{ color: "#666" }}>暂无任务，点击「新建任务」开始</p>
      )}

      {instances && instances.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #ddd", textAlign: "left" }}>
              <th style={{ padding: 8 }}>ID</th>
              <th style={{ padding: 8 }}>GitHub URL</th>
              <th style={{ padding: 8 }}>状态</th>
              <th style={{ padding: 8 }}>创建时间</th>
              <th style={{ padding: 8 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {instances.map((inst) => (
              <tr key={inst.id} style={{ borderBottom: "1px solid #eee" }}>
                <td style={{ padding: 8 }}>{inst.id}</td>
                <td style={{ padding: 8, maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {inst.task_config.github_url || "-"}
                </td>
                <td style={{ padding: 8 }}>
                  <StatusBadge status={inst.status} />
                </td>
                <td style={{ padding: 8 }}>{new Date(inst.created_at).toLocaleString()}</td>
                <td style={{ padding: 8 }}>
                  <Link to={`/tasks/${inst.id}`}>详情</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "#f59e0b",
    running: "#3b82f6",
    completed: "#10b981",
    stopped: "#6b7280",
    failed: "#ef4444",
  };
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: 4,
        background: colors[status] || "#999",
        color: "#fff",
        fontSize: 12,
      }}
    >
      {status}
    </span>
  );
}
