import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import LoginPage from "../pages/LoginPage";

function renderLogin() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>
  );
}

describe("LoginPage", () => {
  it("renders login form by default", () => {
    renderLogin();
    expect(screen.getByText("欢迎回来")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("用户名")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument();
  });

  it("switches to register mode", async () => {
    renderLogin();
    const user = userEvent.setup();
    await user.click(screen.getByText("没有账号？去注册"));
    expect(screen.getByText("创建账号")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "注册并登录" })).toBeInTheDocument();
  });

  it("switches back to login mode", async () => {
    renderLogin();
    const user = userEvent.setup();
    await user.click(screen.getByText("没有账号？去注册"));
    await user.click(screen.getByText("已有账号？去登录"));
    expect(screen.getByText("欢迎回来")).toBeInTheDocument();
  });

  it("shows error on failed login", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "用户名或密码错误" }),
    });

    renderLogin();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("用户名"), "baduser");
    await user.type(screen.getByPlaceholderText("密码"), "badpass");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("用户名或密码错误")).toBeInTheDocument();
  });
});
