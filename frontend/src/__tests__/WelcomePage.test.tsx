import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import WelcomePage, { parseTaskInput } from "../components/WelcomePage";
import AutoResearchPage from "../pages/AutoResearchPage";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderWelcome(props?: Partial<Parameters<typeof WelcomePage>[0]>) {
  return render(
    <MemoryRouter>
      <WelcomePage
        title="复现项目"
        placeholder="粘贴 GitHub URL..."
        suggestions={["示例1", "示例2"]}
        {...props}
      />
    </MemoryRouter>
  );
}

describe("WelcomePage", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    vi.restoreAllMocks();
  });

  it("renders title and suggestions", () => {
    renderWelcome();
    expect(screen.getByText("复现项目")).toBeInTheDocument();
    expect(screen.getByText("示例1")).toBeInTheDocument();
    expect(screen.getByText("示例2")).toBeInTheDocument();
  });

  it("clicking suggestion fills input", async () => {
    renderWelcome();
    const user = userEvent.setup();
    await user.click(screen.getByText("示例1"));
    expect(screen.getByRole("textbox")).toHaveValue("示例1");
  });

  it("shows error when github url is required but missing", async () => {
    renderWelcome({ requireGithubUrl: true });
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox"), "just some text");
    const submitBtn = screen.getByRole("button", { name: "" });
    await user.click(submitBtn);

    expect(await screen.findByText("请在消息中包含一个 GitHub URL")).toBeInTheDocument();
  });

  it("submits successfully with github url", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ id: 42 }),
    });
    globalThis.fetch = fetchMock;

    renderWelcome({ basePath: "/search" });
    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox"),
      "https://github.com/example/repo 复现这个项目"
    );
    const buttons = screen.getAllByRole("button");
    const submitBtn = buttons[0];
    await user.click(submitBtn);

    await vi.waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/search/task/42");
    });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      github_url: "https://github.com/example/repo",
      user_prompt: "复现这个项目",
      original_input: "https://github.com/example/repo 复现这个项目",
    });
  });

  it("uses explicit task type for auto-research entry", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ id: 44 }),
    });
    globalThis.fetch = fetchMock;

    renderWelcome({
      basePath: "/auto-research",
      taskType: "experiments",
      requireGithubUrl: true,
    });
    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox"),
      "帮我跑下https://github.com/jingyaogong/minimind的自动化训练实验"
    );
    await user.click(screen.getAllByRole("button")[0]);

    await vi.waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/auto-research/task/44");
    });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      task_type: "experiments",
      github_url: "https://github.com/jingyaogong/minimind",
      user_prompt: "帮我跑下的自动化训练实验",
      original_input: "帮我跑下https://github.com/jingyaogong/minimind的自动化训练实验",
    });
  });

  it("does not require github url when requireGithubUrl is false", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ id: 10 }),
    });

    renderWelcome({ requireGithubUrl: false });
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox"), "搜索相关论文");
    const buttons = screen.getAllByRole("button");
    const submitBtn = buttons[0];
    await user.click(submitBtn);

    await vi.waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/reproduce/task/10");
    });
  });

  it("navigates to demo route without creating a conversation when demoSubmitPath is provided", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock;

    renderWelcome({
      requireGithubUrl: false,
      basePath: "/paper-only",
      demoSubmitPath: "/paper-only/demo/zero-code-board",
    });
    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox"),
      "https://arxiv.org/abs/2301.12345 复现这篇论文"
    );
    await user.click(screen.getAllByRole("button")[0]);

    await vi.waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        "/paper-only/demo/zero-code-board?paper_url=https%3A%2F%2Farxiv.org%2Fabs%2F2301.12345&prompt=%E5%A4%8D%E7%8E%B0%E8%BF%99%E7%AF%87%E8%AE%BA%E6%96%87&original_input=https%3A%2F%2Farxiv.org%2Fabs%2F2301.12345+%E5%A4%8D%E7%8E%B0%E8%BF%99%E7%AF%87%E8%AE%BA%E6%96%87"
      );
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("routes the auto-research minimind request into the mock run page", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock;

    render(
      <MemoryRouter>
        <AutoResearchPage />
      </MemoryRouter>
    );
    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox"),
      "帮我跑下https://github.com/jingyaogong/minimind的自动化训练实验"
    );
    await user.click(screen.getAllByRole("button")[0]);

    await vi.waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        "/auto-research/demo/mock-run?github_url=https%3A%2F%2Fgithub.com%2Fjingyaogong%2Fminimind&prompt=%E5%B8%AE%E6%88%91%E8%B7%91%E4%B8%8B%E7%9A%84%E8%87%AA%E5%8A%A8%E5%8C%96%E8%AE%AD%E7%BB%83%E5%AE%9E%E9%AA%8C&original_input=%E5%B8%AE%E6%88%91%E8%B7%91%E4%B8%8Bhttps%3A%2F%2Fgithub.com%2Fjingyaogong%2Fminimind%E7%9A%84%E8%87%AA%E5%8A%A8%E5%8C%96%E8%AE%AD%E7%BB%83%E5%AE%9E%E9%AA%8C"
      );
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("extracts URLs without swallowing adjacent Chinese text", () => {
    expect(
      parseTaskInput(
        "https://github.com/showlab/PhotoDoodle。论文链接：https://arxiv.org/pdf/2502.14397 帮我复现一下"
      )
    ).toEqual({
      githubUrl: "https://github.com/showlab/PhotoDoodle",
      paperUrl: "https://arxiv.org/pdf/2502.14397",
      userPrompt: "帮我复现一下",
    });
  });

  it("submits Chinese prompt separately from adjacent URLs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ id: 43 }),
    });
    globalThis.fetch = fetchMock;

    renderWelcome();
    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox"),
      "https://github.com/showlab/PhotoDoodle。论文链接：https://arxiv.org/pdf/2502.14397 帮我复现一下"
    );
    await user.click(screen.getAllByRole("button")[0]);

    await vi.waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/reproduce/task/43");
    });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      github_url: "https://github.com/showlab/PhotoDoodle",
      paper_url: "https://arxiv.org/pdf/2502.14397",
      user_prompt: "帮我复现一下",
      original_input:
        "https://github.com/showlab/PhotoDoodle。论文链接：https://arxiv.org/pdf/2502.14397 帮我复现一下",
    });
  });
});
