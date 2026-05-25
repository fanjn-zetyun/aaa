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
  return {
    queryClient,
    ...render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/reproduce/task/7"]}>
        <Routes>
          <Route path="/reproduce/task/:taskId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
    ),
  };
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
    expect(screen.queryByText("body")).not.toBeInTheDocument();
  });

  it("shows skill selection summary without evidence details inside the SKILL.md reproduction panel", async () => {
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
      workflow_current_step_id: "step_1_audit",
      workflow_results: { repo_name: "motion-guided-flow" },
      workflow_steps: [
        {
          id: "step_1_audit",
          name: "项目与论文双重审计",
          status: "running",
          progress: ["Start step: 项目与论文双重审计"],
        },
      ],
    };

    renderChat();

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(within(panel).getByText("模型选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
    expect(
      within(panel).getByText("已加载 skills/lab4ai-auto-reproduct/project_reproduce.yaml")
    ).toBeInTheDocument();
    expect(within(panel).queryByText("查看选择证据")).not.toBeInTheDocument();
    expect(within(panel).getByTestId("reproduction-step-row-step_1_audit")).toBeInTheDocument();
  });

  it("attaches metadata skill evidence to a new agent bubble after the latest user", async () => {
    conversationPayload.metadata = {
      skill_selection: {
        selected_skill: "lab4ai-auto-reproduct",
        source: "model",
        model_choice: "lab4ai-auto-reproduct",
        fallback_choice: null,
        reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
        confidence: null,
        error: null,
      },
    };
    conversationPayload.messages = [
      {
        id: 1,
        role: "user",
        content: "previous user request",
        message_metadata: {},
        created_at: "2026-05-20T00:00:00Z",
      },
      {
        id: 2,
        role: "assistant",
        content: "previous assistant answer",
        message_metadata: {},
        created_at: "2026-05-20T00:00:10Z",
      },
      {
        id: 3,
        role: "user",
        content: "current user starts new run",
        message_metadata: {},
        created_at: "2026-05-20T00:01:00Z",
      },
    ];

    renderChat();

    const currentUser = await screen.findByText("current user starts new run");
    const skillHeading = await screen.findByText("模型选择了 lab4ai-auto-reproduct");

    expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(2);
    expect(currentUser.compareDocumentPosition(skillHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("reuses metadata-created agent bubble when stream starts for the current run", async () => {
    conversationPayload.metadata = {
      skill_selection: {
        selected_skill: "lab4ai-auto-reproduct",
        source: "model",
        model_choice: "lab4ai-auto-reproduct",
        fallback_choice: null,
        reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
        confidence: null,
        error: null,
      },
    };
    conversationPayload.messages = [
      {
        id: 1,
        role: "user",
        content: "previous user request",
        message_metadata: {},
        created_at: "2026-05-20T00:00:00Z",
      },
      {
        id: 2,
        role: "assistant",
        content: "previous assistant answer",
        message_metadata: {},
        created_at: "2026-05-20T00:00:10Z",
      },
      {
        id: 3,
        role: "user",
        content: "current user starts new run",
        message_metadata: {},
        created_at: "2026-05-20T00:01:00Z",
      },
    ];

    renderChat();

    expect(await screen.findByText("模型选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "assistant_started",
        run_id: "run-current",
        timestamp: "2026-05-20T00:01:01Z",
      });
      ws.emit({
        seq: 2,
        type: "assistant_delta",
        run_id: "run-current",
        delta: "streamed assistant content",
      });
    });

    const skillHeading = screen.getByText("模型选择了 lab4ai-auto-reproduct");
    const agentBubble = skillHeading.closest('[data-testid="agent-message"]');
    expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(2);
    expect(agentBubble).toHaveTextContent("模型选择了 lab4ai-auto-reproduct");
    expect(agentBubble).toHaveTextContent("streamed assistant content");
  });

  it("merges streamed skill selection evidence into the active agent bubble", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "assistant_started",
        run_id: "run-skill",
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "progress",
        run_id: "run-skill",
        stage: "skill_selection",
        content: "Model selected registered skill `lab4ai-auto-reproduct`.",
        skill_selection: {
          selected_skill: "lab4ai-auto-reproduct",
          source: "model",
          model_choice: "lab4ai-auto-reproduct",
          fallback_choice: null,
          reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
          confidence: null,
          error: null,
        },
        workflow_path: "skills/lab4ai-auto-reproduct/project_reproduce.yaml",
        timestamp: "2026-05-20T00:00:02Z",
      });
    });

    expect(await screen.findByText("模型选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
    expect(
      screen.getByText("已加载 skills/lab4ai-auto-reproduct/project_reproduce.yaml")
    ).toBeInTheDocument();
    expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(1);
  });

  it("merges refetched metadata run state into the current streamed agent bubble", async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...conversationPayload,
            metadata: { ...conversationPayload.metadata },
            messages: conversationPayload.messages.map((message) => ({ ...message })),
          }),
      } as Response)
    );
    const { queryClient } = renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "assistant_started",
        run_id: "run-refetch-skill",
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "assistant_delta",
        run_id: "run-refetch-skill",
        delta: "streamed active content",
        skill_selection: {
          selected_skill: "lab4ai-auto-reproduct",
          source: "model",
          model_choice: "lab4ai-auto-reproduct",
          fallback_choice: null,
          reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
          confidence: null,
          error: null,
        },
        workflow_path: "skills/lab4ai-auto-reproduct/project_reproduce.yaml",
      });
    });

    expect(await screen.findByText("streamed active content")).toBeInTheDocument();
    expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(1);

    conversationPayload.updated_at = "2026-05-20T00:00:10Z";
    conversationPayload.metadata = {
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
    await act(async () => {
      const refetchedConversation = {
        ...conversationPayload,
        metadata: { ...conversationPayload.metadata },
        messages: conversationPayload.messages.map((message) => ({ ...message })),
      };
      queryClient.setQueryData(["conversation", "7"], refetchedConversation);
      queryClient.setQueryData(["conversation", 7], refetchedConversation);
      await Promise.resolve();
    });

    const content = screen.getByText("streamed active content");
    const agentBubble = content.closest('[data-testid="agent-message"]');
    await waitFor(() => {
      expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(1);
    });
    expect(agentBubble).toHaveTextContent("lab4ai-auto-reproduct");
    expect(agentBubble).toHaveTextContent("skills/lab4ai-auto-reproduct/project_reproduce.yaml");
  });

  it("merges refreshed metadata fields into existing streamed run state", async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...conversationPayload,
            metadata: { ...conversationPayload.metadata },
            messages: conversationPayload.messages.map((message) => ({ ...message })),
          }),
      } as Response)
    );
    const { queryClient } = renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "assistant_started",
        run_id: "run-refresh-fields",
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "assistant_delta",
        run_id: "run-refresh-fields",
        delta: "streamed partial content",
        skill_selection: {
          selected_skill: "lab4ai-auto-reproduct",
        },
      });
      ws.emit({
        seq: 3,
        type: "workflow_loaded",
        run_id: "run-refresh-fields",
        workflow: {
          name: "Lab4AI_Auto_Reproduction_Pipeline",
          steps: [],
        },
        timestamp: "2026-05-20T00:00:02Z",
      });
    });

    expect(await screen.findByText("streamed partial content")).toBeInTheDocument();

    conversationPayload.updated_at = "2026-05-20T00:00:10Z";
    conversationPayload.metadata = {
      skill_selection: {
        selected_skill: "lab4ai-auto-reproduct",
        source: "model",
        model_choice: "lab4ai-auto-reproduct",
        fallback_choice: null,
        reason: "Refetched metadata supplied the complete skill selection evidence.",
        confidence: null,
        error: null,
      },
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_current_step_id: "metadata_step",
      workflow_steps: [
        {
          id: "metadata_step",
          name: "metadata step marker",
          status: "running",
          progress: ["metadata progress marker"],
        },
      ],
    };

    await act(async () => {
      const refetchedConversation = {
        ...conversationPayload,
        metadata: { ...conversationPayload.metadata },
        messages: conversationPayload.messages.map((message) => ({ ...message })),
      };
      queryClient.setQueryData(["conversation", "7"], refetchedConversation);
      await Promise.resolve();
    });

    const content = screen.getByText("streamed partial content");
    const agentBubble = content.closest('[data-testid="agent-message"]');
    expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(1);
    await waitFor(() => {
      expect(agentBubble).toHaveTextContent("模型选择了 lab4ai-auto-reproduct");
      expect(agentBubble).toHaveTextContent("复现流水线实时看板: PhotoDoodle");
    });

    expect(within(agentBubble as HTMLElement).queryByText("查看选择证据")).not.toBeInTheDocument();
    expect(within(agentBubble as HTMLElement).queryByText("model_choice")).not.toBeInTheDocument();
  });

  it("merges refetched metadata run state into a completed streamed agent bubble", async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...conversationPayload,
            metadata: { ...conversationPayload.metadata },
            messages: conversationPayload.messages.map((message) => ({ ...message })),
          }),
      } as Response)
    );
    const { queryClient } = renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "assistant_started",
        run_id: "run-completed-metadata",
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "assistant_delta",
        run_id: "run-completed-metadata",
        delta: "completed stream answer",
      });
      ws.emit({
        seq: 3,
        type: "assistant_completed",
        run_id: "run-completed-metadata",
        message: {
          id: 2,
          role: "assistant",
          content: "completed stream answer",
          message_metadata: {},
          created_at: "2026-05-20T00:00:03Z",
        },
      });
    });

    expect(await screen.findByText("completed stream answer")).toBeInTheDocument();
    expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(1);

    conversationPayload.updated_at = "2026-05-20T00:00:10Z";
    conversationPayload.metadata = {
      skill_selection: {
        selected_skill: "lab4ai-auto-reproduct",
        source: "model",
        model_choice: "lab4ai-auto-reproduct",
        fallback_choice: null,
        reason: "Completed run metadata selected the reproduction skill.",
        confidence: null,
        error: null,
      },
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_steps: [
        {
          id: "completed_metadata_step",
          name: "completed metadata step marker",
          status: "completed",
        },
      ],
    };

    await act(async () => {
      const refetchedConversation = {
        ...conversationPayload,
        metadata: { ...conversationPayload.metadata },
        messages: conversationPayload.messages.map((message) => ({ ...message })),
      };
      queryClient.setQueryData(["conversation", "7"], refetchedConversation);
      await Promise.resolve();
    });

    const answer = screen.getByText("completed stream answer");
    const agentBubble = answer.closest('[data-testid="agent-message"]');
    await waitFor(() => {
      expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(1);
      expect(agentBubble).toHaveTextContent("模型选择了 lab4ai-auto-reproduct");
      expect(agentBubble).toHaveTextContent("复现流水线实时看板: PhotoDoodle");
    });
  });

  it("merges top-level skill selection source into streamed selection object", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "progress",
        run_id: "run-fallback-source",
        stage: "skill_selection",
        content: "Fallback selected registered skill `lab4ai-auto-reproduct`.",
        skill_selection_source: "fallback",
        skill_selection: {
          selected_skill: "lab4ai-auto-reproduct",
        },
        timestamp: "2026-05-20T00:00:01Z",
      });
    });

    expect(await screen.findByText("规则兜底选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
    expect(screen.getByText("规则兜底")).toBeInTheDocument();
  });

  it("merges skill evidence from assistant delta into the active agent bubble", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "assistant_started",
        run_id: "run-delta-skill",
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "assistant_delta",
        run_id: "run-delta-skill",
        delta: "delta content with skill",
        skill_selection: {
          selected_skill: "lab4ai-auto-reproduct",
          source: "model",
          model_choice: "lab4ai-auto-reproduct",
          fallback_choice: null,
          reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
          confidence: null,
          error: null,
        },
        workflow_path: "runtime/workflows/run-delta-skill/project_reproduce.yaml",
      });
    });

    expect(await screen.findByText("模型选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
    expect(screen.getByText("已加载 runtime/workflows/run-delta-skill/project_reproduce.yaml")).toBeInTheDocument();
    expect(screen.getByText("delta content with skill")).toBeInTheDocument();
    expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(1);
  });

  it("merges skill evidence from assistant delta without text into the active agent bubble", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "assistant_started",
        run_id: "run-delta-state-only",
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "assistant_delta",
        run_id: "run-delta-state-only",
        skill_selection_source: "model",
        skill_selection: {
          selected_skill: "lab4ai-auto-reproduct",
          model_choice: "lab4ai-auto-reproduct",
          fallback_choice: null,
          reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
          confidence: null,
          error: null,
        },
        workflow_path: "skills/lab4ai-auto-reproduct/project_reproduce.yaml",
      });
    });

    expect(await screen.findByText("模型选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
    expect(screen.getByText("已加载 skills/lab4ai-auto-reproduct/project_reproduce.yaml")).toBeInTheDocument();
    expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(1);
  });

  it("updates inferred workflow path when a later stream payload includes explicit workflow path", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "progress",
        run_id: "run-path",
        stage: "skill_selection",
        content: "Model selected registered skill `lab4ai-auto-reproduct`.",
        skill_selection: {
          selected_skill: "lab4ai-auto-reproduct",
          source: "model",
          model_choice: "lab4ai-auto-reproduct",
          fallback_choice: null,
          reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
          confidence: null,
          error: null,
        },
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "workflow_loaded",
        run_id: "run-path",
        workflow_path: "runtime/workflows/run-path/project_reproduce.yaml",
        workflow: {
          name: "Lab4AI_Auto_Reproduction_Pipeline",
          steps: [],
        },
        timestamp: "2026-05-20T00:00:02Z",
      });
    });

    expect(
      await screen.findByText("已加载 runtime/workflows/run-path/project_reproduce.yaml")
    ).toBeInTheDocument();
    expect(
      screen.queryByText("已加载 skills/lab4ai-auto-reproduct/project_reproduce.yaml")
    ).not.toBeInTheDocument();
  });

  it("uses a neutral label for unknown skill selection source", async () => {
    conversationPayload.metadata = {
      skill_selection: {
        selected_skill: "lab4ai-auto-reproduct",
        source: "runtime",
        model_choice: null,
        fallback_choice: null,
        reason: "Runtime provided the selected skill.",
        confidence: null,
        error: null,
      },
    };

    renderChat();

    expect(await screen.findByText("已选择 lab4ai-auto-reproduct")).toBeInTheDocument();
    expect(screen.getByText("已选择")).toBeInTheDocument();
    expect(screen.queryByText("规则兜底")).not.toBeInTheDocument();
  });

  it("does not render skill selection card for empty streamed selection payload", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "progress",
        run_id: "run-empty-skill",
        stage: "skill_selection",
        content: "Skill selection not available yet.",
        skill_selection: {},
        timestamp: "2026-05-20T00:00:01Z",
      });
    });

    expect(await screen.findByText("AutoResearch24 Agent")).toBeInTheDocument();
    expect(screen.queryByText("Skill Selection")).not.toBeInTheDocument();
    expect(screen.queryByText("未选择")).not.toBeInTheDocument();
  });

  it("does not render skill selection card for source-only streamed payload", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "progress",
        run_id: "run-source-only",
        stage: "skill_selection",
        content: "Model selection started.",
        skill_selection_source: "model",
        timestamp: "2026-05-20T00:00:01Z",
      });
    });

    expect(await screen.findByText("AutoResearch24 Agent")).toBeInTheDocument();
    expect(screen.queryByText("Skill Selection")).not.toBeInTheDocument();
    expect(screen.queryByText("未选择")).not.toBeInTheDocument();
  });

  it("renders skill selection and workflow updates without a noisy process timeline", async () => {
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
        content: "Model selected registered skill `lab4ai-auto-reproduct`.",
        skill_selection_source: "model",
        skill_selection: {
          selected_skill: "lab4ai-auto-reproduct",
          source: "model",
          model_choice: "lab4ai-auto-reproduct",
          fallback_choice: null,
          reason: "Model selected registered skill `lab4ai-auto-reproduct`.",
          confidence: null,
          error: null,
        },
        workflow_path: "skills/lab4ai-auto-reproduct/project_reproduce.yaml",
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "workflow_loaded",
        run_id: "run-1",
        workflow_path: "skills/lab4ai-auto-reproduct/project_reproduce.yaml",
        workflow: {
          name: "Lab4AI_Auto_Reproduction_Pipeline",
          project_name: "PhotoDoodle",
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
        type: "workflow_step_completed",
        run_id: "run-1",
        workflow_step_id: "step_1_audit",
        step: {
          id: "step_1_audit",
          name: "项目与论文双重审计",
          status: "completed",
          output: "score=75；已完成项目与论文审计的 MVP 记录。",
          progress: ["Invoking tool: analyze_repo", "Tool completed: analyze_repo"],
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
        seq: 5,
        type: "assistant_started",
        run_id: "run-1",
        timestamp: "2026-05-20T00:00:04Z",
      });
      ws.emit({
        seq: 6,
        type: "assistant_delta",
        run_id: "run-1",
        delta: "工具执行结果如下\n| 序号 | 执行步骤 | 当前状态 | 核心产出 / 详情 |\n| --- | --- | --- | --- |\n| 1 | `step_1_audit`: 项目与论文双重审计 | ✅ 完成 | score=75 |\n最终结论：仓库审计已完成，下一步需要创建 CPU 实例。",
      });
    });

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(
      within(panel).getByRole("heading", { name: "复现流水线实时看板: PhotoDoodle" })
    ).toBeInTheDocument();
    expect(
      within(panel).getByRole("columnheader", { name: "执行步骤 (对应 YAML Task)" })
    ).toBeInTheDocument();
    expect(within(panel).getAllByTestId(/^reproduction-step-row-/)).toHaveLength(9);
    expect(screen.queryByText("Research Reproduction Workbench")).not.toBeInTheDocument();
    expect(screen.getByText("1/9 完成")).toBeInTheDocument();
    expect(screen.getAllByText(/项目与论文双重审计/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("[完成]").length).toBeGreaterThan(0);
    expect(within(panel).getByText(/可行性评分：75/)).toBeInTheDocument();
    expect(
      within(panel).queryByText("score=75；已完成项目与论文审计的 MVP 记录。")
    ).not.toBeInTheDocument();
    expect(screen.queryByText("工作流已加载")).not.toBeInTheDocument();
    expect(screen.queryByText("选择复现流程")).not.toBeInTheDocument();
    expect(screen.getByText("最终结论：仓库审计已完成，下一步需要创建 CPU 实例。")).toBeInTheDocument();

    const finalAnswer = screen.getByText("最终回答").parentElement;
    expect(finalAnswer).toHaveTextContent("最终结论：仓库审计已完成，下一步需要创建 CPU 实例。");
    expect(finalAnswer).not.toHaveTextContent("工具执行结果如下");
    expect(finalAnswer).not.toHaveTextContent("score=75");
  });

  it("keeps intermediate workflow logs out of the final answer card", async () => {
    conversationPayload.messages = [
      ...conversationPayload.messages,
      {
        id: 2,
        role: "assistant",
        content:
          "工具执行结果如下\n| 序号 | 执行步骤 | 当前状态 | 核心产出 / 详情 |\n| --- | --- | --- | --- |\n| 1 | `step_1_audit` | 完成 | score=82 |\n\n最终结论：复现报告已生成。",
        message_metadata: {},
        created_at: "2026-05-20T00:00:30Z",
      },
    ];
    conversationPayload.metadata = {
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_results: { repo_name: "motion-guided-flow" },
      workflow_steps: [
        {
          id: "step_1_audit",
          name: "项目复现可行性分析",
          status: "completed",
          output: "score=82",
        },
      ],
    };

    renderChat();

    const finalAnswer = await screen.findByText("最终回答");
    const card = finalAnswer.parentElement;
    expect(card).toHaveTextContent("最终结论：复现报告已生成。");
    expect(card).not.toHaveTextContent("工具执行结果如下");
    expect(card).not.toHaveTextContent("| 序号 |");
  });

  it("renders workflow completion as the SKILL.md final delivery section", async () => {
    conversationPayload.messages = [
      ...conversationPayload.messages,
      {
        id: 2,
        role: "assistant",
        content:
          "## 结项报告\n\n复现 workflow 已按 project_reproduce.yaml 完成全部 9 个步骤。\n\n交付物：\n- Word 报告：runtime/workspaces/7/repro_report.docx\n\n资源状态：\n- GPU 实例已释放：gpu-1",
        message_metadata: { workflow_final_report: true },
        created_at: "2026-05-20T00:00:30Z",
      },
    ];
    conversationPayload.metadata = {
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_results: {
        repo_name: "motion-guided-flow",
        word_report_path: "runtime/workspaces/7/repro_report.docx",
      },
      workflow_steps: [
        { id: "step_1_audit", name: "项目复现可行性分析", status: "completed" },
        { id: "step_8_generate_report", name: "生成工业级报告", status: "completed" },
        { id: "step_9_release_gpu", name: "释放 GPU 实例", status: "completed" },
      ],
    };

    renderChat();

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(within(panel).getByText("任务完成：motion-guided-flow 自动化复现已结项")).toBeInTheDocument();
    expect(within(panel).getByText("核心指标对比 (Smoke Test 实测)")).toBeInTheDocument();
    expect(within(panel).getByText("runtime/workspaces/7/repro_report.docx")).toBeInTheDocument();
    expect(within(panel).getByText("资源监控核对")).toBeInTheDocument();
    expect(screen.queryByText("结项报告")).not.toBeInTheDocument();
    expect(screen.queryByText("最终回答")).not.toBeInTheDocument();
  });

  it("does not append execution process after workflow final report completion", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.emit({
        seq: 1,
        type: "workflow_loaded",
        run_id: "run-final",
        workflow: {
          name: "Lab4AI_Auto_Reproduction_Pipeline",
          project_name: "PhotoDoodle",
          current_step_id: "step_8_generate_report",
          results: { word_report_path: "runtime/workspaces/7/PhotoDoodle_Final_Repro_Report.docx" },
          steps: [
            { id: "step_1_audit", name: "项目与论文双重审计", status: "completed" },
            { id: "step_8_generate_report", name: "生成工业级报告", status: "completed" },
          ],
        },
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "tool_completed",
        run_id: "run-final",
        tool_name: "repro_report",
        tool_call_id: "tool-report",
        ok: true,
        timestamp: "2026-05-20T00:00:02Z",
      });
      ws.emit({
        seq: 3,
        type: "assistant_completed",
        run_id: "run-final",
        message: {
          id: 2,
          conversation_id: 7,
          role: "assistant",
          content:
            "## 结项报告\n\n复现 workflow 已按 project_reproduce.yaml 完成全部 9 个步骤。\n\n交付物：\n- Word 报告：runtime/workspaces/7/PhotoDoodle_Final_Repro_Report.docx",
          message_metadata: { workflow_final_report: true },
          created_at: "2026-05-20T00:00:03Z",
        },
      });
      ws.emit({
        seq: 4,
        type: "runtime_completed",
        run_id: "run-final",
        timestamp: "2026-05-20T00:00:04Z",
      });
    });

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(within(panel).getByText("任务完成：PhotoDoodle 自动化复现已结项")).toBeInTheDocument();
    expect(screen.queryByText("执行过程")).not.toBeInTheDocument();
    expect(screen.queryByText("结项报告")).not.toBeInTheDocument();
    expect(screen.queryByText("最终回答")).not.toBeInTheDocument();
  });

  it("hides the final answer card when the completed reproduction panel already has final delivery", async () => {
    conversationPayload.messages = [
      ...conversationPayload.messages,
      {
        id: 2,
        role: "assistant",
        content: "最终结论：PhotoDoodle 自动化复现已完成，报告已生成。",
        message_metadata: {},
        created_at: "2026-05-20T00:00:30Z",
      },
    ];
    conversationPayload.status = "completed";
    conversationPayload.metadata = {
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_results: {
        repo_name: "PhotoDoodle",
        word_report_path: "runtime/workspaces/7/PhotoDoodle_Final_Repro_Report.docx",
      },
      workflow_steps: [
        { id: "step_1_audit", name: "项目与论文双重审计", status: "completed" },
        { id: "step_2_condition_check", name: "复现可行性熔断判断", status: "completed" },
        { id: "step_3_deploy_cpu", name: "创建 CPU 实例", status: "completed" },
        { id: "step_4_cpu_env_setup", name: "SSH探活 + 克隆代码 + 智能环境构建", status: "completed" },
        { id: "step_5_release_cpu", name: "释放 CPU 实例", status: "completed" },
        { id: "step_6_deploy_gpu", name: "创建 GPU 实例", status: "completed" },
        { id: "step_7_gpu_execution", name: "CUDA编译 + 推理/微调测试", status: "completed" },
        { id: "step_8_generate_report", name: "生成工业级报告", status: "completed" },
        { id: "step_9_release_gpu", name: "释放 GPU 实例", status: "completed" },
      ],
    };

    renderChat();

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(within(panel).getByText("任务完成：PhotoDoodle 自动化复现已结项")).toBeInTheDocument();
    expect(screen.queryByText("最终回答")).not.toBeInTheDocument();
    expect(screen.queryByText("最终结论：PhotoDoodle 自动化复现已完成，报告已生成。")).not.toBeInTheDocument();
  });

  it("preserves tool and cleanup timeline events", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "tool_started",
        run_id: "run-tool-timeline",
        tool_name: "analyze_repo",
        tool_input: {
          tool_call_id: "tool-repo-start",
          github_url: "https://github.com/showlab/PhotoDoodle",
        },
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "tool_completed",
        run_id: "run-tool-timeline",
        tool_name: "repro_report",
        ok: true,
        message: {
          id: 2,
          role: "tool",
          content: "复现报告草稿已生成。",
          message_metadata: { tool_name: "repro_report", ok: true },
          created_at: "2026-05-20T00:00:02Z",
        },
      });
      ws.emit({
        seq: 3,
        type: "tool_error",
        run_id: "run-tool-timeline",
        tool_name: "ssh_execute",
        error: "SSH 连接超时，请检查实例网络。",
        timestamp: "2026-05-20T00:00:03Z",
      });
      ws.emit({
        seq: 4,
        type: "workflow_cleanup_started",
        run_id: "run-tool-timeline",
        content: "正在释放遗留 CPU 实例。",
        timestamp: "2026-05-20T00:00:04Z",
      });
      ws.emit({
        seq: 5,
        type: "workflow_cleanup_completed",
        run_id: "run-tool-timeline",
        content: "未发现需要继续释放的实例。",
        timestamp: "2026-05-20T00:00:05Z",
      });
    });

    expect(await screen.findByText("执行过程")).toBeInTheDocument();
    expect(screen.getByText("分析 GitHub 仓库")).toBeInTheDocument();
    expect(screen.getByText("https://github.com/showlab/PhotoDoodle")).toBeInTheDocument();
    expect(screen.getByText("复现报告草稿已生成。")).toBeInTheDocument();
    expect(screen.getByText("SSH 连接超时，请检查实例网络。")).toBeInTheDocument();
    expect(screen.getByText("资源兜底释放")).toBeInTheDocument();
    expect(screen.getByText("正在释放遗留 CPU 实例。")).toBeInTheDocument();
    expect(screen.getByText("资源释放检查完成")).toBeInTheDocument();
    expect(screen.getByText("未发现需要继续释放的实例。")).toBeInTheDocument();
  });

  it("renders runtime tool activity events in the current agent bubble", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.emit({
        seq: 1,
        type: "runtime_started",
        run_id: "runtime-1",
      });
      ws.emit({
        seq: 2,
        type: "tool_started",
        run_id: "runtime-1",
        tool_name: "ask_user",
        tool_call_id: "toolu_1",
      });
      ws.emit({
        seq: 3,
        type: "tool_completed",
        run_id: "runtime-1",
        tool_name: "ask_user",
        tool_call_id: "toolu_1",
        ok: true,
      });
      ws.emit({
        seq: 4,
        type: "runtime_completed",
        run_id: "runtime-1",
      });
    });

    expect(await screen.findByText(/ask_user/)).toBeInTheDocument();
    expect(screen.getByText(/runtime-1/)).toBeInTheDocument();
  });

  it("embeds normal human confirmation in the current workflow step", async () => {
    conversationPayload.status = "active";
    conversationPayload.metadata = {
      workflow_state: "waiting_for_user",
      workflow_current_step_id: "step_3_deploy_cpu",
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
        options: ["继续执行", "修改方案"],
        tool_name: "lab4ai_create_instance",
        workflow_step_id: "step_3_deploy_cpu",
      },
    };

    renderChat();

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(within(panel).getByText("实验确认点")).toBeInTheDocument();
    expect(within(panel).getByText("需要你确认后继续执行受控动作")).toBeInTheDocument();
    expect(within(panel).getByText("是否继续创建 CPU 实例？")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "继续执行" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "修改方案" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("inline-human-decision")).not.toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("button", { name: "继续执行" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/conversations/7/messages",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ content: "继续执行" }),
        })
      );
    });
  });

  it("renders reproduce workflow metadata as the SKILL.md nine-step agent panel", async () => {
    conversationPayload.metadata = {
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_current_step_id: "step_4_cpu_env_setup",
      workflow_results: {
        repo_name: "motion-guided-flow",
        score: 83,
        baseline_metrics: {
          PSNR: "28.4",
          SSIM: "0.91",
        },
        hyperparams: {
          lr: "1e-4",
          batch_size: 4,
        },
      },
      workflow_resources: {
        cpu: {
          server_id: "cpu-123",
          raw: {
            ssh_host: "10.0.0.12",
            ssh_port: 22022,
            ssh_user: "root",
          },
        },
      },
      workflow_steps: [
        {
          id: "step_1_audit",
          name: "Repository and paper audit",
          status: "completed",
          output: "Audit completed: repo structure and baseline notes captured.",
        },
        {
          id: "step_3_deploy_cpu",
          name: "CPU deployment",
          status: "completed",
          evidence: {
            cpu_instance_created: true,
            server_id: "cpu-123",
          },
        },
        {
          id: "step_4_cpu_env_setup",
          name: "CPU environment setup",
          status: "running",
          output: "Preparing CPU workspace for motion-guided-flow.",
          artifacts: ["remote:/workspace/user-data/codelab/motion-guided-flow"],
          evidence: {
            clone_completed: true,
            dependency_install_attempted: true,
            project_prep_completed: true,
            remote_workspace_verified: true,
          },
          progress: [
            "Start step: CPU environment setup",
            "Invoking tool: ssh_execute",
            "Installing dependencies on CPU instance.",
            "Tool completed: lab4ai_project_prep",
          ],
          tool_calls: [
            {
              tool_call_id: "tool-ssh",
              name: "ssh_execute",
              status: "completed",
              ok: true,
            },
            {
              tool_call_id: "tool-prep",
              name: "lab4ai_project_prep",
              status: "running",
            },
          ],
        },
      ],
    };

    renderChat();

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(
      within(panel).getByRole("heading", { name: "复现流水线实时看板: motion-guided-flow" })
    ).toBeInTheDocument();
    expect(within(panel).getAllByTestId(/^reproduction-step-row-/)).toHaveLength(9);
    expect(within(panel).getByRole("columnheader", { name: "序号" })).toBeInTheDocument();
    expect(
      within(panel).getByRole("columnheader", { name: "执行步骤 (对应 YAML Task)" })
    ).toBeInTheDocument();
    expect(within(panel).getByRole("columnheader", { name: "当前状态" })).toBeInTheDocument();
    expect(
      within(panel).getByRole("columnheader", { name: "核心产出 / 详情" })
    ).toBeInTheDocument();
    expect(within(panel).getByText("2/9 完成")).toBeInTheDocument();
    expect(within(panel).getByText("step_1_audit")).toBeInTheDocument();
    expect(within(panel).getAllByText("[完成]").length).toBeGreaterThan(0);
    expect(within(panel).getByText(/可行性评分：83/)).toBeInTheDocument();
    expect(within(panel).getByText(/论文 Baseline：PSNR=28.4, SSIM=0.91/)).toBeInTheDocument();
    expect(within(panel).getByText(/超参数：lr=1e-4, batch_size=4/)).toBeInTheDocument();
    expect(within(panel).queryByText("[可行性评分 / 论文 Baseline / 超参数]")).not.toBeInTheDocument();
    const cpuDeployRow = within(panel).getByTestId("reproduction-step-row-step_3_deploy_cpu");
    expect(within(cpuDeployRow).getByText(/serverId：cpu-123/)).toBeInTheDocument();
    expect(within(cpuDeployRow).getByText(/SSH：root@10.0.0.12:22022/)).toBeInTheDocument();
    expect(within(panel).getByText("step_4_cpu_env_setup")).toBeInTheDocument();
    expect(within(panel).getByText("[执行中]")).toBeInTheDocument();
    expect(within(panel).getByText(/clone完成：是/)).toBeInTheDocument();
    expect(within(panel).getByText(/依赖安装结果：已完成/)).toBeInTheDocument();
    expect(within(panel).getByText(/workspace：remote:\/workspace\/user-data\/codelab\/motion-guided-flow/)).toBeInTheDocument();
    expect(within(panel).queryByText("[clone完成 / 依赖安装结果]")).not.toBeInTheDocument();
    expect(within(panel).getAllByText("[等待中...]").length).toBeGreaterThan(0);
    expect(screen.queryByText("Research Reproduction Workbench")).not.toBeInTheDocument();
  });

  it("renders the reproduction panel without a horizontal scrollbar inside the agent bubble", async () => {
    conversationPayload.metadata = {
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_results: { repo_name: "motion-guided-flow" },
      workflow_steps: [
        {
          id: "step_4_cpu_env_setup",
          name: "CPU environment setup",
          status: "running",
          artifacts: ["remote:/workspace/user-data/codelab/motion-guided-flow"],
          evidence: {
            clone_completed: true,
            dependency_install_attempted: true,
          },
        },
      ],
    };

    renderChat();

    const panel = await screen.findByTestId("reproduction-agent-panel");
    const table = within(panel).getByRole("table");
    expect(panel.querySelector(".overflow-x-auto")).not.toBeInTheDocument();
    expect(table.className).not.toContain("min-w-[860px]");
    expect(table.className).toContain("table-fixed");
    expect(within(panel).getByTestId("reproduction-step-row-step_4_cpu_env_setup")).toHaveTextContent(
      "remote:/workspace/user-data/codelab/motion-guided-flow"
    );
  });

  it("maps reproduce workflow statuses to the SKILL.md status labels", async () => {
    conversationPayload.metadata = {
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_results: { repo_name: "PhotoDoodle" },
      workflow_steps: [
        { id: "step_1_audit", name: "项目与论文双重审计", status: "completed" },
        { id: "step_2_condition_check", name: "复现可行性熔断判断", status: "failed", error: "score < 60" },
        { id: "step_3_deploy_cpu", name: "创建 CPU 实例", status: "running" },
      ],
    };

    renderChat();

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(within(panel).getByTestId("reproduction-status-completed")).toHaveTextContent("[完成]");
    expect(within(panel).getByTestId("reproduction-status-running")).toHaveTextContent("[执行中]");
    expect(within(panel).getByTestId("reproduction-status-failed")).toHaveTextContent("[中止]");
    expect(within(panel).getAllByTestId("reproduction-status-pending").length).toBeGreaterThan(0);
    expect(within(panel).getAllByText("[等待中...]").length).toBeGreaterThan(0);
  });

  it("renders the SKILL.md final delivery section from completed workflow metadata", async () => {
    conversationPayload.status = "completed";
    conversationPayload.metadata = {
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_results: {
        repo_name: "PhotoDoodle",
        baseline_metrics: {
          PSNR: "28.4",
          SSIM: "0.91",
        },
        smoke_test_metrics: {
          PSNR: "27.9",
          SSIM: "0.89",
          VRAM: "18.2GB",
        },
        word_report_path: "runtime/workspaces/7/PhotoDoodle_Final_Repro_Report.docx",
      },
      workflow_resources: {
        cpu: { server_id: "cpu-final", released: true },
        gpu: { server_id: "gpu-final", released: true },
      },
      workflow_steps: [
        { id: "step_1_audit", name: "项目与论文双重审计", status: "completed" },
        { id: "step_2_condition_check", name: "复现可行性熔断判断", status: "completed" },
        { id: "step_3_deploy_cpu", name: "创建 CPU 实例", status: "completed" },
        { id: "step_4_cpu_env_setup", name: "SSH探活 + 克隆代码 + 智能环境构建", status: "completed" },
        {
          id: "step_5_release_cpu",
          name: "释放 CPU 实例",
          status: "completed",
          evidence: {
            cpu_instance_released: true,
            server_id: "cpu-final",
          },
        },
        { id: "step_6_deploy_gpu", name: "创建 GPU 实例", status: "completed" },
        {
          id: "step_7_gpu_execution",
          name: "CUDA编译 + 推理/微调测试",
          status: "completed",
          evidence: {
            smoke_test_executed: true,
            gpu_runtime_env_configured: true,
          },
        },
        {
          id: "step_8_generate_report",
          name: "生成工业级报告",
          status: "completed",
          evidence: {
            report_path: "runtime/workspaces/7/PhotoDoodle_Final_Repro_Report.docx",
          },
        },
        {
          id: "step_9_release_gpu",
          name: "释放 GPU 实例",
          status: "completed",
          evidence: {
            gpu_instance_released: true,
            server_id: "gpu-final",
          },
        },
      ],
    };

    renderChat();

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(within(panel).getByText("任务完成：PhotoDoodle 自动化复现已结项")).toBeInTheDocument();
    expect(within(panel).getByText("核心指标对比 (Smoke Test 实测)")).toBeInTheDocument();
    expect(within(panel).getByText("H100 架构优化洞察")).toBeInTheDocument();
    expect(
      within(panel).getByText("Word 报告已排版落盘，请前往该绝对路径获取：")
    ).toBeInTheDocument();
    expect(
      within(panel).getByText("runtime/workspaces/7/PhotoDoodle_Final_Repro_Report.docx")
    ).toBeInTheDocument();
    expect(within(panel).getByText("资源监控核对")).toBeInTheDocument();
    expect(within(panel).getByText("PSNR")).toBeInTheDocument();
    expect(within(panel).getByText("27.9")).toBeInTheDocument();
    expect(within(panel).getByText("显存占用 (VRAM)")).toBeInTheDocument();
    expect(within(panel).getByText("18.2GB")).toBeInTheDocument();
    expect(within(panel).getByText(/编译结果：已完成/)).toBeInTheDocument();
    expect(within(panel).getByText(/实测指标：PSNR=27.9, SSIM=0.89/)).toBeInTheDocument();
    expect(within(panel).getByText(/VRAM：18.2GB/)).toBeInTheDocument();
    expect(within(panel).getByText(/Word 文件路径：runtime\/workspaces\/7\/PhotoDoodle_Final_Repro_Report.docx/)).toBeInTheDocument();
    expect(within(panel).getAllByText(/关机确认：已释放/).length).toBeGreaterThan(0);
    expect(within(panel).getAllByText(/运行时长：待记录/).length).toBeGreaterThan(0);
  });

  it("renders model process markdown as a structured execution record", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.emit({
        seq: 1,
        type: "workflow_loaded",
        run_id: "run-structured",
        workflow: {
          name: "Lab4AI_Auto_Reproduction_Pipeline",
          project_name: "motion-guided-flow",
          current_step_id: "step_4_cpu_env_setup",
          steps: [
            {
              id: "step_4_cpu_env_setup",
              name: "在 CPU 上拉取代码与智能环境/数据构建",
              status: "running",
            },
          ],
        },
        timestamp: "2026-05-20T00:00:01Z",
      });
      ws.emit({
        seq: 2,
        type: "progress",
        run_id: "run-structured",
        stage: "plan",
        workflow_step_id: "step_4_cpu_env_setup",
        content:
          "制定执行计划：用户已确认继续，当前进入 Step 4，我将做 SSH 探活 + 克隆代码 + 读取审计报告。\n\n" +
          "--- #### 复现流水线实时看板：`motion-guided-flow`\n" +
          "| 序号 | 执行步骤（对应 YAML Task） | 当前状态 | 核心产出 / 详情 |\n" +
          "| :--- | :--- | :--- | :--- |\n" +
          "| 1 | `step_1_audit`: 项目与论文双重审计 | ✅ 完成 | score=60 |\n" +
          "| 2 | `step_2_condition_check`: 复现可行性熔断判断 | ✅ 通过 | score>=60 |\n" +
          "| 3 | `step_3_deploy_cpu`: 创建 CPU 实例 | ⏳ 执行中 | 正在申请 2 核 CPU |\n" +
          "| 4 | `step_4_cpu_env_setup`: SSH 探活 + 克隆代码 + 智能环境构建 | ⏳ 等待中 | - |\n\n" +
          "模型规划工具调用：现在开始执行 Step 4。先并行做三件事：SSH 探活 + 克隆代码 + 读取审计报告。\n" +
          "模型规划工具调用：SSH 连接成功，但代码目录已存在。清理后重新克隆，同时读取项目关键文件。",
        timestamp: "2026-05-20T00:00:02Z",
      });
    });

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(within(panel).getByRole("heading", { name: "复现流水线实时看板: motion-guided-flow" })).toBeInTheDocument();
    expect(within(panel).getByText("step_4_cpu_env_setup")).toBeInTheDocument();
    expect(within(panel).getByText("[执行中]")).toBeInTheDocument();
    expect(within(panel).getByText(/clone完成：待记录/)).toBeInTheDocument();
    expect(within(panel).getByText(/依赖安装结果：待记录/)).toBeInTheDocument();
    expect(within(panel).queryByText(/制定执行计划/)).not.toBeInTheDocument();
  });

  it("structures markdown records from step progress and execution events", async () => {
    conversationPayload.status = "running";
    conversationPayload.metadata = {
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_current_step_id: "step_7_gpu_execution",
      workflow_results: { repo_name: "PhotoDoodle" },
      workflow_steps: [
        {
          id: "step_7_gpu_execution",
          name: "CUDA 编译 + 推理/微调测试",
          status: "running",
          progress: [
            "## GPU 执行计划\n\n" +
              "模型规划工具调用：开始 GPU 复现实验，先 CUDA 编译，再运行推理测试。\n\n" +
              "| 序号 | 执行步骤（对应 YAML Task） | 当前状态 | 核心产出 / 详情 |\n" +
              "| :--- | :--- | :--- | :--- |\n" +
              "| 1 | `step_1_audit`: 项目与论文双重审计 | ✅ 完成 | score=80 |\n" +
              "| 7 | `step_7_gpu_execution`: CUDA 编译 + 推理/微调测试 | ⏳ 执行中 | 编译与推理待验证 |\n\n" +
              "- CUDA 编译\n" +
              "- 运行推理测试",
          ],
        },
      ],
    };

    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emit({
        seq: 1,
        type: "workflow_cleanup_started",
        run_id: "run-execution-markdown",
        workflow_step_id: "step_7_gpu_execution",
        content:
          "## 工具恢复记录\n\n" +
          "模型规划工具调用：推理测试失败，准备清理缓存并重新运行推理。\n\n" +
          "- 清理历史代码目录\n" +
          "- 运行推理测试",
        timestamp: "2026-05-20T00:00:03Z",
      });
    });

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(within(panel).getByRole("heading", { name: "复现流水线实时看板: PhotoDoodle" })).toBeInTheDocument();
    expect(within(panel).getByText("0/9 完成")).toBeInTheDocument();
    expect(within(panel).getByText("step_7_gpu_execution")).toBeInTheDocument();
    expect(within(panel).getByText("[执行中]")).toBeInTheDocument();
    expect(within(panel).getByText(/编译结果：待记录/)).toBeInTheDocument();
    expect(within(panel).queryByText(/GPU 执行计划/)).not.toBeInTheDocument();
  });

  it("renders Agent Runtime workflow instruction checklist from metadata", async () => {
    conversationPayload.metadata = {
      runtime: {
        active_skill: { name: "lab4ai-auto-reproduct" },
        active_workflow: {
          name: "Lab4AI_Auto_Reproduction_Pipeline",
          current_step_id: "step_7_gpu_execution",
          steps: {
            step_7_gpu_execution: {
              id: "step_7_gpu_execution",
              name: "GPU execution",
              status: "recovery",
              instruction_plan_id: "step_7_gpu_execution",
              validation_failures: ["missing instruction checklist item(s): import_precheck"],
            },
          },
        },
        instruction_plans: {
          step_7_gpu_execution: {
            step_id: "step_7_gpu_execution",
            items: [
              {
                id: "import_precheck",
                text: "Run import/CUDA environment prechecks and record the result.",
                status: "pending",
              },
              {
                id: "entrypoint_detection",
                text: "Inspect README, scripts, examples, demo, or CLI entrypoints.",
                status: "completed",
              },
            ],
          },
        },
      },
    };

    renderChat();

    const panel = await screen.findByTestId("reproduction-agent-panel");
    expect(within(panel).getByText("step_7_gpu_execution")).toBeInTheDocument();
    expect(within(panel).getByText("[执行中]")).toBeInTheDocument();
    expect(within(panel).getByText(/编译结果：待记录/)).toBeInTheDocument();
    expect(
      within(panel).queryByText("missing instruction checklist item(s): import_precheck")
    ).not.toBeInTheDocument();
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
    expect(screen.getAllByText("AutoResearch24 Agent")).toHaveLength(2);
  });

  it("saves Lab4AI credentials from the workflow step without sending secrets as chat text", async () => {
    conversationPayload.status = "active";
    conversationPayload.metadata = {
      workflow_state: "waiting_for_user",
      workflow_current_step_id: "step_3_deploy_cpu",
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_results: { repo_name: "PhotoDoodle" },
      workflow_steps: [
        {
          id: "step_3_deploy_cpu",
          name: "拉起廉价 CPU 实例",
          status: "waiting_for_user",
          output: "申请 CPU 实例前需要 Lab4AI 登录凭证。",
        },
      ],
      pending_user_input: {
        question: "Lab4AI 凭证未配置，请先由管理员配置平台账号。",
        options: ["已完成配置，继续执行", "停止任务"],
        tool_name: "lab4ai_create_instance",
        workflow_step_id: "step_3_deploy_cpu",
        intervention: {
          type: "lab4ai_credentials_required",
          title: "需要配置 Lab4AI 平台账号",
          admin_endpoint: "/api/admin/settings/lab4ai",
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

    const panel = await screen.findByTestId("reproduction-agent-panel");
    fireEvent.change(within(panel).getByLabelText("手机号/账号"), {
      target: { value: "13800008000" },
    });
    fireEvent.change(within(panel).getByLabelText("密码"), {
      target: { value: "super-secret-password" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "保存并继续" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/admin/settings/lab4ai",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ phone: "13800008000", password: "super-secret-password" }),
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

    const messageCalls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
      .filter(([path]) => path === "/api/conversations/7/messages")
      .map(([, options]) => String((options as RequestInit).body || ""));
    expect(messageCalls.join("\n")).not.toContain("super-secret-password");
    expect(await within(panel).findByText("Lab4AI 凭证已安全配置")).toBeInTheDocument();
    expect(within(panel).getByText("138****8000")).toBeInTheDocument();
    expect(within(panel).queryByLabelText("密码")).not.toBeInTheDocument();
  });

  it("uses reproduction markdown styling for reproduce assistant answers", async () => {
    conversationPayload.status = "completed";
    conversationPayload.messages.push({
      id: 2,
      role: "assistant",
      content:
        "#### 复现流水线实时看板 `PhotoDoodle`\n\n" +
        "| 序号 | 执行步骤 (对应 YAML Task) | 当前状态 | 核心产出 / 详情 |\n" +
        "| :--- | :--- | :--- | :--- |\n" +
        "| 1 | `step_1_audit`: 项目与论文双重审计 | [完成] | score=80 |",
      message_metadata: {},
      created_at: "2026-05-20T00:00:10Z",
    });

    renderChat();

    const agentMessage = await screen.findByTestId("agent-message");
    expect(within(agentMessage).getByTestId("markdown-content")).toHaveClass(
      "markdown-reproduction"
    );
    expect(within(agentMessage).getByTestId("reproduction-status-done")).toHaveTextContent(
      "[完成]"
    );
  });

  it("keeps reproduction markdown tables visible when workflow metadata is present", async () => {
    conversationPayload.status = "completed";
    conversationPayload.metadata = {
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_steps: [
        {
          id: "step_1_audit",
          name: "项目与论文双重审计",
          status: "completed",
        },
      ],
    };
    conversationPayload.messages.push({
      id: 2,
      role: "assistant",
      content:
        "#### 复现流水线实时看板 `PhotoDoodle`\n\n" +
        "| 序号 | 执行步骤 (对应 YAML Task) | 当前状态 | 核心产出 / 详情 |\n" +
        "| :--- | :--- | :--- | :--- |\n" +
        "| 1 | `step_1_audit`: 项目与论文双重审计 | [完成] | score=80 |",
      message_metadata: {},
      created_at: "2026-05-20T00:00:10Z",
    });

    renderChat();

    const agentMessage = await screen.findByTestId("agent-message");
    expect(
      within(agentMessage).getByText("复现流水线实时看板", { exact: false })
    ).toBeInTheDocument();
    expect(within(agentMessage).getAllByText("step_1_audit")).toHaveLength(1);
    expect(within(agentMessage).queryByText("Research Reproduction Workbench")).not.toBeInTheDocument();
    expect(within(agentMessage).getByTestId("reproduction-status-completed")).toHaveTextContent(
      "[完成]"
    );
  });
});
