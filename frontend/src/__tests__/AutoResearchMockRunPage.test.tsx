import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import AutoResearchMockRunPage from "../pages/AutoResearchMockRunPage";

const DEMO_PATH =
  "/auto-research/demo/mock-run?github_url=https%3A%2F%2Fgithub.com%2Fjingyaogong%2Fminimind&prompt=%E5%B8%AE%E6%88%91%E8%B7%91%E4%B8%8B%E7%9A%84%E8%87%AA%E5%8A%A8%E5%8C%96%E8%AE%AD%E7%BB%83%E5%AE%9E%E9%AA%8C&original_input=%E5%B8%AE%E6%88%91%E8%B7%91%E4%B8%8Bhttps%3A%2F%2Fgithub.com%2Fjingyaogong%2Fminimind%E7%9A%84%E8%87%AA%E5%8A%A8%E5%8C%96%E8%AE%AD%E7%BB%83%E5%AE%9E%E9%AA%8C";

function renderDemo() {
  return render(
    <MemoryRouter initialEntries={[DEMO_PATH]}>
      <Routes>
        <Route path="/auto-research/demo/mock-run" element={<AutoResearchMockRunPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("AutoResearchMockRunPage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reveals one agent reply with the same timing sequence as the paper-only board", async () => {
    renderDemo();

    expect(screen.getByText("帮我跑下https://github.com/jingyaogong/minimind的自动化训练实验")).toBeInTheDocument();
    expect(screen.getAllByTestId("agent-message")).toHaveLength(1);
    expect(screen.getByText("正在读取 GitHub 仓库地址并判断自动化训练入口...")).toBeInTheDocument();
    expect(screen.queryByText("Agent Routing")).not.toBeInTheDocument();
    expect(screen.queryByTestId("autoresearch-mock-agent-panel")).not.toBeInTheDocument();

    await advanceDemoTimers(1200);
    expect(screen.queryByText("Agent Routing")).not.toBeInTheDocument();
    expect(screen.queryByTestId("autoresearch-mock-agent-panel")).not.toBeInTheDocument();

    await advanceDemoTimers(1200);
    expect(screen.getByText("Agent Routing")).toBeInTheDocument();
    expect(screen.queryByTestId("autoresearch-mock-agent-panel")).not.toBeInTheDocument();

    await advanceDemoTimers(800);

    expect(screen.queryByTestId("autoresearch-mock-agent-panel")).not.toBeInTheDocument();
    expect(screen.getByText("配置 Lab4AI 平台账号")).toBeInTheDocument();
    let rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expect(within(rightPanel).getByText("未配置")).toBeInTheDocument();
    expect(within(rightPanel).getByText("Lab4AI 凭证未配置，等待账号登录。")).toBeInTheDocument();

    loginLab4AI();
    expect(screen.getByText("Credential Setup")).toBeInTheDocument();
    expect(screen.queryByTestId("autoresearch-mock-agent-panel")).not.toBeInTheDocument();
    rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expect(within(rightPanel).getByText("工作区待创建，确认后会展示生成文件。")).toBeInTheDocument();
    expect(within(rightPanel).queryByText("autoresearch_report.md")).not.toBeInTheDocument();
    await advanceDemoTimers(450);
    expect(screen.getByText("已收到 Lab4AI 登录凭证，正在进行本地脱敏处理。")).toBeInTheDocument();
    await advanceDemoTimers(600);
    expect(screen.getByText("正在写入受控运行上下文，密码不会在页面明文展示。")).toBeInTheDocument();
    await advanceDemoTimers(1_050);

    const panel = screen.getByTestId("autoresearch-mock-agent-panel");
    expect(within(panel).getByText("Lab4AI Auto Research")).toBeInTheDocument();
    expect(within(panel).getByText("自动化训练实验流水线")).toBeInTheDocument();
    expect(within(panel).getByText("Pipeline Steps")).toBeInTheDocument();
    expect(within(panel).getByText("instance_provision")).toBeInTheDocument();
    expect(within(panel).queryByText("policies")).not.toBeInTheDocument();
    expect(within(panel).queryByText("instance_teardown")).not.toBeInTheDocument();
    expect(within(panel).queryByText("Gate Log")).not.toBeInTheDocument();

    const hitl = screen.getByTestId("step-human-input");
    expect(hitl).toHaveTextContent("Lab instance flow");
    expect(hitl).toHaveTextContent("Gate: lab_instance_flow");
    expect(hitl).toHaveTextContent("lab4ai_create_instance");
    expect(screen.queryByTestId("autoresearch-mock-hitl")).not.toBeInTheDocument();
    rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expect(within(rightPanel).getByText("Lab4AI 登录凭证")).toBeInTheDocument();
    expect(within(rightPanel).getByText("平台统一账号，仅展示脱敏信息")).toBeInTheDocument();
    expect(within(rightPanel).getByText("已配置")).toBeInTheDocument();
    expect(within(rightPanel).getByText("已安全保存")).toBeInTheDocument();
    expect(within(rightPanel).getByText("Lab4AI 实例")).toBeInTheDocument();
    expect(document.body.textContent || "").not.toContain("lab4ai-instance");
    expectNoDemoDisclosure();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("simulates the HITL conversation and reveals workspace artifacts in step order", async () => {
    renderDemo();
    await revealWorkflow();
    loginLab4AI();
    await completeCredentialStream();

    let rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expect(within(rightPanel).getByText("工作区待创建，确认后会展示生成文件。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "创建实例" }));
    let panel = screen.getByTestId("autoresearch-mock-agent-panel");
    expect(within(panel).queryByText("policies")).not.toBeInTheDocument();
    expect(screen.queryByTestId("step-human-input")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    panel = screen.getByTestId("autoresearch-mock-agent-panel");
    expect(within(panel).getByText("policies")).toBeInTheDocument();
    expect(within(panel).getByText("⏳执行中")).toBeInTheDocument();
    expect(within(panel).queryByText("setup")).not.toBeInTheDocument();
    rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expectInWorkspaceOrder(rightPanel, ["lab_instance.json", "ssh_connection.txt"]);

    await advanceDemoTimers(15_000);
    panel = screen.getByTestId("autoresearch-mock-agent-panel");
    expect(within(panel).getByText("setup")).toBeInTheDocument();
    expect(within(panel).getByText("⏳执行中")).toBeInTheDocument();
    expect(within(panel).queryByText("environments")).not.toBeInTheDocument();
    rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expectInWorkspaceOrder(rightPanel, ["lab_instance.json", "ssh_connection.txt"]);
    expect(within(rightPanel).queryByText("project_summary.md")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    panel = screen.getByTestId("autoresearch-mock-agent-panel");
    expect(within(panel).getByText("environments")).toBeInTheDocument();
    expect(within(panel).queryByText("experimentation")).not.toBeInTheDocument();
    rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expectInWorkspaceOrder(rightPanel, ["lab_instance.json", "ssh_connection.txt", "project_summary.md", "results.tsv"]);
    expect(within(rightPanel).queryByText("environment.md")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    expect(screen.getByText("Step 5 参数配置")).toBeInTheDocument();
    expect(screen.getByText(/你要选哪个方案/)).toBeInTheDocument();
    expect(screen.getByText("- 稳妥参数：epochs=1 batch_size=16 lr=3e-4")).toBeInTheDocument();
    panel = screen.getByTestId("autoresearch-mock-agent-panel");
    expect(
      panel.compareDocumentPosition(screen.getByText("Step 5 参数配置").closest("section") as HTMLElement) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(within(panel).getByText("experimentation")).toBeInTheDocument();
    expect(within(panel).queryByText("output_and_logging")).not.toBeInTheDocument();
    expect(within(panel).queryByText("final_report")).not.toBeInTheDocument();
    rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expectInWorkspaceOrder(rightPanel, ["project_summary.md", "results.tsv", "environment.md"]);
    expect(within(rightPanel).queryByText("round_01.log")).not.toBeInTheDocument();

    submitFollowUp("稳妥参数：epochs=1 batch_size=16 lr=3e-4");
    expect(screen.getByText("收到，Step 5 实验方案按你的输入配置：稳妥参数：epochs=1 batch_size=16 lr=3e-4")).toBeInTheDocument();
    expect(screen.queryByText("Step 5 参数配置")).not.toBeInTheDocument();
    expect(screen.queryByText(/你要选哪个方案/)).not.toBeInTheDocument();
    let panels = screen.getAllByTestId("autoresearch-mock-agent-panel");
    expect(panels).toHaveLength(2);
    expect(within(panels[0]).getByText("experimentation")).toBeInTheDocument();
    expect(within(panels[0]).queryByText("output_and_logging")).not.toBeInTheDocument();
    panel = panels[1];
    expect(within(panel).getByText("正在写入实验方案：稳妥参数：epochs=1 batch_size=16 lr=3e-4")).toBeInTheDocument();
    expect(within(panel).queryByText("output_and_logging")).not.toBeInTheDocument();
    expect(within(panel).queryByText("experiment_loop")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    panels = screen.getAllByTestId("autoresearch-mock-agent-panel");
    expect(panels).toHaveLength(2);
    panel = panels[1];
    expect(within(panel).getByText("output_and_logging")).toBeInTheDocument();
    expect(within(panel).queryByText("experiment_loop")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    expect(screen.getByText("Step 7 训练参数配置")).toBeInTheDocument();
    expect(screen.getByText(/训练循环的关键参数需要你确认/)).toBeInTheDocument();
    expect(screen.getByText("- 启动训练：3 轮 / 单轮 5 分钟 / val_loss")).toBeInTheDocument();
    panels = screen.getAllByTestId("autoresearch-mock-agent-panel");
    expect(panels).toHaveLength(2);
    panel = panels[1];
    expect(
      panel.compareDocumentPosition(screen.getByText("Step 7 训练参数配置").closest("section") as HTMLElement) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(within(panel).getByText("experiment_loop")).toBeInTheDocument();
    expect(within(panel).queryByText("final_report")).not.toBeInTheDocument();

    submitFollowUp("启动训练：3 轮 / 单轮 5 分钟 / val_loss");
    expect(screen.getByText("收到，Step 7 训练关键参数按你的输入配置：启动训练：3 轮 / 单轮 5 分钟 / val_loss")).toBeInTheDocument();
    expect(screen.queryByText("Step 7 训练参数配置")).not.toBeInTheDocument();
    expect(screen.queryByText(/训练循环的关键参数需要你确认/)).not.toBeInTheDocument();
    panels = screen.getAllByTestId("autoresearch-mock-agent-panel");
    expect(panels).toHaveLength(3);
    expect(within(panels[1]).getByText("experiment_loop")).toBeInTheDocument();
    expect(within(panels[1]).queryByText("final_report")).not.toBeInTheDocument();
    panel = panels[2];
    expect(within(panel).getByText("执行中：启动训练：3 轮 / 单轮 5 分钟 / val_loss")).toBeInTheDocument();
    await advanceDemoTimers(59_000);
    panels = screen.getAllByTestId("autoresearch-mock-agent-panel");
    expect(panels).toHaveLength(3);
    panel = panels[2];
    expect(within(panel).getByText("执行中：启动训练：3 轮 / 单轮 5 分钟 / val_loss")).toBeInTheDocument();
    expect(within(panel).getByText("⏳执行中")).toBeInTheDocument();
    expect(within(panel).queryByText("final_report")).not.toBeInTheDocument();

    await advanceDemoTimers(1_000);
    panels = screen.getAllByTestId("autoresearch-mock-agent-panel");
    panel = panels[2];
    expect(within(panel).getByText("final_report")).toBeInTheDocument();
    expect(within(panel).queryByText("instance_teardown")).not.toBeInTheDocument();
    rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expectInWorkspaceOrder(rightPanel, [
      "environment.md",
      "round_01.log",
      "round_02.log",
      "round_03.log",
      "autoresearch_report.md",
    ]);
    expect(within(rightPanel).queryByText("instance_stop.json")).not.toBeInTheDocument();
    expect(within(rightPanel).getByLabelText("project_summary.md")).toHaveTextContent("下载");
    expect(within(rightPanel).getByLabelText("environment.md")).toHaveTextContent("下载");

    await advanceDemoTimers(15_000);
    expect(screen.getByTestId("step-human-input")).toHaveTextContent("关机确认");
    panels = screen.getAllByTestId("autoresearch-mock-agent-panel");
    panel = panels[2];
    expect(within(panel).getByText("instance_teardown")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "立即关闭实例" }));
    expect(screen.queryByTestId("step-human-input")).not.toBeInTheDocument();
    rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    panels = screen.getAllByTestId("autoresearch-mock-agent-panel");
    panel = panels[2];
    expect(within(panel).getByText("正在关闭实例并写入 instance_stop.json")).toBeInTheDocument();
    expect(within(panel).getByText("⏳执行中")).toBeInTheDocument();
    expect(within(rightPanel).getByText("实例关闭中")).toBeInTheDocument();
    expect(document.body.textContent || "").not.toContain("10 秒后");
    expect(document.body.textContent || "").not.toContain("10秒后");
    expect(within(rightPanel).queryByText("instance_stop.json")).not.toBeInTheDocument();
    expect(screen.queryByText("自动化训练实验完成，相关产物可以在工作区查看。")).not.toBeInTheDocument();

    await advanceDemoTimers(9_000);
    rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expect(within(rightPanel).queryByText("instance_stop.json")).not.toBeInTheDocument();
    expect(screen.queryByText("自动化训练实验完成，相关产物可以在工作区查看。")).not.toBeInTheDocument();

    await advanceDemoTimers(1_000);
    rightPanel = screen.getByTestId("autoresearch-demo-right-panel");
    expectInWorkspaceOrder(rightPanel, ["autoresearch_report.md", "instance_stop.json"]);
    expect(screen.getByText("自动化训练实验完成，相关产物可以在工作区查看。")).toBeInTheDocument();
    expectNoDemoDisclosure();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});

function expectInWorkspaceOrder(container: HTMLElement, names: string[]) {
  const nodes = names.map((name) => within(container).getByText(name));
  for (let index = 0; index < nodes.length - 1; index += 1) {
    expect(nodes[index].compareDocumentPosition(nodes[index + 1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  }
}

async function revealWorkflow() {
  await advanceDemoTimers(3200);
}

function loginLab4AI() {
  fireEvent.change(screen.getByLabelText("Lab4AI 账号"), { target: { value: "13812348000" } });
  fireEvent.change(screen.getByLabelText("Lab4AI 密码"), { target: { value: "lab4ai-password" } });
  fireEvent.click(screen.getByRole("button", { name: "登录并继续" }));
}

async function completeCredentialStream() {
  await advanceDemoTimers(2_100);
}

function submitFollowUp(content: string) {
  fireEvent.change(screen.getByLabelText("继续输入任务需求"), { target: { value: content } });
  fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
}

async function advanceDemoTimers(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function expectNoDemoDisclosure() {
  expect(document.body.textContent || "").not.toMatch(/mock|模拟|演示/i);
}
