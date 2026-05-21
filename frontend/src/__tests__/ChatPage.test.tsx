import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ChatPage from "../pages/ChatPage";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;

  readyState = MockWebSocket.OPEN;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  close() {
    this.readyState = 3;
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
  }
}

function renderChat() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/reproduce/task/7"]}>
        <Routes>
          <Route path="/reproduce/task/:taskId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("ChatPage", () => {
  let conversationPayload: {
    id: number;
    title: string;
    status: string;
    task_type: string;
    updated_at: string;
    metadata: Record<string, unknown>;
    messages: Array<{
      id: number;
      role: "user" | "assistant" | "tool" | "system";
      content: string;
      message_metadata: Record<string, unknown>;
      created_at: string;
    }>;
  };

  beforeEach(() => {
    localStorage.setItem("access_token", "token");
    Element.prototype.scrollIntoView = vi.fn();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    conversationPayload = {
      id: 7,
      title: "PhotoDoodle",
      status: "running",
      task_type: "reproduce",
      updated_at: "2026-05-20T00:00:00Z",
      metadata: {},
      messages: [
        {
          id: 1,
          role: "user",
          content: "帮我复现 PhotoDoodle",
          message_metadata: {},
          created_at: "2026-05-20T00:00:00Z",
        },
      ],
    };
    globalThis.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(conversationPayload),
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("renders streamed assistant deltas, tool timeline, and skill workflow board in one round", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "progress",
        run_id: "run-1",
        stage: "skill_selection",
        content: "已选择 skill：lab4ai-auto-reproduct。",
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "workflow_loaded",
        run_id: "run-1",
        workflow: {
          name: "Lab4AI_Auto_Reproduction_Pipeline",
          steps: [
            { id: "step_1_audit", name: "项目与论文双重审计", status: "running" },
          ],
        },
        timestamp: "2026-05-20T00:00:02Z",
      });
      ws.emit({
        seq: 3,
        type: "workflow_step_progress",
        run_id: "run-1",
        workflow_step_id: "step_1_audit",
        content: "Invoking tool: analyze_repo",
        step: {
          id: "step_1_audit",
          name: "项目与论文双重审计",
          status: "running",
        },
        timestamp: "2026-05-20T00:00:02Z",
      });
      ws.emit({
        seq: 4,
        type: "tool_started",
        run_id: "run-1",
        tool_name: "analyze_repo",
        tool_input: { github_url: "https://github.com/showlab/PhotoDoodle" },
        timestamp: "2026-05-20T00:00:02Z",
      });
      ws.emit({
        seq: 5,
        type: "tool_completed",
        run_id: "run-1",
        tool_name: "analyze_repo",
        ok: true,
        message: {
          id: 2,
          role: "tool",
          content: "已识别仓库 showlab/PhotoDoodle。",
          message_metadata: { tool_name: "analyze_repo", ok: true },
          created_at: "2026-05-20T00:00:03Z",
        },
      });
      ws.emit({
        seq: 6,
        type: "workflow_step_completed",
        run_id: "run-1",
        workflow_step_id: "step_1_audit",
        step: {
          id: "step_1_audit",
          name: "项目与论文双重审计",
          status: "completed",
          output: "score=75；已完成项目与论文审计的 MVP 记录。",
        },
        timestamp: "2026-05-20T00:00:03Z",
      });
      ws.emit({
        seq: 7,
        type: "assistant_started",
        run_id: "run-1",
        timestamp: "2026-05-20T00:00:04Z",
      });
      ws.emit({ seq: 8, type: "assistant_delta", run_id: "run-1", delta: "第一段" });
      ws.emit({ seq: 9, type: "assistant_delta", run_id: "run-1", delta: "，第二段" });
    });

    expect(await screen.findByText("执行过程")).toBeInTheDocument();
    expect(screen.getByText("复现流水线实时看板:")).toBeInTheDocument();
    expect(screen.getByText(/项目与论文双重审计/)).toBeInTheDocument();
    expect(screen.getByText("✅ 完成")).toBeInTheDocument();
    expect(screen.getByText("选择复现流程")).toBeInTheDocument();
    expect(screen.getByText("分析 GitHub 仓库")).toBeInTheDocument();
    expect(screen.getByText("已识别仓库 showlab/PhotoDoodle。")).toBeInTheDocument();
    expect(screen.getByText("第一段，第二段")).toBeInTheDocument();
  });

  it("ignores replayed websocket events by seq", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({ seq: 1, type: "assistant_started", run_id: "run-1" });
      ws.emit({ seq: 2, type: "assistant_delta", run_id: "run-1", delta: "只出现一次" });
      ws.emit({ seq: 2, type: "assistant_delta", run_id: "run-1", delta: "重复内容" });
    });

    expect(await screen.findByText("只出现一次")).toBeInTheDocument();
    expect(screen.queryByText("只出现一次重复内容")).not.toBeInTheDocument();
  });

  it("starts a new agent bubble for the user reply after waiting confirmation", async () => {
    conversationPayload.status = "active";
    conversationPayload.metadata = {
      workflow_state: "waiting_for_user",
      pending_user_input: {
        question: "是否继续创建 CPU 实例？",
        options: ["继续执行"],
        tool_name: "lab4ai_create_instance",
      },
    };
    conversationPayload.messages = [
      ...conversationPayload.messages,
      {
        id: 2,
        role: "assistant",
        content: "上一轮内容",
        message_metadata: {},
        created_at: "2026-05-20T00:00:30Z",
      },
    ];

    renderChat();

    expect(await screen.findByText("等待你确认")).toBeInTheDocument();
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "创建 Lab4AI 实例" })).getByRole("button", {
        name: "继续执行",
      })
    );

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/conversations/7/messages",
        expect.objectContaining({ method: "POST" })
      );
    });

    conversationPayload.status = "running";
    conversationPayload.metadata = {};
    conversationPayload.messages = [
      ...conversationPayload.messages,
      {
        id: 3,
        role: "user",
        content: "继续执行",
        message_metadata: {},
        created_at: "2026-05-20T00:01:00Z",
      },
    ];

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(1);
    });
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => {
      ws.emit({ seq: 1, type: "assistant_started", run_id: "run-same" });
      ws.emit({ seq: 2, type: "assistant_delta", run_id: "run-same", delta: "下一轮内容" });
    });

    expect(await screen.findByText("下一轮内容")).toBeInTheDocument();
    expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(2);
  });

  it("opens Lab4AI credential dialog and continues after saving admin settings", async () => {
    conversationPayload.status = "active";
    conversationPayload.metadata = {
      workflow_state: "waiting_for_user",
      pending_user_input: {
        question: "Lab4AI 凭证未配置，请先由管理员配置平台账号。",
        options: ["已完成配置，继续执行", "停止任务"],
        tool_name: "lab4ai_create_instance",
        intervention: {
          type: "lab4ai_credentials_required",
          title: "需要配置 Lab4AI 平台账号",
        },
      },
    };
    globalThis.fetch = vi.fn().mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/admin/settings/lab4ai" && options?.method === "PUT") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ configured: true, phone_masked: "138****8000" }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(conversationPayload),
      });
    });

    renderChat();

    expect(await screen.findByRole("dialog", { name: "需要配置 Lab4AI 平台账号" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Lab4AI 手机号"), {
      target: { value: "13800138000" },
    });
    fireEvent.change(screen.getByLabelText("Lab4AI 密码"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存并继续执行" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/admin/settings/lab4ai",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ phone: "13800138000", password: "secret" }),
        })
      );
    });
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/conversations/7/messages",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ content: "已完成配置，继续执行" }),
        })
      );
    });
  });
});
