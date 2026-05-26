import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Sidebar from "../components/Sidebar";

function renderSidebar(path = "/paper-only/demo/zero-code-board") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Sidebar", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(
      "zero_code_demo_history",
      JSON.stringify({
        title: "GeneCLR 纯论文复现演示",
        status: "running",
        href: "/paper-only/demo/zero-code-board?paper_url=https%3A%2F%2Farxiv.org%2Fabs%2F2301.12345",
      })
    );
    globalThis.fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/conversations") {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
        } as Response);
      }
      if (url === "/api/cloud-instances/quota") {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              gpu_quota_hours: 0,
              cpu_quota_hours: 0,
              gpu_used_hours: 0,
              cpu_used_hours: 0,
            }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
      } as Response);
    });
  });

  it("shows the running zero-code demo in history without backend conversations", async () => {
    renderSidebar();

    fireEvent.click(screen.getByRole("button", { name: /历史任务/ }));

    const demoLink = await screen.findByRole("link", { name: /GeneCLR 纯论文复现演示/ });
    expect(demoLink).toHaveAttribute(
      "href",
      "/paper-only/demo/zero-code-board?paper_url=https%3A%2F%2Farxiv.org%2Fabs%2F2301.12345"
    );
    expect(screen.queryByText("暂无历史任务")).not.toBeInTheDocument();
  });
});
