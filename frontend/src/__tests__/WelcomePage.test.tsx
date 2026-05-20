import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import WelcomePage, { parseTaskInput } from "../components/WelcomePage";

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
