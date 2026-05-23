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

  it("shows model-selected skill evidence from conversation metadata", async () => {
    conversationPayload.metadata = {
      task_type: "reproduce",
      github_url: "https://github.com/jsnzwu/motion-guided-flow",
      skill_selection: {
        selected_skill: "lab4ai-auto-reproduct",
        source: "model",
        model_choice: "lab4ai-auto-reproduct",
        fallback_choice: null,
        reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
        confidence: null,
        error: null,
      },
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_steps: [],
    };

    renderChat();

    expect(await screen.findByText("模型选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
    expect(screen.getByText("模型选择")).toBeInTheDocument();

    fireEvent.click(screen.getByText("查看选择证据"));

    expect(screen.getByText("source")).toBeInTheDocument();
    expect(screen.getByText("model")).toBeInTheDocument();
    expect(screen.getByText("model_choice")).toBeInTheDocument();
    expect(screen.getAllByText("lab4ai-auto-reproduct").length).toBeGreaterThan(0);
    expect(screen.queryByText("workflow_context")).not.toBeInTheDocument();
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
          progress: ["Invoking tool: analyze_repo"],
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
          tool_calls: [
            {
              tool_call_id: "tool-1",
              name: "analyze_repo",
              status: "completed",
              ok: true,
            },
          ],
        },
        timestamp: "2026-05-20T00:00:03Z",
      });
      ws.emit({
        seq: 7,
        type: "assistant_started",
        run_id: "run-1",
        timestamp: "2026-05-20T00:00:04Z",
      });
      ws.emit({
        seq: 8,
        type: "assistant_delta",
        run_id: "run-1",
        delta: "工具执行结果如下\n| 序号 | 执行步骤 | 当前状态 | 核心产出 / 详情 |\n| --- | --- | --- | --- |\n| 1 | `step_1_audit`: 项目与论文双重审计 | ✅ 完成 | score=75 |\n最终结论：仓库审计已完成，下一步需要创建 CPU 实例。",
      });
    });

    expect(await screen.findByText("执行过程")).toBeInTheDocument();
    expect(screen.getByText("思考过程")).toBeInTheDocument();
    expect(screen.getByText("工作流已加载")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "复现流水线实时看板: PhotoDoodle" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("执行过程与结果")).toBeInTheDocument();
    expect(screen.getAllByText(/项目与论文双重审计/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("完成").length).toBeGreaterThan(0);
    expect(screen.getAllByText("正在分析仓库。").length).toBeGreaterThan(0);
    expect(screen.getAllByText("分析 GitHub 仓库").length).toBeGreaterThan(0);
    expect(screen.getByText("选择复现流程")).toBeInTheDocument();
    expect(screen.getByText("已识别仓库 showlab/PhotoDoodle。")).toBeInTheDocument();
    expect(screen.getByText("最终结论：仓库审计已完成，下一步需要创建 CPU 实例。")).toBeInTheDocument();

    const finalAnswer = screen.getByText("最终回答").parentElement;
    expect(finalAnswer).toHaveTextContent("最终结论：仓库审计已完成，下一步需要创建 CPU 实例。");
    expect(finalAnswer).not.toHaveTextContent("工具执行结果如下");
    expect(finalAnswer).not.toHaveTextContent("score=75");
  });

  it("shows a step-level HITL reason on the workflow board", async () => {
    conversationPayload.status = "active";
    conversationPayload.metadata = {
      workflow_state: "waiting_for_user",
      selected_skill: "lab4ai-auto-reproduct",
      workflow_name: "lab4ai-auto-reproduct",
      workflow_results: { repo_name: "PhotoDoodle" },
      workflow_steps: [
        {
          id: "step_3_deploy_cpu",
          name: "创建 CPU 实例",
          status: "waiting_for_user",
          output: "需要确认后才能创建 CPU 实例。",
          progress: ["Tool waiting for user: lab4ai_create_instance"],
          tool_calls: [
            {
              tool_call_id: "tool-cpu",
              name: "lab4ai_create_instance",
              status: "waiting_for_user",
            },
          ],
        },
      ],
      pending_user_input: {
        question: "是否继续创建 CPU 实例？",
        options: ["继续执行"],
        tool_name: "lab4ai_create_instance",
      },
    };

    renderChat();

    expect(await screen.findByText("等待你确认")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "复现流水线实时看板: PhotoDoodle" })).toBeInTheDocument();
    expect(screen.getAllByText("等待确认").length).toBeGreaterThan(0);
    expect(screen.getByText("需要你确认后继续。")).toBeInTheDocument();
    expect(screen.getByText("需要确认后才能创建 CPU 实例。")).toBeInTheDocument();
    expect(screen.getAllByText("创建 Lab4AI 实例").length).toBeGreaterThan(0);
    expect(screen.getAllByText("待确认").length).toBeGreaterThan(0);
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
      within(screen.getByTestId("inline-human-decision")).getByRole("button", {
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

  it("shows Lab4AI credential request inline and continues from chat confirmation", async () => {
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
    globalThis.fetch = vi.fn().mockImplementation(() => {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(conversationPayload),
      });
    });

    renderChat();

    const inlineDecision = await screen.findByTestId("inline-human-decision");
    expect(within(inlineDecision).getByText("Lab4AI 凭证未配置，请先由管理员配置平台账号。")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(
      within(inlineDecision).getByRole("button", { name: "已完成配置，继续执行" })
    );

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
