import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch, getToken } from "../lib/api";

interface ClawInstance {
  id: number;
  status: string;
  pid: number | null;
  task_config: { github_url?: string; paper_url?: string; user_prompt?: string };
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [logs, setLogs] = useState<string[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const { data: instance } = useQuery({
    queryKey: ["claw-instance", id],
    queryFn: () => apiFetch<ClawInstance>(`/api/claw-instances/${id}`),
    refetchInterval: 3000,
  });

  const stopMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/api/claw-instances/${id}/stop`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["claw-instance", id] }),
  });

  useEffect(() => {
    if (!id) return;
    const token = getToken();
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/claw-instances/${id}/logs?token=${token}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      setLogs((prev) => [...prev, event.data]);
    };
    ws.onclose = () => {};

    return () => {
      ws.close();
    };
  }, [id]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  if (!instance) return <p style={{ padding: 24 }}>加载中...</p>;

  const isRunning = instance.status === "running" || instance.status === "pending";

  return (
    <div style={{ maxWidth: 900, margin: "40px auto", padding: 24 }}>
      <button onClick={() => navigate("/dashboard")} style={{ marginBottom: 16 }}>
        ← 返回列表
      </button>

      <h1>任务 #{instance.id}</h1>

      <table style={{ marginBottom: 24 }}>
        <tbody>
          <tr>
            <td style={{ padding: "4px 16px 4px 0", fontWeight: "bold" }}>状态</td>
            <td>{instance.status}</td>
          </tr>
          <tr>
            <td style={{ padding: "4px 16px 4px 0", fontWeight: "bold" }}>GitHub</td>
            <td>{instance.task_config.github_url || "-"}</td>
          </tr>
          <tr>
            <td style={{ padding: "4px 16px 4px 0", fontWeight: "bold" }}>论文</td>
            <td>{instance.task_config.paper_url || "-"}</td>
          </tr>
          <tr>
            <td style={{ padding: "4px 16px 4px 0", fontWeight: "bold" }}>指令</td>
            <td>{instance.task_config.user_prompt || "-"}</td>
          </tr>
          {instance.error_message && (
            <tr>
              <td style={{ padding: "4px 16px 4px 0", fontWeight: "bold", color: "red" }}>
                错误
              </td>
              <td style={{ color: "red" }}>{instance.error_message}</td>
            </tr>
          )}
        </tbody>
      </table>

      {isRunning && (
        <button
          onClick={() => stopMutation.mutate()}
          disabled={stopMutation.isPending}
          style={{ marginBottom: 16, padding: "8px 16px", background: "#ef4444", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}
        >
          停止任务
        </button>
      )}

      <h2>实时日志</h2>
      <div
        style={{
          background: "#1e1e1e",
          color: "#d4d4d4",
          padding: 16,
          borderRadius: 8,
          height: 400,
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: 13,
          lineHeight: 1.6,
        }}
      >
        {logs.length === 0 && <span style={{ color: "#666" }}>等待日志...</span>}
        {logs.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
        <div ref={logsEndRef} />
      </div>
    </div>
  );
}
