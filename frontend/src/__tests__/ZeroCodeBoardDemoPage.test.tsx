import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ZeroCodeBoardDemoPage from "../pages/ZeroCodeBoardDemoPage";

const DEMO_PATH =
  "/paper-only/demo/zero-code-board?paper_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2502.14397&prompt=%E5%A4%8D%E7%8E%B0%E8%BF%99%E7%AF%87%E8%AE%BA%E6%96%87%EF%BC%8C%E4%BD%86%E6%B2%A1%E6%9C%89%E4%BB%A3%E7%A0%81%E4%BB%93%E5%BA%93&original_input=%E5%A4%8D%E7%8E%B0%E8%BF%99%E7%AF%87%E8%AE%BA%E6%96%87%EF%BC%8C%E4%BD%86%E6%B2%A1%E6%9C%89%E4%BB%A3%E7%A0%81%E4%BB%93%E5%BA%93%EF%BC%9Ahttps%3A%2F%2Farxiv.org%2Fpdf%2F2502.14397";

function renderDemo(path = DEMO_PATH) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/paper-only/demo/zero-code-board" element={<ZeroCodeBoardDemoPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("ZeroCodeBoardDemoPage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts with only the submitted user message, then reveals agent routing with pauses", async () => {
    renderDemo();

    expect(screen.getByText("复现这篇论文，但没有代码仓库：https://arxiv.org/pdf/2502.14397")).toBeInTheDocument();
    expect(screen.getByTestId("agent-message")).toBeInTheDocument();
    expect(screen.getByText("AutoResearch24")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("正在读取论文地址并判断复现入口...")).toBeInTheDocument();
    expect(screen.queryByText("未检测到 GitHub 仓库，进入纯论文复现路径。")).not.toBeInTheDocument();
    expect(screen.queryByText("保存凭证并继续")).not.toBeInTheDocument();

    await advanceDemoTimers(1200);
    expect(screen.queryByText("未检测到 GitHub 仓库，进入纯论文复现路径。")).not.toBeInTheDocument();

    await advanceDemoTimers(1200);
    expect(screen.getByText("未检测到 GitHub 仓库，进入纯论文复现路径。")).toBeInTheDocument();
    expect(screen.getByText("选择 skill：zero-code-reproduction")).toBeInTheDocument();
    expect(screen.getByText(/候选插件：zero-code-repro-csai/)).toBeInTheDocument();
    expect(screen.getByText("请先配置 Lab4AI 平台凭证，后续实例创建会进入 HITL 确认。")).toBeInTheDocument();
    expect(screen.queryByText("保存凭证并继续")).not.toBeInTheDocument();

    await advanceDemoTimers(800);
    expect(screen.getByText("保存凭证并继续")).toBeInTheDocument();
    expect(screen.queryByTestId("zero-code-agent-panel")).not.toBeInTheDocument();

    const rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("未配置")).toBeInTheDocument();
    expect(within(rightPanel).getByText("Lab4AI 凭证未配置，等待用户输入。")).toBeInTheDocument();
    expect(within(rightPanel).queryByText("当前演示任务暂无 Lab4AI 实例连接信息。")).not.toBeInTheDocument();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("shows a fixed disabled follow-up chat box while the task is running", () => {
    renderDemo();

    const input = screen.getByRole("textbox", { name: "继续输入任务需求" });
    expect(input).toHaveAttribute("placeholder", "继续输入你的问题或调整要求...");
    expect(input).toBeDisabled();
    const sendButton = screen.getByRole("button", { name: "发送消息" });
    expect(sendButton).toBeDisabled();
    expect(screen.getByTestId("zero-code-follow-up-bar")).toHaveClass("shrink-0");
    expect(screen.getByTestId("zero-code-follow-up-bar")).toHaveClass("p-3");
    expect(screen.getByTestId("zero-code-follow-up-bar")).not.toHaveClass("mx-auto");
    expect(screen.getByTestId("zero-code-follow-up-bar")).not.toHaveClass("max-w-[1100px]");
    expect(screen.getByTestId("zero-code-follow-up-form")).toHaveClass("w-full");
    expect(screen.getByTestId("zero-code-follow-up-form")).not.toHaveClass("max-w-4xl");
    expect(screen.getByTestId("zero-code-follow-up-input-shell")).toHaveClass("rounded-xl");
    expect(screen.getByTestId("zero-code-follow-up-input-shell")).toHaveClass("focus-within:border-slate-300");
    expect(sendButton).toHaveClass("w-[32px]");
    expect(sendButton).toHaveClass("h-[32px]");
  });

  it("keeps the paper-only right panel fixed while credentials and workspace scroll independently", () => {
    renderDemo();

    const rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(rightPanel).toHaveClass("h-full");
    expect(rightPanel).toHaveClass("overflow-hidden");
    expect(rightPanel).not.toHaveClass("overflow-y-auto");

    const sections = rightPanel.querySelectorAll("section");
    expect(sections).toHaveLength(2);
    sections.forEach((section) => {
      expect(section).toHaveClass("flex-1");
      expect(section).toHaveClass("basis-0");
      expect(section).toHaveClass("min-h-0");
      expect(section).not.toHaveClass("shrink-0");
    });
    expect(sections[0]).not.toHaveClass("h-[45%]");
    expect(sections[0].querySelector(".overflow-y-auto")).toBeTruthy();
    expect(sections[1].querySelector(".overflow-y-auto")).toBeTruthy();
  });

  it("updates one agent reply in place as the demo advances", async () => {
    renderDemo();

    expect(screen.getAllByTestId("agent-message")).toHaveLength(1);
    expect(screen.getByText("AutoResearch24")).toBeInTheDocument();
    expect(screen.getByText("正在读取论文地址并判断复现入口...")).toBeInTheDocument();

    await advanceDemoTimers(1200);
    let agentMessages = screen.getAllByTestId("agent-message");
    expect(agentMessages).toHaveLength(1);
    expect(within(agentMessages[0]).getByText("正在读取论文地址并判断复现入口...")).toBeInTheDocument();

    await advanceDemoTimers(1200);
    agentMessages = screen.getAllByTestId("agent-message");
    expect(agentMessages).toHaveLength(1);
    expect(within(agentMessages[0]).getByText("未检测到 GitHub 仓库，进入纯论文复现路径。")).toBeInTheDocument();
    expect(within(agentMessages[0]).queryByText("正在读取论文地址并判断复现入口...")).not.toBeInTheDocument();

    await advanceDemoTimers(800);
    agentMessages = screen.getAllByTestId("agent-message");
    expect(agentMessages).toHaveLength(1);
    expect(within(agentMessages[0]).getByText("保存凭证并继续")).toBeInTheDocument();
    expect(screen.queryByTestId("zero-code-agent-panel")).not.toBeInTheDocument();
  });

  it("scrolls the conversation to the latest revealed content", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    renderDemo();
    expect(scrollIntoView).toHaveBeenCalledTimes(1);

    await advanceDemoTimers(2400);
    expect(scrollIntoView).toHaveBeenCalledTimes(2);

    await advanceDemoTimers(800);
    expect(scrollIntoView).toHaveBeenCalledTimes(3);

    fireEvent.change(screen.getByLabelText("Lab4AI 账号"), { target: { value: "13812348000" } });
    fireEvent.change(screen.getByLabelText("Lab4AI 密码"), { target: { value: "demo-password" } });
    fireEvent.click(screen.getByRole("button", { name: "保存凭证并继续" }));
    expect(scrollIntoView).toHaveBeenCalledTimes(4);
  });

  it("saves demo credentials, masks them in the right panel, then asks for CPU HITL", async () => {
    renderDemo();
    await revealCredentialForm();

    fireEvent.change(screen.getByLabelText("Lab4AI 账号"), { target: { value: "13812348000" } });
    fireEvent.change(screen.getByLabelText("Lab4AI 密码"), { target: { value: "demo-password" } });
    fireEvent.click(screen.getByRole("button", { name: "保存凭证并继续" }));

    const rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("已配置")).toBeInTheDocument();
    expect(within(rightPanel).getByText("138****8000")).toBeInTheDocument();
    expect(screen.queryByText("demo-password")).not.toBeInTheDocument();
    expect(screen.getByText("凭证已保存，开始加载 zero-code-reproduction workflow。")).toBeInTheDocument();
    expect(screen.getByText("需要创建远程 CPU 实例解析论文和生成脚手架。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认创建 CPU 实例" })).toBeInTheDocument();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("reveals the workflow gradually through CPU and GPU confirmations", async () => {
    renderDemo();
    await saveCredentials();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 CPU 实例" }));

    let panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).queryByText("执行位置")).not.toBeInTheDocument();
    expect(within(panel).queryByText("Gate Log")).not.toBeInTheDocument();
    expect(within(panel).getByText("step_0_remote_instance_init")).toBeInTheDocument();
    expect(within(panel).queryByText("step_1_paper_acquisition_parse")).not.toBeInTheDocument();

    await advanceDemoTimers(30_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_1_paper_acquisition_parse")).toBeInTheDocument();
    expect(within(panel).queryByText("step_2_domain_routing")).not.toBeInTheDocument();
    expect(within(panel).queryByText("step_9_gpu_validation_training")).not.toBeInTheDocument();

    await advanceDemoTimers(60_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_4_scaffold_generation")).toBeInTheDocument();
    expect(within(panel).queryByText("step_9_gpu_validation_training")).not.toBeInTheDocument();
    expect(screen.queryByText("CPU 阶段完成，下一步需要创建 GPU 实例做轻量验证。")).not.toBeInTheDocument();

    await advanceDemoTimers(60_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_8_release_cpu")).toBeInTheDocument();
    expect(screen.getByText("CPU 阶段完成，下一步需要创建 GPU 实例做轻量验证。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认创建 GPU 实例" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 GPU 实例" }));
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_9_gpu_validation_training")).toBeInTheDocument();
    expect(within(panel).queryByText("step_10_release_gpu")).not.toBeInTheDocument();
    expect(within(panel).queryByText("step_11_final_docx_report")).not.toBeInTheDocument();
    expect(within(panel).getAllByText(/7f26d6d2f7a94b93b02fd48b1e4c9a65/).length).toBeGreaterThan(0);

    const rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getAllByText(/481a8b5e60994cf98ed252ae0518edf0/).length).toBeGreaterThan(0);
    expect(within(rightPanel).getAllByText(/7f26d6d2f7a94b93b02fd48b1e4c9a65/).length).toBeGreaterThan(0);
    expect(within(rightPanel).getByText("CONFIDENCE_REPORT.md")).toBeInTheDocument();
    expect(within(rightPanel).getByText("geneclr.py")).toBeInTheDocument();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("continues from step 4 through step 8 before showing GPU step 9", async () => {
    renderDemo();
    await saveCredentials();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 CPU 实例" }));
    await advanceDemoTimers(90_000);

    let panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_4_scaffold_generation")).toBeInTheDocument();
    expect(within(panel).queryByText("step_5_quality_check")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确认创建 GPU 实例" })).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_5_quality_check")).toBeInTheDocument();
    expect(within(panel).queryByText("step_6_package_report")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_6_package_report")).toBeInTheDocument();
    expect(within(panel).queryByText("step_7_env_data_weights")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_7_env_data_weights")).toBeInTheDocument();
    expect(within(panel).queryByText("step_8_release_cpu")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_8_release_cpu")).toBeInTheDocument();
    expect(within(panel).queryByText("step_9_gpu_validation_training")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认创建 GPU 实例" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 GPU 实例" }));
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_9_gpu_validation_training")).toBeInTheDocument();
  });

  it("uses routed domain outputs and explicit waiting/completed status labels", async () => {
    renderDemo();
    await saveCredentials();

    let panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("⏳等待中...")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 CPU 实例" }));
    await advanceDemoTimers(60_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getAllByText("✅完成").length).toBeGreaterThan(0);
    expect(within(panel).getByText("学科类型：CS/AI (DRY)")).toBeInTheDocument();

    await advanceDemoTimers(30_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_4_scaffold_generation")).toBeInTheDocument();
    expect(within(panel).getByText("model.py / train.py / config.yaml / 参数量")).toBeInTheDocument();

    await advanceDemoTimers(15_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_5_quality_check")).toBeInTheDocument();
    expect(within(panel).getByText("语法检查 / 导入测试 / Forward pass / 损失计算")).toBeInTheDocument();
  });

  it("labels step 11 as final report generation", async () => {
    renderDemo();
    await saveCredentials();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 CPU 实例" }));
    await advanceDemoTimers(300_000);
    fireEvent.click(screen.getByRole("button", { name: "确认创建 GPU 实例" }));
    await advanceDemoTimers(30_000);

    const panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("11. 最终报告生成")).toBeInTheDocument();
  });

  it("omits runtime and compute-cost noise from release step outputs", async () => {
    renderDemo();
    await saveCredentials();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 CPU 实例" }));
    await advanceDemoTimers(150_000);

    let panel = screen.getByTestId("zero-code-agent-panel");
    const step8 = within(panel).getByTestId("zero-code-step-row-step_8_release_cpu");
    expect(within(step8).getByText("CPU 实例已释放")).toBeInTheDocument();
    expect(within(step8).queryByText(/示例运行时长/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 GPU 实例" }));
    await advanceDemoTimers(15_000);

    panel = screen.getByTestId("zero-code-agent-panel");
    const step10 = within(panel).getByTestId("zero-code-step-row-step_10_release_gpu");
    expect(within(step10).getByText("GPU 实例释放中")).toBeInTheDocument();
    expect(within(step10).queryByText(/算力消耗/)).not.toBeInTheDocument();
  });

  it("marks the final report step completed after report generation finishes", async () => {
    renderDemo();
    await saveCredentials();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 CPU 实例" }));
    await advanceDemoTimers(150_000);
    fireEvent.click(screen.getByRole("button", { name: "确认创建 GPU 实例" }));

    await advanceDemoTimers(30_000);
    let panel = screen.getByTestId("zero-code-agent-panel");
    let step11 = within(panel).getByTestId("zero-code-step-row-step_11_final_docx_report");
    expect(within(step11).getByText("⏳执行中")).toBeInTheDocument();

    await advanceDemoTimers(10_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    step11 = within(panel).getByTestId("zero-code-step-row-step_11_final_docx_report");
    expect(within(step11).getByText("✅完成")).toBeInTheDocument();
  });

  it("shows the final download guidance after all workflow steps finish", async () => {
    renderDemo();
    await saveCredentials();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 CPU 实例" }));
    await advanceDemoTimers(150_000);
    fireEvent.click(screen.getByRole("button", { name: "确认创建 GPU 实例" }));
    await advanceDemoTimers(40_000);

    const panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).queryByText("流程推进中。")).not.toBeInTheDocument();
    expect(within(panel).getByText("完成论文复现，相关产物以及报告文件可以在工作区下载")).toBeInTheDocument();
    expect(within(panel).queryByText("当前步骤：step_11_final_docx_report")).not.toBeInTheDocument();
  });

  it("auto-reveals early workflow steps at fixed intervals with matching workspace paths", async () => {
    renderDemo();
    await saveCredentials();

    let panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_0_remote_instance_init")).toBeInTheDocument();
    expect(within(panel).queryByText("step_1_paper_acquisition_parse")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 CPU 实例" }));
    await advanceDemoTimers(29_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).queryByText("step_1_paper_acquisition_parse")).not.toBeInTheDocument();

    await advanceDemoTimers(1_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_1_paper_acquisition_parse")).toBeInTheDocument();
    expect(within(panel).queryByText("step_2_domain_routing")).not.toBeInTheDocument();

    await advanceDemoTimers(14_000);
    expect(within(screen.getByTestId("zero-code-agent-panel")).queryByText("step_2_domain_routing")).not.toBeInTheDocument();

    await advanceDemoTimers(1_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_2_domain_routing")).toBeInTheDocument();
    expect(within(panel).getByText("学科类型：CS/AI (DRY)")).toBeInTheDocument();
    expect(within(panel).queryByText(/代码类型/)).not.toBeInTheDocument();
    expect(within(panel).queryByText("step_3_paper_profile")).not.toBeInTheDocument();

    await advanceDemoTimers(14_000);
    expect(within(screen.getByTestId("zero-code-agent-panel")).queryByText("step_3_paper_profile")).not.toBeInTheDocument();

    await advanceDemoTimers(1_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_3_paper_profile")).toBeInTheDocument();
    expect(within(panel).queryByText("step_4_scaffold_generation")).not.toBeInTheDocument();

    await advanceDemoTimers(29_000);
    expect(within(screen.getByTestId("zero-code-agent-panel")).queryByText("step_4_scaffold_generation")).not.toBeInTheDocument();

    await advanceDemoTimers(1_000);
    panel = screen.getByTestId("zero-code-agent-panel");
    expect(within(panel).getByText("step_4_scaffold_generation")).toBeInTheDocument();
    expect(within(panel).getByText("model.py / train.py / config.yaml / 参数量")).toBeInTheDocument();

    await advanceDemoTimers(60_000);
    const rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("code/reproduction_scaffold")).toBeInTheDocument();
    expect(within(rightPanel).getByText("model.py")).toBeInTheDocument();
  });

  it("reveals workspace artifacts in execution order instead of all at once", async () => {
    renderDemo();
    await saveCredentials();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 CPU 实例" }));

    let rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).queryByText("code/reproduction_scaffold")).not.toBeInTheDocument();

    await advanceDemoTimers(90_000);
    rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("code/reproduction_scaffold")).toBeInTheDocument();
    expect(within(rightPanel).getByText("model.py")).toBeInTheDocument();
    expect(within(rightPanel).queryByText("train.py")).not.toBeInTheDocument();
    expect(within(rightPanel).queryByText("CONFIDENCE_REPORT.md")).not.toBeInTheDocument();

    await advanceDemoTimers(5_000);
    rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("train.py")).toBeInTheDocument();
    expect(within(rightPanel).queryByText("config.yaml")).not.toBeInTheDocument();

    await advanceDemoTimers(5_000);
    rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("config.yaml")).toBeInTheDocument();
    expect(within(rightPanel).queryByText("geneclr.py")).not.toBeInTheDocument();

    await advanceDemoTimers(5_000);
    rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("geneclr.py")).toBeInTheDocument();
    expect(within(rightPanel).queryByText("CONFIDENCE_REPORT.md")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("paper_profile.json")).toBeInTheDocument();
    expect(within(rightPanel).queryByText("CONFIDENCE_REPORT.md")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("CONFIDENCE_REPORT.md")).toBeInTheDocument();
    expect(within(rightPanel).queryByText("requirements.txt")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("requirements.txt")).toBeInTheDocument();
    expect(within(rightPanel).queryByText("report.docx")).not.toBeInTheDocument();

    await advanceDemoTimers(15_000);
    fireEvent.click(screen.getByRole("button", { name: "确认创建 GPU 实例" }));
    await advanceDemoTimers(30_000);
    rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getByText("training.log")).toBeInTheDocument();
    expect(within(rightPanel).getByText("report.docx")).toBeInTheDocument();
  });

  it("previews generated markdown files after scaffold generation", async () => {
    renderDemo();
    await saveCredentials();

    fireEvent.click(screen.getByRole("button", { name: "确认创建 CPU 实例" }));
    await advanceDemoTimers(300_000);

    const rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    fireEvent.click(within(rightPanel).getByRole("button", { name: "CONFIDENCE_REPORT.md" }));

    const preview = within(rightPanel).getByTestId("workspace-markdown-preview");
    expect(within(preview).getByText("GeneCLR Zero-Code Reproduction Confidence Report")).toBeInTheDocument();
    fireEvent.click(within(rightPanel).getByRole("button", { name: "返回" }));
    expect(within(rightPanel).getByText("CONFIDENCE_REPORT.md")).toBeInTheDocument();
  });

  it("stops before creating instances when the CPU HITL is rejected", async () => {
    renderDemo();
    await saveCredentials();

    fireEvent.click(screen.getByRole("button", { name: "停止任务" }));

    expect(screen.getByText("演示任务已停止，未创建计费实例。")).toBeInTheDocument();
    const rightPanel = screen.getByTestId("zero-code-demo-right-panel");
    expect(within(rightPanel).getAllByText("未创建计费实例，工作区未生成。").length).toBeGreaterThan(0);
    expect(within(rightPanel).queryByText(/481a8b5e60994cf98ed252ae0518edf0/)).not.toBeInTheDocument();
  });
});

async function saveCredentials() {
  await revealCredentialForm();
  fireEvent.change(screen.getByLabelText("Lab4AI 账号"), { target: { value: "13812348000" } });
  fireEvent.change(screen.getByLabelText("Lab4AI 密码"), { target: { value: "demo-password" } });
  fireEvent.click(screen.getByRole("button", { name: "保存凭证并继续" }));
}

async function revealCredentialForm() {
  await advanceDemoTimers(3200);
}

async function advanceDemoTimers(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
