import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
  beforeEach(() => {
    localStorage.setItem("access_token", "token");
    Element.prototype.scrollIntoView = vi.fn();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: 7,
          title: "PhotoDoodle",
          status: "running",
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
        }),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("renders streamed assistant deltas and tool timeline in one agent bubble", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
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
      type: "tool_started",
      run_id: "run-1",
      tool_name: "analyze_repo",
      tool_input: { github_url: "https://github.com/showlab/PhotoDoodle" },
      timestamp: "2026-05-20T00:00:02Z",
    });
    ws.emit({
      seq: 3,
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
      seq: 4,
      type: "assistant_started",
      run_id: "run-1",
      timestamp: "2026-05-20T00:00:04Z",
    });
    ws.emit({ seq: 5, type: "assistant_delta", run_id: "run-1", delta: "第一段" });
    ws.emit({ seq: 6, type: "assistant_delta", run_id: "run-1", delta: "，第二段" });

    expect(await screen.findByText("执行过程")).toBeInTheDocument();
    expect(screen.getByText("选择 skill")).toBeInTheDocument();
    expect(screen.getByText("analyze_repo")).toBeInTheDocument();
    expect(screen.getByText("已识别仓库 showlab/PhotoDoodle。")).toBeInTheDocument();
    expect(screen.getByText("第一段，第二段")).toBeInTheDocument();
  });

  it("ignores replayed websocket events by seq", async () => {
    renderChat();

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1);
    });
    const ws = MockWebSocket.instances[0];
    ws.emit({ seq: 1, type: "assistant_started", run_id: "run-1" });
    ws.emit({ seq: 2, type: "assistant_delta", run_id: "run-1", delta: "只出现一次" });
    ws.emit({ seq: 2, type: "assistant_delta", run_id: "run-1", delta: "重复内容" });

    expect(await screen.findByText("只出现一次")).toBeInTheDocument();
    expect(screen.queryByText("只出现一次重复内容")).not.toBeInTheDocument();
  });
});
