import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import LoginPage from "../pages/LoginPage";

const { navigateMock } = vi.hoisted(() => ({
  navigateMock: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

function renderLogin() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    navigateMock.mockReset();
    localStorage.clear();
  });

  it("renders login form by default", () => {
    renderLogin();
    expect(screen.getByText("AutoResearch24")).toBeInTheDocument();
    expect(screen.queryByText("LOBSTER")).not.toBeInTheDocument();
    expect(screen.getByText("欢迎回来")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("手机号")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument();
  });

  it("switches to register mode", async () => {
    renderLogin();
    const user = userEvent.setup();
    await user.click(screen.getByText("没有账号？去注册"));
    expect(screen.getByText("创建账号")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("机构/学校")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("确认密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "注册并登录" })).toBeInTheDocument();
  });

  it("switches back to login mode", async () => {
    renderLogin();
    const user = userEvent.setup();
    await user.click(screen.getByText("没有账号？去注册"));
    await user.click(screen.getByText("已有账号？去登录"));
    expect(screen.getByText("欢迎回来")).toBeInTheDocument();
  });

  it("shows local validation error for invalid phone", async () => {
    renderLogin();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("手机号"), "12345");
    await user.type(screen.getByPlaceholderText("密码"), "secret123");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText("请输入有效的中国大陆手机号")).toBeInTheDocument();
  });

  it("shows local validation error for mismatched passwords", async () => {
    renderLogin();
    const user = userEvent.setup();
    await user.click(screen.getByText("没有账号？去注册"));
    await user.type(screen.getByPlaceholderText("手机号"), "13800138000");
    await user.type(screen.getByPlaceholderText("机构/学校"), "Test University");
    await user.type(screen.getByPlaceholderText("密码"), "secret123");
    await user.type(screen.getByPlaceholderText("确认密码"), "secret456");
    await user.click(screen.getByRole("button", { name: "注册并登录" }));
    expect(await screen.findByText("两次输入的密码不一致")).toBeInTheDocument();
  });

  it("allows admin backdoor login without phone validation", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ access_token: "admin-token" }),
    });

    renderLogin();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("手机号"), "admin");
    await user.type(screen.getByPlaceholderText("密码"), "admin123");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        body: expect.any(URLSearchParams),
        method: "POST",
      })
    );
    expect(localStorage.getItem("access_token")).toBe("admin-token");
    expect(navigateMock).toHaveBeenCalledWith("/");
  });

  it("registers with institution and logs in after success", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ username: "13800138000" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ access_token: "registered-token" }),
      });
    globalThis.fetch = fetchMock;

    renderLogin();
    const user = userEvent.setup();
    await user.click(screen.getByText("没有账号？去注册"));
    await user.type(screen.getByPlaceholderText("手机号"), "13800138000");
    await user.type(screen.getByPlaceholderText("机构/学校"), "Test University");
    await user.type(screen.getByPlaceholderText("密码"), "secret123");
    await user.type(screen.getByPlaceholderText("确认密码"), "secret123");
    await user.click(screen.getByRole("button", { name: "注册并登录" }));

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/auth/register",
      expect.objectContaining({
        body: JSON.stringify({
          phone: "13800138000",
          institution: "Test University",
          password: "secret123",
        }),
        method: "POST",
      })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/auth/login",
      expect.objectContaining({
        body: expect.any(URLSearchParams),
        method: "POST",
      })
    );
    expect(localStorage.getItem("access_token")).toBe("registered-token");
    expect(navigateMock).toHaveBeenCalledWith("/");
  });

  it("maps backend validation detail to friendly register message", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: () =>
        Promise.resolve({
          detail: [{ loc: ["body", "institution"], msg: "String should have at least 1 character" }],
        }),
    });

    renderLogin();
    const user = userEvent.setup();
    await user.click(screen.getByText("没有账号？去注册"));
    await user.type(screen.getByPlaceholderText("手机号"), "13800138000");
    await user.type(screen.getByPlaceholderText("机构/学校"), "Test University");
    await user.type(screen.getByPlaceholderText("密码"), "secret123");
    await user.type(screen.getByPlaceholderText("确认密码"), "secret123");
    await user.click(screen.getByRole("button", { name: "注册并登录" }));

    expect(await screen.findByText("请输入机构或学校名称")).toBeInTheDocument();
  });

  it("shows error on failed login", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "手机号或密码错误" }),
    });

    renderLogin();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("手机号"), "13800138000");
    await user.type(screen.getByPlaceholderText("密码"), "badpass");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("手机号或密码错误")).toBeInTheDocument();
  });
});
