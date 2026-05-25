import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import RightPanel from "../components/RightPanel";

function renderRightPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/reproduce/task/7"]}>
        <Routes>
          <Route path="/reproduce/task/:taskId" element={<RightPanel />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("RightPanel", () => {
  beforeEach(() => {
    localStorage.setItem("access_token", "token");
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/conversations/7") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 7,
              title: "PhotoDoodle",
              status: "running",
              created_at: "2026-05-20T00:00:00Z",
              updated_at: "2026-05-20T00:00:00Z",
            }),
        } as Response);
      }
      if (url === "/api/conversations/7/runtime-credentials") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              lab4ai_credentials: {
                configured: true,
                phone_masked: "138****8000",
              },
              instances: [
                {
                  id: 1,
                  server_id: "srv-123",
                  instance_id: "inst-123",
                  instance_type: "CPU",
                  status: "running",
                  username: "root",
                  password: "ssh-secret",
                  ssh_host: "10.0.0.8",
                  ssh_port: 2222,
                  ssh_command: "ssh -p 2222 root@10.0.0.8",
                  started_at: "2026-05-20T00:00:00Z",
                  stopped_at: null,
                },
              ],
            }),
        } as Response);
      }
      if (url === "/api/conversations/7/workspace-files") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              exists: true,
              root: "runtime/workspaces/7",
              files: [
                {
                  path: "PhotoDoodle/PhotoDoodle_Final_Repro_Report.md",
                  name: "PhotoDoodle_Final_Repro_Report.md",
                  kind: "file",
                  size: 2048,
                  modified_at: "2026-05-20T01:00:00Z",
                  depth: 1,
                },
                {
                  path: "reports/result.md",
                  name: "result.md",
                  kind: "file",
                  size: 42,
                  modified_at: "2026-05-20T00:00:00Z",
                  depth: 1,
                },
                {
                  path: "logs/run.txt",
                  name: "run.txt",
                  kind: "file",
                  size: 12,
                  modified_at: "2026-05-20T00:00:00Z",
                  depth: 1,
                },
              ],
            }),
        } as Response);
      }
      if (url === "/api/conversations/7/workspace-files/content?path=reports%2Fresult.md") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              path: "reports/result.md",
              name: "result.md",
              kind: "markdown",
              content: "# 复现报告\n\n| 指标 | 数值 |\n|---|---|\n| PSNR | 28.4 |\n",
            }),
        } as Response);
      }
      if (
        url ===
        "/api/conversations/7/workspace-files/content?path=PhotoDoodle%2FPhotoDoodle_Final_Repro_Report.md"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              path: "PhotoDoodle/PhotoDoodle_Final_Repro_Report.md",
              name: "PhotoDoodle_Final_Repro_Report.md",
              kind: "markdown",
              content:
                "# PhotoDoodle 自动化复现报告\n\n## 结果对比\n\n| 指标 | 数值 |\n|---|---|\n| PSNR | 28.4 |\n",
            }),
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("shows masked Lab4AI login credentials above task instances", async () => {
    renderRightPanel();

    const loginCard = await screen.findByTestId("lab4ai-login-credentials");
    expect(within(loginCard).getByText("Lab4AI 登录凭证")).toBeInTheDocument();
    expect(within(loginCard).getByText("已登录")).toBeInTheDocument();
    expect(within(loginCard).getByText("138****8000")).toBeInTheDocument();
    expect(screen.queryByText("lab4ai-secret")).not.toBeInTheDocument();

    expect(await screen.findByText("Lab4AI 实例")).toBeInTheDocument();
    expect(screen.getByText("CPU 实例 · srv-123")).toBeInTheDocument();
    expect(screen.getByText("ssh-secret")).toBeInTheDocument();
  });

  it("previews markdown files from the workspace list", async () => {
    renderRightPanel();

    fireEvent.click(await screen.findByRole("button", { name: "result.md" }));

    const preview = await screen.findByTestId("workspace-markdown-preview");
    expect(within(preview).getByText("reports/result.md")).toBeInTheDocument();
    expect(await within(preview).findByRole("heading", { name: "复现报告" })).toBeInTheDocument();
    expect(within(preview).getByText("PSNR")).toBeInTheDocument();
    expect(within(preview).getByText("28.4")).toBeInTheDocument();

    fireEvent.click(within(preview).getByRole("button", { name: "返回文件列表" }));

    expect(await screen.findByRole("button", { name: "result.md" })).toBeInTheDocument();
    expect(screen.queryByTestId("workspace-markdown-preview")).not.toBeInTheDocument();
  });

  it("highlights and previews the final markdown report from the workspace", async () => {
    renderRightPanel();

    const reportButton = await screen.findByRole("button", {
      name: "预览最终报告 PhotoDoodle_Final_Repro_Report.md",
    });
    expect(within(reportButton).getByText("最终报告")).toBeInTheDocument();

    fireEvent.click(reportButton);

    const preview = await screen.findByTestId("workspace-markdown-preview");
    expect(within(preview).getByText("Markdown 预览")).toBeInTheDocument();
    expect(within(preview).getByText("PhotoDoodle/PhotoDoodle_Final_Repro_Report.md")).toBeInTheDocument();
    expect(within(preview).getByRole("button", { name: "刷新预览" })).toBeInTheDocument();
    expect(await within(preview).findByRole("heading", { name: "PhotoDoodle 自动化复现报告" })).toBeInTheDocument();
    expect(await within(preview).findByRole("heading", { name: "结果对比" })).toBeInTheDocument();
  });
});
