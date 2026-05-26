import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
                  path: "PhotoDoodle",
                  name: "PhotoDoodle",
                  kind: "directory",
                  size: null,
                  modified_at: "2026-05-20T01:00:00Z",
                  depth: 0,
                },
                {
                  path: "PhotoDoodle/notes.txt",
                  name: "notes.txt",
                  kind: "file",
                  size: 12,
                  modified_at: "2026-05-20T01:00:00Z",
                  depth: 1,
                },
                {
                  path: "PhotoDoodle/PhotoDoodle_Final_Repro_Report.docx",
                  name: "PhotoDoodle_Final_Repro_Report.docx",
                  kind: "file",
                  size: 4096,
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
                {
                  path: "root-report.txt",
                  name: "root-report.txt",
                  kind: "file",
                  size: 12,
                  modified_at: "2026-05-20T00:00:00Z",
                  depth: 0,
                },
              ],
            }),
        } as Response);
      }
      if (url === "/api/conversations/7/workspace-files/download?path=PhotoDoodle%2Fnotes.txt") {
        return Promise.resolve({
          ok: true,
          blob: () => Promise.resolve(new Blob(["download me"], { type: "text/plain" })),
          headers: new Headers({
            "content-disposition": 'attachment; filename="notes.txt"',
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
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("keeps the right panel fixed while credentials and workspace scroll independently", async () => {
    renderRightPanel();

    const credentialTitle = await screen.findByText("权限与环境配置");
    const rightPanel = credentialTitle.closest("aside");
    expect(rightPanel).toHaveClass("h-full");
    expect(rightPanel).toHaveClass("overflow-hidden");
    expect(rightPanel).not.toHaveClass("overflow-y-auto");

    const sections = rightPanel?.querySelectorAll("section");
    expect(sections).toHaveLength(2);
    sections?.forEach((section) => {
      expect(section).toHaveClass("flex-1");
      expect(section).toHaveClass("basis-0");
      expect(section).toHaveClass("min-h-0");
      expect(section).not.toHaveClass("shrink-0");
    });
    expect(sections?.[0]).not.toHaveClass("h-[44%]");
    expect(sections?.[0].querySelector(".overflow-y-auto")).toBeTruthy();
    expect(sections?.[1].querySelector(".overflow-y-auto")).toBeTruthy();
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

  it("renders the docx report in the normal project directory tree without priority styling", async () => {
    renderRightPanel();

    const rows = await screen.findAllByTestId(/workspace-file-row-/);
    expect(rows.map((row) => row.getAttribute("data-testid"))).toEqual([
      "workspace-file-row-PhotoDoodle",
      "workspace-file-row-PhotoDoodle/notes.txt",
      "workspace-file-row-PhotoDoodle/PhotoDoodle_Final_Repro_Report.docx",
      "workspace-file-row-reports/result.md",
      "workspace-file-row-logs/run.txt",
      "workspace-file-row-root-report.txt",
    ]);
    const reportRow = within(screen.getByTestId("workspace-file-row-PhotoDoodle/PhotoDoodle_Final_Repro_Report.docx"));
    expect(reportRow.getByText("PhotoDoodle_Final_Repro_Report.docx")).toBeInTheDocument();
    expect(reportRow.queryByText("最终报告")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /预览最终报告/ })).not.toBeInTheDocument();
    expect(screen.queryByText("PhotoDoodle_Final_Repro_Report.md")).not.toBeInTheDocument();
  });

  it("downloads files under the project directory and hides download outside it", async () => {
    const objectUrl = "blob:download-url";
    const createObjectURL = vi.fn(() => objectUrl);
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    const clickedDownloads: string[] = [];
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tagName: string) => {
      const element = originalCreateElement(tagName);
      if (tagName.toLowerCase() === "a") {
        vi.spyOn(element, "click").mockImplementation(() => {
          clickedDownloads.push((element as HTMLAnchorElement).download);
        });
      }
      return element;
    });

    renderRightPanel();

    const projectFileRow = await screen.findByTestId("workspace-file-row-PhotoDoodle/notes.txt");
    const rootFileRow = await screen.findByTestId("workspace-file-row-root-report.txt");
    expect(within(projectFileRow).getByRole("button", { name: "下载 notes.txt" })).toBeInTheDocument();
    expect(within(rootFileRow).queryByRole("button", { name: "下载 root-report.txt" })).not.toBeInTheDocument();

    fireEvent.click(within(projectFileRow).getByRole("button", { name: "下载 notes.txt" }));

    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.some((call) => String(call[0]).includes("/workspace-files/download?path=PhotoDoodle%2Fnotes.txt"))).toBe(true);
    await waitFor(() => {
      expect(clickedDownloads).toContain("notes.txt");
    });
    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith(objectUrl);
  });
});
