import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ZeroCodeAgentPanel,
  type PendingUserInput,
  type SkillSelectionState,
  type WorkflowState,
  type WorkflowStepState,
} from "../components/ZeroCodeAgentPanel";
import { MarkdownContent } from "../components/MarkdownContent";

const DEMO_TITLE = "GeneCLR: A Context-Aware Protein Language Model for Defense System Discovery";
const PROJECT_NAME = "geneclr-zero-code";
const CPU_SERVER_ID = "481a8b5e60994cf98ed252ae0518edf0";
const CPU_SSH = "root@182.242.159.112:30043";
const GPU_SERVER_ID = "7f26d6d2f7a94b93b02fd48b1e4c9a65";
const GPU_SSH = "root@182.242.159.118:30817";
const PROJECT_ROOT = `/workspace/user-data/codelab/${PROJECT_NAME}/`;
const SCAFFOLD_DIR = `${PROJECT_ROOT}code/reproduction_scaffold`;
const REPORT_PATH = `${SCAFFOLD_DIR}/CONFIDENCE_REPORT.md`;
const DEMO_HISTORY_KEY = "zero_code_demo_history";

const SKILL_SELECTION_DELAY_MS = 2400;
const CREDENTIAL_FORM_DELAY_MS = 3200;
const EARLY_STEP_REVEAL_SCHEDULE = [
  { delayMs: 30_000, stepIndex: 1 },
  { delayMs: 45_000, stepIndex: 2 },
  { delayMs: 60_000, stepIndex: 3 },
  { delayMs: 90_000, stepIndex: 4 },
  { delayMs: 105_000, stepIndex: 5 },
  { delayMs: 120_000, stepIndex: 6 },
  { delayMs: 135_000, stepIndex: 7 },
  { delayMs: 150_000, stepIndex: 8, completeCpuStage: true },
];
const GPU_STEP_REVEAL_SCHEDULE = [
  { delayMs: 15_000, stepIndex: 10 },
  { delayMs: 30_000, stepIndex: 11 },
];
const FINAL_REPORT_COMPLETE_DELAY_MS = 40_000;
const CPU_READY_WORKSPACE_FILE_COUNT = 9;
const GPU_INITIAL_WORKSPACE_FILE_COUNT = 10;
const GPU_CHECKPOINT_WORKSPACE_FILE_COUNT = 11;
const GPU_FINAL_WORKSPACE_FILE_COUNT = 12;
const WORKSPACE_FILE_REVEAL_SCHEDULE = [
  { delayMs: 60_000, fileCount: 2 },
  { delayMs: 90_000, fileCount: 3 },
  { delayMs: 95_000, fileCount: 4 },
  { delayMs: 100_000, fileCount: 5 },
  { delayMs: 105_000, fileCount: 6 },
  { delayMs: 120_000, fileCount: 7 },
  { delayMs: 125_000, fileCount: 8 },
  { delayMs: 140_000, fileCount: CPU_READY_WORKSPACE_FILE_COUNT },
];
const GPU_WORKSPACE_FILE_REVEAL_SCHEDULE = [
  { delayMs: 15_000, fileCount: GPU_CHECKPOINT_WORKSPACE_FILE_COUNT },
  { delayMs: 30_000, fileCount: GPU_FINAL_WORKSPACE_FILE_COUNT },
];
const ROUTED_DOMAIN = "CS/AI (DRY)";
const ROUTED_DOMAIN_OUTPUTS: Record<string, { step4: string; step5: string }> = {
  "CS/AI (DRY)": {
    step4: "model.py / train.py / config.yaml / 参数量",
    step5: "语法检查 / 导入测试 / Forward pass / 损失计算",
  },
  "CS_SYSTEMS (DRY)": {
    step4: "model.py / train.py / config.yaml / 参数量",
    step5: "语法检查 / 导入测试 / Forward pass / 损失计算",
  },
  "BIOINFO (DRY)": {
    step4: "pipeline.sh / analysis.R / 环境脚本",
    step5: "脚本语法 / 干跑测试 / 依赖检查",
  },
  "ECON_QUANT (DRY)": {
    step4: "regression.do / clean.py / 变量字典",
    step5: "语法检查 / 数据格式匹配 / 变量覆盖率",
  },
  "BIOMED_WET (WET)": {
    step4: "SOP_checklist.md / reagent_list / 时间线",
    step5: "完整性检查 / 步骤覆盖率 / 安全提示",
  },
  "CHEM_MAT (DRY/HYBRID)": {
    step4: "结构数据 JSON / 计算脚本",
    step5: "数据格式验证 / 字段完整性",
  },
  HYBRID: {
    step4: "干部分 + 湿部分各自产物",
    step5: "分别验证",
  },
};

type DemoStage =
  | "credential_required"
  | "cpu_confirm"
  | "cpu_running"
  | "scaffold_ready"
  | "gpu_confirm"
  | "gpu_running"
  | "completed"
  | "stopped";

type AgentRevealStage = "thinking" | "skill_selected" | "credential_form";

interface DemoWorkspaceFile {
  path: string;
  name: string;
  kind: "file" | "directory";
  size?: number;
  modifiedAt?: string;
  content?: string;
}

interface DemoInstance {
  label: string;
  serverId: string;
  status: string;
  spec: string;
  username: string;
  sshCommand: string;
}

const ZERO_CODE_STEPS: WorkflowStepState[] = [
  step("step_0_remote_instance_init", "0. 远程实例初始化", "环境", "远程", "实例ID / SSH信息 / 目录结构"),
  step("step_1_paper_acquisition_parse", "1. 论文获取与解析", "输入", "远程", "页数 / 字符数 / 章节数"),
  step("step_2_domain_routing", "2. 学科方向判定", "路由", "本地LLM→远程存储", "学科 / 实验类型 / 激活插件"),
  step("step_3_paper_profile", "3. 论文要素提取", "解析", "本地LLM→远程存储", "Paper Profile (公式/超参/数据集/基线)"),
  step("step_4_scaffold_generation", "4. 复现产物生成", "生成", "本地LLM→远程存储", "脚手架与报告草稿"),
  step("step_5_quality_check", "5. 产物质量检查", "验证", "远程", "导入测试 / dry-run"),
  step("step_6_package_report", "6. 打包与报告", "交付", "本地LLM→远程存储", "CONFIDENCE_REPORT / README"),
  step("step_7_env_data_weights", "7. 环境+数据+权重准备", "准备", "远程 CPU", "requirements.txt / 模型权重 / 数据集"),
  step("step_8_release_cpu", "8. 释放 CPU 实例", "释放", "远程", "CPU 实例关闭 / 算力消耗"),
  step("step_9_gpu_validation_training", "9. GPU 轻量验证训练", "训练", "远程 GPU", "训练日志 / loss下降 / checkpoint"),
  step("step_10_release_gpu", "10. 释放 GPU 实例", "释放", "远程", "GPU 实例关闭 / 算力消耗"),
  step("step_11_final_docx_report", "11. 最终报告生成", "报告", "本地", ".docx 复现报告"),
];

const SKILL_SELECTION: SkillSelectionState = {
  selected_skill: "zero-code-reproduction",
  source: "fallback",
  fallback_choice: "zero-code-reproduction",
  reason: "Paper-only reproduction without a GitHub repository.",
};

export default function ZeroCodeBoardDemoPage() {
  const [params] = useSearchParams();
  const paperUrl = params.get("paper_url") || "https://arxiv.org/pdf/2502.14397";
  const prompt = params.get("prompt") || "复现这篇论文，但没有代码仓库";
  const originalInput = params.get("original_input") || `${prompt}：${paperUrl}`;
  const [stage, setStage] = useState<DemoStage>("credential_required");
  const [agentRevealStage, setAgentRevealStage] = useState<AgentRevealStage>("thinking");
  const [credentialMask, setCredentialMask] = useState<string | null>(null);
  const [visibleWorkflowStepIndex, setVisibleWorkflowStepIndex] = useState(0);
  const [visibleGpuWorkflowStepIndex, setVisibleGpuWorkflowStepIndex] = useState(9);
  const [visibleWorkspaceFileCount, setVisibleWorkspaceFileCount] = useState(0);
  const latestContentRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const timers = [
      window.setTimeout(() => setAgentRevealStage("skill_selected"), SKILL_SELECTION_DELAY_MS),
      window.setTimeout(() => setAgentRevealStage("credential_form"), CREDENTIAL_FORM_DELAY_MS),
    ];
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    localStorage.setItem(
      DEMO_HISTORY_KEY,
      JSON.stringify({
        title: "GeneCLR 纯论文复现演示",
        status: stage === "stopped" ? "stopped" : "running",
        href: `/paper-only/demo/zero-code-board?paper_url=${encodeURIComponent(paperUrl)}&prompt=${encodeURIComponent(
          prompt
        )}&original_input=${encodeURIComponent(originalInput)}`,
      })
    );
    window.dispatchEvent(new Event("zero-code-demo-history"));
  }, [originalInput, paperUrl, prompt, stage]);

  useEffect(() => {
    latestContentRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [agentRevealStage, stage, visibleWorkflowStepIndex, visibleGpuWorkflowStepIndex]);

  useEffect(() => {
    if (stage !== "cpu_running") return;
    const timers = EARLY_STEP_REVEAL_SCHEDULE.map(({ delayMs, stepIndex, completeCpuStage }) =>
      window.setTimeout(() => {
        setVisibleWorkflowStepIndex(stepIndex);
        if (completeCpuStage) {
          setVisibleWorkspaceFileCount(CPU_READY_WORKSPACE_FILE_COUNT);
          setStage("scaffold_ready");
        }
      }, delayMs)
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [stage]);

  useEffect(() => {
    if (stage !== "cpu_running") return;
    const timers = WORKSPACE_FILE_REVEAL_SCHEDULE.map(({ delayMs, fileCount }) =>
      window.setTimeout(() => setVisibleWorkspaceFileCount(fileCount), delayMs)
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [stage]);

  useEffect(() => {
    if (stage !== "gpu_running") return;
    const timers = GPU_STEP_REVEAL_SCHEDULE.map(({ delayMs, stepIndex }) =>
      window.setTimeout(() => setVisibleGpuWorkflowStepIndex(stepIndex), delayMs)
    );
    timers.push(window.setTimeout(() => setStage("completed"), FINAL_REPORT_COMPLETE_DELAY_MS));
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [stage]);

  useEffect(() => {
    if (stage !== "gpu_running") return;
    const timers = GPU_WORKSPACE_FILE_REVEAL_SCHEDULE.map(({ delayMs, fileCount }) =>
      window.setTimeout(() => setVisibleWorkspaceFileCount(fileCount), delayMs)
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [stage]);

  const workflow = useMemo(
    () => workflowForStage(stage, paperUrl, visibleWorkflowStepIndex, visibleGpuWorkflowStepIndex),
    [paperUrl, stage, visibleGpuWorkflowStepIndex, visibleWorkflowStepIndex]
  );
  const pendingInput = useMemo(() => pendingInputForStage(stage), [stage]);
  const showSkillSelection = agentRevealStage === "skill_selected" || agentRevealStage === "credential_form" || stage !== "credential_required";
  const showCredentialForm = agentRevealStage === "credential_form" && stage === "credential_required";

  async function handlePanelSubmit(answer: string) {
    if (/停止|取消/.test(answer)) {
      setVisibleWorkflowStepIndex(0);
      setVisibleGpuWorkflowStepIndex(9);
      setVisibleWorkspaceFileCount(0);
      setStage("stopped");
      return;
    }
    if (stage === "cpu_confirm" && /创建|确认|CPU/.test(answer)) {
      setVisibleWorkflowStepIndex(0);
      setVisibleGpuWorkflowStepIndex(9);
      setVisibleWorkspaceFileCount(0);
      setStage("cpu_running");
      return;
    }
    if (stage === "gpu_confirm" && /创建|确认|GPU/.test(answer)) {
      setVisibleGpuWorkflowStepIndex(9);
      setVisibleWorkspaceFileCount(GPU_INITIAL_WORKSPACE_FILE_COUNT);
      setStage("gpu_running");
    }
  }

  function handleCredentialSubmit(maskedPhone: string) {
    setCredentialMask(maskedPhone);
    setAgentRevealStage("credential_form");
    setVisibleWorkflowStepIndex(0);
    setVisibleGpuWorkflowStepIndex(9);
    setVisibleWorkspaceFileCount(0);
    setStage("cpu_confirm");
  }

  function handleAdvanceStage(nextStage: DemoStage) {
    if (nextStage === "gpu_running") {
      setVisibleGpuWorkflowStepIndex(9);
      setVisibleWorkspaceFileCount(GPU_INITIAL_WORKSPACE_FILE_COUNT);
    }
    setStage(nextStage);
  }

  return (
    <div className="flex-1 overflow-hidden">
      <div className="grid h-full grid-cols-1 gap-4 overflow-hidden xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-h-0 flex-col overflow-hidden">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 lg:px-6 lg:py-6">
            <div className="mx-auto flex max-w-[1100px] flex-col gap-5 pr-0 xl:pr-1">
            <div className="flex justify-end">
              <div className="max-w-3xl whitespace-pre-wrap rounded-2xl bg-slate-800 px-4 py-3 text-chat-body leading-relaxed text-white shadow-sm">
                {originalInput}
              </div>
            </div>

            <AgentMessage>
              {agentRevealStage === "thinking" && stage === "credential_required" && <AgentThinkingCard />}
              {showSkillSelection && <SkillSelectionCard paperUrl={paperUrl} />}
              {showCredentialForm && (
                <CredentialRequestCard onSubmit={handleCredentialSubmit} />
              )}
              {stage !== "credential_required" && (
                <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-chat-body leading-relaxed text-slate-700 shadow-sm">
                  <p>凭证已保存，开始加载 zero-code-reproduction workflow。</p>
                  <p className="mt-1">需要创建远程 CPU 实例解析论文和生成脚手架。</p>
                </div>
              )}
              {stage !== "credential_required" && (
                <ZeroCodeAgentPanel
                  workflow={workflow}
                  pendingInput={pendingInput}
                  onSubmit={handlePanelSubmit}
                  skillSelection={SKILL_SELECTION}
                  workflowPath="skills/zero-code-reproduction/SKILL.md"
                  showExecutionLocation={false}
                  showGateLog={false}
                />
              )}
            </AgentMessage>
            <DemoAdvanceControls stage={stage} onAdvance={handleAdvanceStage} />
            <div ref={latestContentRef} aria-hidden="true" />
            </div>
          </div>
          <FollowUpChatBox />
        </div>
        <div className="h-full min-h-0 py-4 pr-4 lg:py-6 lg:pr-6">
          <ZeroCodeDemoRightPanel
            stage={stage}
            credentialMask={credentialMask}
            visibleWorkspaceFileCount={visibleWorkspaceFileCount}
          />
        </div>
      </div>
    </div>
  );
}

function FollowUpChatBox() {
  return (
    <div data-testid="zero-code-follow-up-bar" className="shrink-0 border-t border-slate-100 bg-white p-3">
      <form data-testid="zero-code-follow-up-form" className="w-full">
        <div
          data-testid="zero-code-follow-up-input-shell"
          className="flex w-full items-end gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 transition-colors focus-within:border-slate-300 focus-within:bg-white"
        >
          <label className="sr-only" htmlFor="zero-code-follow-up-input">
            继续输入任务需求
          </label>
          <textarea
            id="zero-code-follow-up-input"
            aria-label="继续输入任务需求"
            disabled
            placeholder="继续输入你的问题或调整要求..."
            rows={1}
            className="flex-1 resize-none bg-transparent text-chat-body leading-relaxed text-slate-700 placeholder-slate-300 disabled:opacity-50"
          />
          <button
            type="button"
            aria-label="发送消息"
            disabled
            className="flex h-[32px] w-[32px] shrink-0 items-center justify-center rounded-full bg-slate-800 text-white transition-colors hover:bg-slate-700 disabled:bg-slate-300"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </button>
        </div>
      </form>
    </div>
  );
}

function AgentMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-4" data-testid="agent-message">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-800 text-ui-small font-semibold text-white">
        A
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">AutoResearch24</div>
        {children}
      </div>
    </div>
  );
}

function AgentThinkingCard() {
  return (
    <div className="inline-flex max-w-xl items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-chat-body text-slate-600 shadow-sm">
      <span className="flex gap-1" aria-hidden="true">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400 [animation-delay:160ms]" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400 [animation-delay:320ms]" />
      </span>
      <span>正在读取论文地址并判断复现入口...</span>
    </div>
  );
}

function SkillSelectionCard({ paperUrl }: { paperUrl: string }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white px-4 py-4 shadow-sm">
      <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">Agent Routing</div>
      <div className="mt-3 space-y-2 text-chat-body leading-relaxed text-slate-700">
        <p>未检测到 GitHub 仓库，进入纯论文复现路径。</p>
        <p>论文地址：{paperUrl}</p>
        <p>选择 skill：zero-code-reproduction</p>
        <p>候选插件：zero-code-repro-csai / zero-code-repro-biodefense</p>
        <p>请先配置 Lab4AI 平台凭证，后续实例创建会进入 HITL 确认。</p>
      </div>
    </section>
  );
}

function CredentialRequestCard({ onSubmit }: { onSubmit: (maskedPhone: string) => void }) {
  const [phone, setPhone] = useState("13812348000");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!phone.trim() || !password.trim()) {
      setError("请填写 Lab4AI 平台账号和密码。");
      return;
    }
    onSubmit(maskPhone(phone));
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-ui-meta font-bold uppercase text-amber-700">等待你确认</div>
          <div className="mt-1 text-ui-small font-semibold text-amber-900">配置 Lab4AI 平台凭证</div>
        </div>
        <span className="rounded-full border border-amber-200 bg-white px-2 py-0.5 text-ui-micro font-medium text-amber-700">
          Credential
        </span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-ui-small text-slate-700">
          Lab4AI 账号
          <input
            aria-label="Lab4AI 账号"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            className="mt-1 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-ui-small text-slate-700"
          />
        </label>
        <label className="text-ui-small text-slate-700">
          Lab4AI 密码
          <input
            aria-label="Lab4AI 密码"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-1 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-ui-small text-slate-700"
          />
        </label>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="text-ui-micro text-amber-700">页面只记录脱敏账号，不展示密码明文。</p>
        <button
          type="submit"
          className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-ui-small font-medium text-slate-700 hover:bg-amber-100"
        >
          保存凭证并继续
        </button>
      </div>
      {error && <p className="mt-2 text-ui-small text-red-600">{error}</p>}
    </form>
  );
}

function DemoAdvanceControls({
  stage,
  onAdvance,
}: {
  stage: DemoStage;
  onAdvance: (stage: DemoStage) => void;
}) {
  if (stage === "cpu_running") {
    return null;
  }
  if (stage === "scaffold_ready") {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-4">
        <div className="text-ui-meta font-bold uppercase text-amber-700">实验确认点</div>
        <div className="mt-1 text-chat-body text-slate-700">CPU 阶段完成，下一步需要创建 GPU 实例做轻量验证。</div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={() => onAdvance("gpu_running")} className={advanceButtonClass}>
            确认创建 GPU 实例
          </button>
        </div>
      </div>
    );
  }
  return null;
}

const advanceButtonClass =
  "rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-ui-small font-medium text-slate-700 shadow-sm hover:bg-slate-50";

function ZeroCodeDemoRightPanel({
  stage,
  credentialMask,
  visibleWorkspaceFileCount,
}: {
  stage: DemoStage;
  credentialMask: string | null;
  visibleWorkspaceFileCount: number;
}) {
  return (
    <aside
      data-testid="zero-code-demo-right-panel"
      className="flex h-full min-h-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
        <section className="flex min-h-0 flex-1 basis-0 flex-col overflow-hidden border-b border-slate-200">
          <PanelHeader title="权限与环境配置" subtitle={rightPanelStatus(stage)} />
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            <div className="space-y-4">
              <Lab4AICredentialBlock credentialMask={credentialMask} />
              <div>
                <SectionTitle label="Lab4AI 实例" />
                {demoInstancesForStage(stage).length > 0 ? (
                  <div className="space-y-3">
                    {demoInstancesForStage(stage).map((instance) => (
                      <InstanceBlock key={instance.serverId} instance={instance} />
                    ))}
                  </div>
                ) : stage === "stopped" ? (
                  <EmptyPanelText
                    text="未创建计费实例，工作区未生成。"
                  />
                ) : null}
              </div>
            </div>
          </div>
        </section>
        <section className="flex min-h-0 flex-1 basis-0 flex-col overflow-hidden">
          <WorkspacePanel stage={stage} visibleWorkspaceFileCount={visibleWorkspaceFileCount} />
        </section>
      </div>
    </aside>
  );
}

function Lab4AICredentialBlock({ credentialMask }: { credentialMask: string | null }) {
  const configured = !!credentialMask;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-ui-small font-semibold text-slate-800">Lab4AI 登录凭证</div>
          <div className="mt-0.5 text-ui-micro text-slate-400">平台统一账号，仅展示脱敏信息</div>
        </div>
        <span
          className={`shrink-0 rounded-md border px-2 py-0.5 text-ui-micro font-medium ${
            configured
              ? "border-emerald-100 bg-emerald-50 text-emerald-700"
              : "border-amber-100 bg-amber-50 text-amber-700"
          }`}
        >
          {configured ? "已配置" : "未配置"}
        </span>
      </div>
      {configured ? (
        <div className="space-y-2">
          <CredentialRow label="账号" value={credentialMask} />
          <CredentialRow label="密码" value="已安全保存" />
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-ui-small text-slate-500">
          Lab4AI 凭证未配置，等待用户输入。
        </div>
      )}
    </div>
  );
}

function WorkspacePanel({
  stage,
  visibleWorkspaceFileCount,
}: {
  stage: DemoStage;
  visibleWorkspaceFileCount: number;
}) {
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const previewFile = demoWorkspaceFiles().find((file) => file.path === previewPath);
  const files = demoWorkspaceFilesForStage(stage, visibleWorkspaceFileCount);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelHeader title="工作区文件" subtitle={files.length > 0 ? PROJECT_ROOT : "未创建"} />
      {files.length === 0 ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <EmptyPanelText
            text={stage === "stopped" ? "未创建计费实例，工作区未生成。" : "工作区待创建，确认后会展示生成文件。"}
          />
        </div>
      ) : previewPath ? (
        <WorkspacePreview file={previewFile} fallbackPath={previewPath} onBack={() => setPreviewPath(null)} />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="border-b border-slate-100 px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-ui-small font-semibold text-slate-800">Workspace Artifacts</div>
                <div className="mt-0.5 break-all text-ui-micro text-slate-400">{PROJECT_ROOT}</div>
              </div>
              <span className="shrink-0 rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-ui-micro font-medium text-slate-500">
                {files.length} 项
              </span>
            </div>
          </div>
          <div className="py-2">
            {files.map((file) => (
              <DemoFileRow key={file.path} file={file} onPreview={setPreviewPath} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function WorkspacePreview({
  file,
  fallbackPath,
  onBack,
}: {
  file?: DemoWorkspaceFile;
  fallbackPath: string;
  onBack: () => void;
}) {
  return (
    <div data-testid="workspace-markdown-preview" className="flex min-h-0 flex-1 flex-col bg-slate-50/50">
      <div className="shrink-0 border-b border-slate-200 bg-white px-4 py-3">
        <button type="button" onClick={onBack} className="mb-3 rounded-md border border-slate-200 bg-white px-2 py-1 text-ui-micro font-medium text-slate-600 hover:bg-slate-50">
          返回
        </button>
        <div className="min-w-0">
          <span className="rounded-md border border-blue-100 bg-blue-50 px-2 py-0.5 text-ui-micro font-semibold text-blue-700">
            Markdown 预览
          </span>
          <div className="mt-2 truncate text-ui-small font-semibold text-slate-800">
            {file?.name || fileNameFromPath(fallbackPath)}
          </div>
          <div className="mt-0.5 break-all text-ui-micro text-slate-400">{fallbackPath}</div>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <article className="rounded-lg border border-slate-200 bg-white px-4 py-4 shadow-sm">
          <MarkdownContent content={file?.content || ""} variant="workspace" />
        </article>
      </div>
    </div>
  );
}

function InstanceBlock({ instance }: { instance: DemoInstance }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="break-all text-ui-small font-semibold text-slate-800">
            {instance.label} · {instance.serverId}
          </div>
          <div className="mt-0.5 text-ui-micro text-slate-400">{instance.spec}</div>
        </div>
        <span className="shrink-0 rounded-md border border-emerald-100 bg-emerald-50 px-2 py-0.5 text-ui-micro font-medium text-emerald-700">
          {instance.status}
        </span>
      </div>
      <div className="space-y-2">
        <CredentialRow label="用户名" value={instance.username} />
        <CredentialRow label="SSH 命令" value={instance.sshCommand} />
      </div>
    </div>
  );
}

function DemoFileRow({ file, onPreview }: { file: DemoWorkspaceFile; onPreview: (path: string) => void }) {
  const isMarkdown = file.kind === "file" && file.name.endsWith(".md");
  const content = (
    <>
      <FileIcon kind={file.kind} markdown={isMarkdown} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <div className="truncate font-medium text-slate-700">{file.name}</div>
          {isMarkdown && (
            <span className="shrink-0 rounded-md border border-blue-100 bg-blue-50 px-1.5 py-0.5 text-ui-micro font-semibold text-blue-700">
              MD
            </span>
          )}
        </div>
        {file.kind === "file" && (
          <div className="mt-0.5 text-ui-micro text-slate-400">
            {formatSize(file.size || 0)}
            {file.modifiedAt ? ` · ${file.modifiedAt}` : ""}
          </div>
        )}
      </div>
      {file.kind === "file" && !isMarkdown && (
        <button type="button" className="shrink-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-ui-micro font-medium text-slate-500" onClick={(event) => event.stopPropagation()}>
          下载
        </button>
      )}
    </>
  );
  const className = "group flex w-full items-center gap-2 px-4 py-2.5 text-left text-ui-meta hover:bg-slate-50";
  if (isMarkdown) {
    return (
      <button type="button" aria-label={file.name} onClick={() => onPreview(file.path)} className={className} title={file.path}>
        {content}
      </button>
    );
  }
  return (
    <div className={className} title={file.path}>
      {content}
    </div>
  );
}

function workflowForStage(
  stage: DemoStage,
  paperUrl: string,
  visibleWorkflowStepIndex: number,
  visibleGpuWorkflowStepIndex: number
): WorkflowState {
  if (stage === "stopped") return stoppedWorkflow();
  if (stage === "cpu_confirm") return workflowFromVisibleSteps([visibleStep(0, "waiting_for_user")], "step_0_remote_instance_init", "waiting_for_user", paperUrl);
  if (stage === "cpu_running") {
    return workflowFromVisibleSteps(
      earlyWorkflowSteps(visibleWorkflowStepIndex, false),
      ZERO_CODE_STEPS[Math.max(0, visibleWorkflowStepIndex)].id,
      "running",
      paperUrl
    );
  }
  if (stage === "scaffold_ready" || stage === "gpu_confirm") {
    return workflowFromVisibleSteps(
      earlyWorkflowSteps(8, true),
      "step_8_release_cpu",
      "waiting_for_user",
      paperUrl
    );
  }
  if (stage === "completed") {
    return workflowFromVisibleSteps(
      [...earlyWorkflowSteps(8, true), visibleStep(9, "completed", true), visibleStep(10, "completed"), visibleStep(11, "completed")],
      "step_11_final_docx_report",
      "completed",
      paperUrl
    );
  }
  if (stage === "gpu_running") {
    return workflowFromVisibleSteps(
      [
        visibleStep(0, "completed"),
        visibleStep(1, "completed"),
        visibleStep(2, "completed"),
        visibleStep(3, "completed"),
        visibleStep(4, "completed"),
        visibleStep(5, "completed"),
        visibleStep(6, "completed"),
        visibleStep(7, "completed"),
        visibleStep(8, "completed"),
        ...gpuWorkflowSteps(visibleGpuWorkflowStepIndex),
      ],
      ZERO_CODE_STEPS[Math.min(Math.max(visibleGpuWorkflowStepIndex, 9), 11)].id,
      "running",
      paperUrl
    );
  }
  return workflowFromVisibleSteps([visibleStep(0, "waiting_for_user")], "step_0_remote_instance_init", "waiting_for_user", paperUrl);
}

function earlyWorkflowSteps(currentIndex: number, completed: boolean) {
  const cappedIndex = Math.min(Math.max(currentIndex, 0), 8);
  return Array.from({ length: cappedIndex + 1 }, (_, index) =>
    visibleStep(index, completed || index < cappedIndex ? "completed" : index === 0 ? "running" : "running")
  );
}

function gpuWorkflowSteps(currentIndex: number) {
  const cappedIndex = Math.min(Math.max(currentIndex, 9), 11);
  return Array.from({ length: cappedIndex - 8 }, (_, offset) => {
    const index = offset + 9;
    return visibleStep(index, index < cappedIndex ? "completed" : "running", index === 9);
  });
}

function visibleStep(index: number, status: string, includeGpu = false) {
  return { index, status, includeGpu };
}

function workflowFromVisibleSteps(
  visibleSteps: Array<{ index: number; status: string; includeGpu?: boolean }>,
  currentStepId: string,
  currentStatus: string,
  paperUrl: string
): WorkflowState {
  return {
    kind: "zero_code_reproduction_pipeline",
    name: "zero_code_reproduction_pipeline",
    version: "1.0",
    project_name: PROJECT_NAME,
    current_step_id: currentStepId,
    status: currentStatus,
    gate_log: { next_action: workflowNextAction(currentStepId, currentStatus) },
    results: {
      paper_title: DEMO_TITLE,
      paper_url: paperUrl,
      project_name: PROJECT_NAME,
      cpu_server_id: CPU_SERVER_ID,
      cpu_ssh: CPU_SSH,
      gpu_server_id: GPU_SERVER_ID,
      gpu_ssh: GPU_SSH,
      scaffold_dir: SCAFFOLD_DIR,
      markdown_report_path: REPORT_PATH,
    },
    steps: visibleSteps.map(({ index, status, includeGpu }) => {
      const item = ZERO_CODE_STEPS[index];
      if (status === "completed") return completedStep(item);
      if (status === currentStatus) {
        return {
          ...item,
          status,
          expected_output: runningStepOutput(item, includeGpu),
        };
      }
      return { ...item, status };
    }),
  };
}

function runningStepOutput(item: WorkflowStepState, includeGpu = false) {
  if (includeGpu) return `H100 轻量验证训练进行中；GPU serverId：${GPU_SERVER_ID}；SSH：${GPU_SSH}`;
  if (item.id === "step_2_domain_routing") return `学科类型：${ROUTED_DOMAIN}`;
  if (item.id === "step_10_release_gpu") return "GPU 实例释放中";
  const routedOutput = routedStepOutput(item.id);
  if (routedOutput) return routedOutput;
  return item.expected_output;
}

function workflowNextAction(currentStepId: string, currentStatus: string) {
  if (currentStepId === "step_0_remote_instance_init" && currentStatus === "waiting_for_user") {
    return "等待 CPU 实例创建确认。";
  }
  if (currentStepId === "step_1_paper_acquisition_parse") {
    return "正在解析论文 PDF 和补充材料。";
  }
  if (currentStepId === "step_9_gpu_validation_training" && currentStatus === "waiting_for_user") {
    return "等待 GPU 实例创建确认。";
  }
  if (currentStepId === "step_9_gpu_validation_training") {
    return "GPU 轻量验证训练进行中。";
  }
  if (currentStatus === "stopped") {
    return "演示任务已停止，未创建计费实例。";
  }
  return "流程推进中。";
}

function pendingInputForStage(stage: DemoStage): PendingUserInput | null {
  if (stage === "cpu_confirm") {
    return {
      question: "确认创建 CPU 实例用于论文解析和脚手架生成？",
      options: ["确认创建 CPU 实例", "停止任务"],
      tool_name: "lab4ai_create_instance",
      workflow_step_id: "step_0_remote_instance_init",
    };
  }
  if (stage === "gpu_confirm") {
    return {
      question: "确认创建 GPU 实例进行轻量验证训练？",
      options: ["确认创建 GPU 实例", "停止任务"],
      tool_name: "lab4ai_create_instance",
      workflow_step_id: "step_9_gpu_validation_training",
    };
  }
  return null;
}

function stoppedWorkflow(): WorkflowState {
  return {
    ...workflowFromVisibleSteps([visibleStep(0, "skipped")], "step_0_remote_instance_init", "stopped", ""),
    status: "stopped",
    gate_log: { next_action: "演示任务已停止，未创建计费实例。" },
  };
}

function completedStep(item: WorkflowStepState): WorkflowStepState {
  const outputs: Record<string, { expected_output: string; evidence?: Record<string, unknown> }> = {
    step_0_remote_instance_init: {
      expected_output: `CPU serverId：${CPU_SERVER_ID}；SSH：${CPU_SSH}；目录：${PROJECT_ROOT}`,
      evidence: { cpu_server_id: CPU_SERVER_ID, cpu_ssh: CPU_SSH, project_root: PROJECT_ROOT },
    },
    step_1_paper_acquisition_parse: { expected_output: "论文 PDF 解析完成；章节 9 个；补充材料已索引" },
    step_2_domain_routing: {
      expected_output: `学科类型：${ROUTED_DOMAIN}`,
    },
    step_3_paper_profile: { expected_output: "Paper Profile：公式 8 个 / 超参数 23 个 / 数据集 4 个 / 基线 6 个" },
    step_4_scaffold_generation: { expected_output: routedStepOutput("step_4_scaffold_generation") },
    step_5_quality_check: { expected_output: routedStepOutput("step_5_quality_check") },
    step_6_package_report: { expected_output: `CONFIDENCE_REPORT.md / README.md；报告：${REPORT_PATH}` },
    step_7_env_data_weights: { expected_output: "requirements.txt / ESM2 权重 / DefenseFinder 示例数据已准备" },
    step_8_release_cpu: { expected_output: "CPU 实例已释放" },
    step_10_release_gpu: { expected_output: "GPU 实例已释放" },
    step_11_final_docx_report: { expected_output: "report.docx 复现报告" },
  };
  const output = outputs[item.id] || { expected_output: item.expected_output || "-" };
  return { ...item, status: "completed", expected_output: output.expected_output, evidence: output.evidence };
}

function routedStepOutput(stepId: string) {
  const outputs = ROUTED_DOMAIN_OUTPUTS[ROUTED_DOMAIN];
  if (stepId === "step_4_scaffold_generation") return outputs.step4;
  if (stepId === "step_5_quality_check") return outputs.step5;
  return "";
}

function demoInstancesForStage(stage: DemoStage): DemoInstance[] {
  if (["credential_required", "cpu_confirm", "stopped"].includes(stage)) return [];
  const instances: DemoInstance[] = [
    {
      label: "CPU",
      serverId: CPU_SERVER_ID,
      status: ["scaffold_ready", "gpu_confirm", "gpu_running", "completed"].includes(stage) ? "已释放" : "运行中",
      spec: "2C CPU / 8GB RAM",
      username: "root",
      sshCommand: CPU_SSH,
    },
  ];
  if (["gpu_running", "completed"].includes(stage)) {
    instances.push({
      label: "GPU",
      serverId: GPU_SERVER_ID,
      status: stage === "completed" ? "已释放" : "运行中",
      spec: "1x H100 / 80GB VRAM",
      username: "root",
      sshCommand: GPU_SSH,
    });
  }
  return instances;
}

function demoWorkspaceFilesForStage(stage: DemoStage, visibleWorkspaceFileCount: number): DemoWorkspaceFile[] {
  if (["credential_required", "cpu_confirm", "stopped"].includes(stage)) return [];
  if (["scaffold_ready", "gpu_confirm"].includes(stage)) return demoWorkspaceFiles().slice(0, CPU_READY_WORKSPACE_FILE_COUNT);
  if (stage === "completed") return demoWorkspaceFiles().slice(0, GPU_FINAL_WORKSPACE_FILE_COUNT);
  if (stage === "gpu_running") return demoWorkspaceFiles().slice(0, visibleWorkspaceFileCount);
  return demoWorkspaceFiles().slice(0, visibleWorkspaceFileCount);
}

function demoWorkspaceFiles(): DemoWorkspaceFile[] {
  return [
    { path: "code/reproduction_scaffold", name: "code/reproduction_scaffold", kind: "directory" },
    { path: "code/reproduction_scaffold/paper_profile.json", name: "paper_profile.json", kind: "file", size: 18700, modifiedAt: "05-25 20:09" },
    { path: "code/reproduction_scaffold/model.py", name: "model.py", kind: "file", size: 15100, modifiedAt: "05-25 20:14" },
    { path: "code/reproduction_scaffold/train.py", name: "train.py", kind: "file", size: 16800, modifiedAt: "05-25 20:15" },
    { path: "code/reproduction_scaffold/config.yaml", name: "config.yaml", kind: "file", size: 1900, modifiedAt: "05-25 20:15" },
    { path: "code/reproduction_scaffold/models/geneclr.py", name: "geneclr.py", kind: "file", size: 14200, modifiedAt: "05-25 20:14" },
    { path: "code/reproduction_scaffold/README.md", name: "README.md", kind: "file", size: 8200, modifiedAt: "05-25 20:12", content: "# GeneCLR Reproduction Scaffold\n\nGenerated scaffold for paper-only reproduction." },
    {
      path: "code/reproduction_scaffold/CONFIDENCE_REPORT.md",
      name: "CONFIDENCE_REPORT.md",
      kind: "file",
      size: 12400,
      modifiedAt: "05-25 20:17",
      content:
        "# GeneCLR Zero-Code Reproduction Confidence Report\n\n- Active plugins: `zero-code-reproduction`, `zero-code-repro-csai`, `zero-code-repro-biodefense`\n- CPU serverId: `481a8b5e60994cf98ed252ae0518edf0`\n- GPU serverId: `7f26d6d2f7a94b93b02fd48b1e4c9a65`\n\n## Deliverables\n\n- Paper profile JSON\n- PyTorch model scaffold\n- Final `report.docx`",
    },
    { path: "code/reproduction_scaffold/requirements.txt", name: "requirements.txt", kind: "file", size: 2400, modifiedAt: "05-25 20:17" },
    { path: "code/reproduction_scaffold/training/finetune_geneclr.py", name: "finetune_geneclr.py", kind: "file", size: 16100, modifiedAt: "05-25 20:16" },
    { path: "code/reproduction_scaffold/runs/gpu_validation/training.log", name: "training.log", kind: "file", size: 7800, modifiedAt: "05-25 20:31" },
    { path: "code/reproduction_scaffold/report.docx", name: "report.docx", kind: "file", size: 286000, modifiedAt: "05-25 20:33" },
  ];
}

function rightPanelStatus(stage: DemoStage) {
  if (stage === "credential_required") return "等待凭证";
  if (stage === "cpu_confirm") return "等待确认";
  if (stage === "cpu_running") return "CPU 运行中";
  if (stage === "scaffold_ready") return "脚手架生成";
  if (stage === "gpu_confirm") return "等待确认";
  if (stage === "gpu_running") return "GPU 验证";
  if (stage === "completed") return "已完成";
  return "已停止";
}

function maskPhone(phone: string) {
  const digits = phone.replace(/\D/g, "");
  if (digits.length < 8) return phone;
  return `${digits.slice(0, 3)}****${digits.slice(-4)}`;
}

function fileNameFromPath(path: string) {
  return path.split("/").pop() || path;
}

function formatSize(size: number) {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

function step(
  id: string,
  name: string,
  phase: string,
  executionLocation: string,
  expectedOutput: string
): WorkflowStepState {
  return { id, name, phase, execution_location: executionLocation, expected_output: expectedOutput, status: "pending" };
}

function PanelHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="shrink-0 border-b border-slate-100 bg-slate-50/70 px-5 py-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-ui-title font-semibold text-slate-800">{title}</h3>
        <span className="truncate text-ui-micro uppercase tracking-wide text-slate-400">{subtitle}</span>
      </div>
    </div>
  );
}

function SectionTitle({ label }: { label: string }) {
  return <div className="mb-2 text-ui-meta font-semibold uppercase tracking-wide text-slate-400">{label}</div>;
}

function CredentialRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-3 text-ui-small">
      <span className="text-slate-400">{label}</span>
      <span className="min-w-0 break-all font-mono text-slate-700">{value}</span>
    </div>
  );
}

function EmptyPanelText({ text }: { text: string }) {
  return (
    <div className="flex min-h-[120px] items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center text-ui-small leading-relaxed text-slate-500">
      {text}
    </div>
  );
}

function FileIcon({ kind, markdown = false }: { kind: DemoWorkspaceFile["kind"]; markdown?: boolean }) {
  if (kind === "directory") {
    return (
      <svg className="h-4 w-4 shrink-0 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M3 7h6l2 2h10v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
      </svg>
    );
  }
  if (markdown) {
    return (
      <svg className="h-4 w-4 shrink-0 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M4 5h16v14H4V5Z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M7 15V9l3 4 3-4v6M16 9v6m0 0 2-2m-2 2-2-2" />
      </svg>
    );
  }
  return (
    <svg className="h-4 w-4 shrink-0 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M7 3h7l5 5v13H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M14 3v5h5" />
    </svg>
  );
}
