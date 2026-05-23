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

  it("nests skill selection evidence inside the first workflow step", async () => {
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

    const step = await screen.findByTestId("workflow-step-step_1_audit");
    expect(within(step).getByText("模型选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
    expect(
      within(step).getByText("已加载 skills/lab4ai-auto-reproduct/project_reproduce.yaml")
    ).toBeInTheDocument();
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

    expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(2);
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
    expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(2);
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
    expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(1);
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
    expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(1);

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
      expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(1);
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
    expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(1);
    await waitFor(() => {
      expect(agentBubble).toHaveTextContent("模型选择了 lab4ai-auto-reproduct");
      expect(agentBubble).toHaveTextContent("metadata step marker");
    });

    fireEvent.click(within(agentBubble as HTMLElement).getByText("查看选择证据"));

    expect(within(agentBubble as HTMLElement).getByText("source")).toBeInTheDocument();
    expect(within(agentBubble as HTMLElement).getByText("model")).toBeInTheDocument();
    expect(within(agentBubble as HTMLElement).getByText("model_choice")).toBeInTheDocument();
    expect(
      within(agentBubble as HTMLElement).getAllByText(
        "Refetched metadata supplied the complete skill selection evidence."
      ).length
    ).toBeGreaterThan(0);
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
    expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(1);

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
      expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(1);
      expect(agentBubble).toHaveTextContent("模型选择了 lab4ai-auto-reproduct");
      expect(agentBubble).toHaveTextContent("completed metadata step marker");
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
    expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(1);
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
    expect(screen.getAllByText("LOBSTER Agent")).toHaveLength(1);
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

    expect(await screen.findByText("LOBSTER Agent")).toBeInTheDocument();
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

    expect(await screen.findByText("LOBSTER Agent")).toBeInTheDocument();
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

    expect(await screen.findByText("模型选择了 lab4ai-auto-reproduct")).toBeInTheDocument();
    expect(
      screen.getByText("已加载 skills/lab4ai-auto-reproduct/project_reproduce.yaml")
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "PhotoDoodle 复现流水线" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("Project Reproduction Workflow")).toBeInTheDocument();
    expect(screen.getByText("1/9 完成")).toBeInTheDocument();
    expect(screen.getAllByText(/项目与论文双重审计/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("完成").length).toBeGreaterThan(0);
    expect(screen.getAllByText("正在分析仓库。").length).toBeGreaterThan(0);
    expect(screen.getAllByText("分析仓库完成。").length).toBeGreaterThan(0);
    expect(screen.getAllByText("分析 GitHub 仓库").length).toBeGreaterThan(0);
    expect(screen.getAllByText("score=75；已完成项目与论文审计的 MVP 记录。").length).toBeGreaterThan(0);
    const workflowStep = screen.getByTestId("workflow-step-step_1_audit");
    expect(within(workflowStep).getByText("思考过程")).toBeInTheDocument();
    expect(within(workflowStep).getByText("执行过程")).toBeInTheDocument();
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
        options: ["继续执行"],
        tool_name: "lab4ai_create_instance",
        workflow_step_id: "step_3_deploy_cpu",
      },
    };

    renderChat();

    const step = await screen.findByTestId("workflow-step-step_3_deploy_cpu");
    expect(within(step).getByText("等待你确认")).toBeInTheDocument();
    expect(within(step).getByText("需要你的输入")).toBeInTheDocument();
    expect(within(step).getByText("是否继续创建 CPU 实例？")).toBeInTheDocument();
    expect(within(step).getByRole("button", { name: "继续执行" })).toBeInTheDocument();
    expect(screen.queryByTestId("inline-human-decision")).not.toBeInTheDocument();

    fireEvent.click(within(step).getByRole("button", { name: "继续执行" }));

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

  it("shows workflow steps as a vertical run card with the current step expanded", async () => {
    conversationPayload.metadata = {
      workflow_name: "Lab4AI_Auto_Reproduction_Pipeline",
      workflow_current_step_id: "step_4_cpu_env_setup",
      workflow_results: { repo_name: "motion-guided-flow" },
      workflow_steps: [
        {
          id: "step_1_audit",
          name: "Repository and paper audit",
          status: "completed",
          output: "Audit completed: repo structure and baseline notes captured.",
        },
        {
          id: "step_4_cpu_env_setup",
          name: "CPU environment setup",
          status: "running",
          output: "Preparing CPU workspace for motion-guided-flow.",
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

    expect(
      await screen.findByRole("heading", { name: "motion-guided-flow 复现流水线" })
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText("1/9 完成")).toBeInTheDocument();
    expect(screen.getByText("step_1_audit")).toBeInTheDocument();
    expect(
      screen.getByText("Audit completed: repo structure and baseline notes captured.")
    ).toBeInTheDocument();
    expect(screen.getByText("step_4_cpu_env_setup")).toBeInTheDocument();
    expect(screen.getByText("Preparing CPU workspace for motion-guided-flow.")).toBeInTheDocument();
    expect(screen.getByText("Installing dependencies on CPU instance.")).toBeInTheDocument();
    expect(screen.getByText("执行远程命令")).toBeInTheDocument();
    expect(screen.getByText("lab4ai_project_prep")).toBeInTheDocument();
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

    const step = await screen.findByTestId("workflow-step-step_3_deploy_cpu");
    fireEvent.change(within(step).getByLabelText("手机号/账号"), {
      target: { value: "13800008000" },
    });
    fireEvent.change(within(step).getByLabelText("密码"), {
      target: { value: "super-secret-password" },
    });
    fireEvent.click(within(step).getByRole("button", { name: "保存并继续" }));

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
  });
});
