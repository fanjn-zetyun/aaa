import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { MarkdownContent } from "../components/MarkdownContent";
import {
  ZeroCodeAgentPanel,
  type PendingUserInput,
  type SkillSelectionState,
  type WorkflowState,
  type WorkflowStepState,
} from "../components/ZeroCodeAgentPanel";

type MockStage =
  | "credential_required"
  | "credential_streaming"
  | "instance_confirm"
  | "instance_running"
  | "policies"
  | "setup"
  | "environment"
  | "experiment_plan"
  | "experiment_plan_running"
  | "logging"
  | "training_params"
  | "experiment_running"
  | "final_report"
  | "teardown"
  | "teardown_running"
  | "completed";

interface DemoWorkspaceFile {
  path: string;
  name: string;
  kind: "file" | "directory";
  size?: number;
  modifiedAt?: string;
  stepLabel: string;
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

const PROJECT_ROOT = "/workspace/user-data/codelab/minimind";
const REPORT_PATH = `${PROJECT_ROOT}/07_report/autoresearch_report.md`;
const SERVER_ID = "minimind-lab-042";
const SSH_HOST = randomSshHost();
const SSH_PORT = 30000 + Math.floor(Math.random() * 900);
const SSH_COMMAND = `ssh root@${SSH_HOST} -p ${SSH_PORT}`;
const SKILL_SELECTION_DELAY_MS = 2400;
const WORKFLOW_READY_DELAY_MS = 3200;
const STEP_REVEAL_DELAY_MS = 15_000;
const TRAINING_TO_REPORT_DELAY_MS = 60_000;
const TEARDOWN_COMPLETE_DELAY_MS = 10_000;

type AgentRevealStage = "thinking" | "skill_selected" | "workflow_ready";
type ParameterStage = "experiment_plan" | "training_params";
type BoardId = "initial" | "after_step5" | "after_step7";

interface DialogueMessage {
  role: "user" | "agent";
  text: string;
  boardId?: BoardId;
}

const CREDENTIAL_STREAM_LINES = [
  "已收到 Lab4AI 登录凭证，正在进行本地脱敏处理。",
  "正在写入受控运行上下文，密码不会在页面明文展示。",
  "凭证配置完成，准备加载自动化训练实验流水线。",
];

const SKILL_SELECTION: SkillSelectionState = {
  selected_skill: "lab4ai-auto-research",
  source: "fallback",
  fallback_choice: "lab4ai-auto-research",
  reason: "task_type=experiments 且输入包含 GitHub 自动化训练实验请求。",
};

const STAGE_COPY: Record<
  MockStage,
  {
    nextAction: string;
    agentSummary: string;
  }
> = {
  credential_required: {
    nextAction: "等待登录 Lab4AI 平台账号后继续。",
    agentSummary: "已识别 GitHub 仓库和自动化训练实验意图，需要先完成 Lab4AI 账号登录。",
  },
  credential_streaming: {
    nextAction: "正在完成凭证配置并加载运行上下文。",
    agentSummary: "Lab4AI 登录凭证已收到，正在准备自动化实验流水线。",
  },
  instance_confirm: {
    nextAction: "等待确认是否创建实验室实例（Lab instance flow）。",
    agentSummary: "凭证已保存，进入 lab4ai-auto-research 流程。",
  },
  instance_running: {
    nextAction: "正在创建实验室实例，约 15 秒后进入规则加载。",
    agentSummary: "已收到创建实例确认，正在申请 Lab4AI 实验环境。",
  },
  policies: {
    nextAction: "正在加载 Gate/HITL 策略，约 15 秒后进入项目 setup。",
    agentSummary: "实验室实例已创建，正在加载自动化实验边界和确认策略。",
  },
  setup: {
    nextAction: "正在确认项目路径、训练入口和 results.tsv 表头，约 15 秒后进入环境配置。",
    agentSummary: "实例连接产物已写入工作区，正在准备 minimind 项目。",
  },
  environment: {
    nextAction: "正在配置 conda 环境、Python 路径和镜像复用方案，约 15 秒后进入实验方案确认。",
    agentSummary: "项目 setup 已完成，仓库摘要和结果表已经写入工作区。",
  },
  experiment_plan: {
    nextAction: "等待确认实验方案参数。",
    agentSummary: "环境方案已完成，下一步需要确认实验方案中的可调参数。",
  },
  experiment_plan_running: {
    nextAction: "正在固化实验方案参数，约 15 秒后进入指标记录。",
    agentSummary: "实验方案参数已确认，正在写入本轮训练计划。",
  },
  logging: {
    nextAction: "正在准备 results.tsv 追加策略和指标抽取，约 15 秒后进入训练参数确认。",
    agentSummary: "实验方案已确认，正在固化指标记录方案。",
  },
  training_params: {
    nextAction: "等待确认实验训练关键参数。",
    agentSummary: "指标记录方案已完成，下一步需要确认训练循环的关键参数。",
  },
  experiment_running: {
    nextAction: "训练循环进行中，约 60 秒后进入最终报告生成。",
    agentSummary: "训练参数已确认，自动化训练实验循环正在执行。",
  },
  final_report: {
    nextAction: "正在生成最终报告，约 15 秒后进入实例释放确认。",
    agentSummary: "实验循环已结束，报告和训练日志已按 step 顺序写入工作区。",
  },
  teardown: {
    nextAction: "等待确认是否关闭 Lab4AI 实验室实例。",
    agentSummary: "最终报告已生成，等待确认是否释放 Lab4AI 实例。",
  },
  teardown_running: {
    nextAction: "正在关闭 Lab4AI 实验室实例，请等待资源释放完成。",
    agentSummary: "已收到关闭实例确认，正在释放 Lab4AI 资源并写入关机结果。",
  },
  completed: {
    nextAction: "自动化训练实验全流程已完成。",
    agentSummary: "实例已关闭，工作区保留完整的实验日志、结果表和报告产物。",
  },
};

const AUTO_RESEARCH_STEPS: WorkflowStepState[] = [
  workflowStep("instance_provision", "1. 实例申请", "Lab", "serverId / SSH / workspace 根目录"),
  workflowStep("policies", "2. 规则加载", "Policy", "Gate/HITL 规则与安全边界"),
  workflowStep("setup", "3. 项目 setup", "Setup", "project_root / entrypoint / results.tsv"),
  workflowStep("environments", "4. 环境配置", "Environment", "conda env / python path / mirror"),
  workflowStep("experimentation", "5. 实验方案", "Experiment", "训练假设 / 参数范围 / 安全改动范围"),
  workflowStep("output_and_logging", "6. 指标记录", "Logging", "results.tsv 追加策略 / 指标抽取"),
  workflowStep("experiment_loop", "7. 实验循环", "Loop", "round 1-3 / best val_loss / logs"),
  workflowStep("final_report", "8. 最终报告", "Report", "autoresearch_report.md"),
  workflowStep("instance_teardown", "9. 实例释放", "Teardown", "stop instance result"),
];

const STAGE_STEP_INDEX: Record<MockStage, number> = {
  credential_required: 0,
  credential_streaming: 0,
  instance_confirm: 0,
  instance_running: 0,
  policies: 1,
  setup: 2,
  environment: 3,
  experiment_plan: 4,
  experiment_plan_running: 4,
  logging: 5,
  training_params: 6,
  experiment_running: 6,
  final_report: 7,
  teardown: 8,
  teardown_running: 8,
  completed: 8,
};

const STAGE_COMPLETED_STEPS: Record<MockStage, number> = {
  credential_required: 0,
  credential_streaming: 0,
  instance_confirm: 0,
  instance_running: 0,
  policies: 1,
  setup: 2,
  environment: 3,
  experiment_plan: 4,
  experiment_plan_running: 4,
  logging: 5,
  training_params: 6,
  experiment_running: 6,
  final_report: 7,
  teardown: 8,
  teardown_running: 8,
  completed: 9,
};

const STAGE_STEP_STATUS: Partial<Record<MockStage, string>> = {
  instance_running: "running",
  policies: "running",
  setup: "running",
  environment: "running",
  experiment_plan: "waiting_for_user",
  experiment_plan_running: "running",
  logging: "running",
  training_params: "waiting_for_user",
  experiment_running: "running",
  final_report: "running",
  teardown: "waiting_for_user",
  teardown_running: "running",
};

const AUTO_STAGE_TRANSITIONS: Partial<Record<MockStage, { next: MockStage; delayMs: number }>> = {
  instance_running: { next: "policies", delayMs: STEP_REVEAL_DELAY_MS },
  policies: { next: "setup", delayMs: STEP_REVEAL_DELAY_MS },
  setup: { next: "environment", delayMs: STEP_REVEAL_DELAY_MS },
  environment: { next: "experiment_plan", delayMs: STEP_REVEAL_DELAY_MS },
  experiment_plan_running: { next: "logging", delayMs: STEP_REVEAL_DELAY_MS },
  logging: { next: "training_params", delayMs: STEP_REVEAL_DELAY_MS },
  experiment_running: { next: "final_report", delayMs: TRAINING_TO_REPORT_DELAY_MS },
  final_report: { next: "teardown", delayMs: STEP_REVEAL_DELAY_MS },
  teardown_running: { next: "completed", delayMs: TEARDOWN_COMPLETE_DELAY_MS },
};

export default function AutoResearchMockRunPage() {
  const [params] = useSearchParams();
  const githubUrl = params.get("github_url") || "https://github.com/jingyaogong/minimind";
  const originalInput =
    params.get("original_input") || `帮我跑下${githubUrl}的自动化训练实验`;
  const prompt = params.get("prompt") || "帮我跑下自动化训练实验";
  const [stage, setStage] = useState<MockStage>("credential_required");
  const [agentRevealStage, setAgentRevealStage] = useState<AgentRevealStage>("thinking");
  const [credentialMask, setCredentialMask] = useState<string | null>(null);
  const [credentialStreamCount, setCredentialStreamCount] = useState(0);
  const [chatDraft, setChatDraft] = useState("");
  const [dialogueMessages, setDialogueMessages] = useState<DialogueMessage[]>([]);
  const [experimentPlanConfig, setExperimentPlanConfig] = useState<string | null>(null);
  const [trainingConfig, setTrainingConfig] = useState<string | null>(null);
  const [activeBoardId, setActiveBoardId] = useState<BoardId>("initial");
  const [frozenBoardStages, setFrozenBoardStages] = useState<Partial<Record<BoardId, MockStage>>>({});
  const latestContentRef = useRef<HTMLDivElement | null>(null);

  const showRouting = agentRevealStage === "skill_selected" || agentRevealStage === "workflow_ready";
  const showCredentialForm = agentRevealStage === "workflow_ready" && stage === "credential_required";
  const showCredentialStream = agentRevealStage === "workflow_ready" && stage === "credential_streaming";
  const showWorkflow =
    agentRevealStage === "workflow_ready" && stage !== "credential_required" && stage !== "credential_streaming";
  const parameterPrompt = parameterPromptForStage(stage);

  useEffect(() => {
    const timers = [
      window.setTimeout(() => setAgentRevealStage("skill_selected"), SKILL_SELECTION_DELAY_MS),
      window.setTimeout(() => setAgentRevealStage("workflow_ready"), WORKFLOW_READY_DELAY_MS),
    ];
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    latestContentRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [agentRevealStage, dialogueMessages.length, stage]);

  useEffect(() => {
    const transition = AUTO_STAGE_TRANSITIONS[stage];
    if (!transition) return;
    const timer = window.setTimeout(() => setStage(transition.next), transition.delayMs);
    return () => window.clearTimeout(timer);
  }, [stage]);

  useEffect(() => {
    if (stage !== "credential_streaming") return;
    setCredentialStreamCount(0);
    const timers = [
      window.setTimeout(() => setCredentialStreamCount(1), 450),
      window.setTimeout(() => setCredentialStreamCount(2), 1_050),
      window.setTimeout(() => setCredentialStreamCount(3), 1_650),
      window.setTimeout(() => setStage("instance_confirm"), 2_100),
    ];
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [stage]);

  function handleCredentialSubmit(maskedAccount: string) {
    setCredentialMask(maskedAccount);
    setStage("credential_streaming");
  }

  async function handlePanelSubmit() {
    setStage((current) => {
      if (current === "instance_confirm") return "instance_running";
      if (current === "teardown") return "teardown_running";
      return current;
    });
  }

  function handleFollowUpSubmit(event: FormEvent) {
    event.preventDefault();
    if (!parameterPrompt) return;
    const content = chatDraft.trim();
    if (!content) return;
    const agentReply =
      parameterPrompt.stage === "experiment_plan"
        ? `收到，Step 5 实验方案按你的输入配置：${content}`
        : `收到，Step 7 训练关键参数按你的输入配置：${content}`;
    const nextBoardId: BoardId = parameterPrompt.stage === "experiment_plan" ? "after_step5" : "after_step7";
    setDialogueMessages((messages) => [
      ...messages,
      { role: "user", text: content },
      { role: "agent", text: agentReply, boardId: nextBoardId },
    ]);
    setChatDraft("");
    if (parameterPrompt.stage === "experiment_plan") {
      setExperimentPlanConfig(content);
      setFrozenBoardStages((current) => ({ ...current, initial: "experiment_plan" }));
      setActiveBoardId("after_step5");
      setStage("experiment_plan_running");
    } else {
      setTrainingConfig(content);
      setFrozenBoardStages((current) => ({ ...current, after_step5: "training_params" }));
      setActiveBoardId("after_step7");
      setStage("experiment_running");
    }
  }

  function boardStageFor(boardId: BoardId): MockStage | null {
    return frozenBoardStages[boardId] || (activeBoardId === boardId ? stage : null);
  }

  function boardConfigFor(boardId: BoardId) {
    return {
      experimentPlanConfig: boardId === "initial" ? null : experimentPlanConfig,
      trainingConfig: boardId === "after_step7" ? trainingConfig : null,
    };
  }

  function renderWorkflowContent(boardId: BoardId) {
    const boardStage = boardStageFor(boardId);
    if (!boardStage) return null;
    const isActiveBoard = activeBoardId === boardId && !frozenBoardStages[boardId];
    const config = boardConfigFor(boardId);
    const boardWorkflow = workflowForStage(
      boardStage,
      githubUrl,
      config.experimentPlanConfig,
      config.trainingConfig
    );
    const boardPendingInput = pendingInputForStage(boardStage, githubUrl);
    const boardParameterPrompt = isActiveBoard ? parameterPromptForStage(boardStage) : null;

    return (
      <>
        <StageSummaryCard stage={boardStage} />
        <ZeroCodeAgentPanel
          workflow={boardWorkflow}
          pendingInput={boardPendingInput}
          onSubmit={handlePanelSubmit}
          skillSelection={SKILL_SELECTION}
          workflowPath="skills/lab4ai-auto-research/SKILL.md"
          showExecutionLocation={false}
          showGateLog={false}
          panelTestId="autoresearch-mock-agent-panel"
          eyebrow="Lab4AI Auto Research"
          title="自动化训练实验流水线"
          pipelineLabel="Pipeline Steps"
          completedNotice="自动化训练实验完成，相关产物可以在工作区查看。"
        />
        {boardParameterPrompt && <ParameterQuestionCard prompt={boardParameterPrompt} />}
      </>
    );
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
                {agentRevealStage === "thinking" && <AgentThinkingCard />}
                {showRouting && <RoutingCard githubUrl={githubUrl} prompt={prompt} />}
                {showCredentialForm && <CredentialRequestCard onSubmit={handleCredentialSubmit} />}
                {showCredentialStream && <CredentialStreamingCard visibleCount={credentialStreamCount} />}
                {showWorkflow && (
                  <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-chat-body leading-relaxed text-slate-700 shadow-sm">
                    <p>凭证已保存，开始加载 lab4ai-auto-research workflow。</p>
                    <p className="mt-1">需要创建 Lab4AI 实例运行 minimind 自动化训练实验。</p>
                  </div>
                )}
                {showWorkflow && renderWorkflowContent("initial")}
              </AgentMessage>
              {dialogueMessages.map((message, index) =>
                message.role === "user" ? (
                  <UserDialogueBubble key={`${message.role}-${index}`}>{message.text}</UserDialogueBubble>
                ) : (
                  <AgentMessage key={`${message.role}-${index}`}>
                    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-chat-body leading-relaxed text-slate-700 shadow-sm">
                      {message.text}
                    </div>
                    {message.boardId && renderWorkflowContent(message.boardId)}
                  </AgentMessage>
                )
              )}
              <div ref={latestContentRef} aria-hidden="true" />
            </div>
          </div>
          <FollowUpChatBox
            enabled={Boolean(parameterPrompt)}
            value={chatDraft}
            placeholder={parameterPrompt?.placeholder || "继续输入你的问题或调整要求..."}
            onChange={setChatDraft}
            onSubmit={handleFollowUpSubmit}
          />
        </div>

        <div className="min-h-0 py-4 pr-4 lg:py-6 lg:pr-6">
          <AutoResearchDemoRightPanel stage={stage} credentialMask={credentialMask} />
        </div>
      </div>
    </div>
  );
}

function AgentMessage({ children }: { children: ReactNode }) {
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

function UserDialogueBubble({ children }: { children: ReactNode }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-3xl whitespace-pre-wrap rounded-2xl bg-slate-800 px-4 py-3 text-chat-body leading-relaxed text-white shadow-sm">
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
      <span>正在读取 GitHub 仓库地址并判断自动化训练入口...</span>
    </div>
  );
}

function CredentialStreamingCard({ visibleCount }: { visibleCount: number }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-4 shadow-sm">
      <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">Credential Setup</div>
      <div className="mt-3 space-y-2">
        {CREDENTIAL_STREAM_LINES.slice(0, visibleCount).map((line) => (
          <div key={line} className="flex items-start gap-2 text-chat-body text-slate-700">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
            <span>{line}</span>
          </div>
        ))}
        {visibleCount < CREDENTIAL_STREAM_LINES.length && (
          <div className="inline-flex items-center gap-2 text-chat-body text-slate-500">
            <span className="flex gap-1" aria-hidden="true">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400 [animation-delay:160ms]" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400 [animation-delay:320ms]" />
            </span>
            <span>正在继续配置...</span>
          </div>
        )}
      </div>
    </div>
  );
}

function RoutingCard({ githubUrl, prompt }: { githubUrl: string; prompt: string }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white px-4 py-4 shadow-sm">
      <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">Agent Routing</div>
      <div className="mt-3 space-y-2 text-chat-body leading-relaxed text-slate-700">
        <p>检测到 GitHub 仓库和自动化训练实验请求，确定性选择 skill：lab4ai-auto-research。</p>
        <p className="break-all">仓库：{githubUrl}</p>
        <p>请求：{prompt}</p>
      </div>
    </section>
  );
}

function CredentialRequestCard({ onSubmit }: { onSubmit: (maskedAccount: string) => void }) {
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!account.trim() || !password.trim()) {
      setError("请填写 Lab4AI 平台账号和密码。");
      return;
    }
    onSubmit(maskAccount(account));
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-ui-meta font-bold uppercase text-amber-700">等待你登录</div>
          <div className="mt-1 text-ui-small font-semibold text-amber-900">配置 Lab4AI 平台账号</div>
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
            value={account}
            onChange={(event) => setAccount(event.target.value)}
            placeholder="请输入平台账号"
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
            placeholder="请输入平台密码"
            className="mt-1 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-ui-small text-slate-700"
          />
        </label>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="text-ui-micro text-amber-700">页面只展示脱敏账号，不展示密码明文。</p>
        <button
          type="submit"
          className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-ui-small font-medium text-slate-700 hover:bg-amber-100"
        >
          登录并继续
        </button>
      </div>
      {error && <p className="mt-2 text-ui-small text-red-600">{error}</p>}
    </form>
  );
}

function StageSummaryCard({ stage }: { stage: MockStage }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-chat-body leading-relaxed text-slate-700 shadow-sm">
      <p>{STAGE_COPY[stage].agentSummary}</p>
      <p className="mt-1 text-ui-small text-slate-500">{STAGE_COPY[stage].nextAction}</p>
    </div>
  );
}

function ParameterQuestionCard({
  prompt,
}: {
  prompt: {
    stage: ParameterStage;
    title: string;
    question: string;
    suggestions: string[];
  };
}) {
  return (
    <section className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-4">
      <div className="text-ui-meta font-bold uppercase text-amber-700">{prompt.title}</div>
      <p className="mt-2 text-chat-body leading-relaxed text-slate-700">{prompt.question}</p>
      <div className="mt-3 space-y-1 text-ui-small text-slate-600">
        {prompt.suggestions.map((suggestion) => (
          <div key={suggestion}>- {suggestion}</div>
        ))}
      </div>
      <p className="mt-3 text-ui-small text-amber-700">请直接在下方对话框输入选择或自定义参数。</p>
    </section>
  );
}

function FollowUpChatBox({
  enabled,
  value,
  placeholder,
  onChange,
  onSubmit,
}: {
  enabled: boolean;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <div data-testid="autoresearch-follow-up-bar" className="shrink-0 border-t border-slate-100 bg-white p-3">
      <form className="w-full" onSubmit={onSubmit}>
        <div className="flex w-full items-end gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 transition-colors focus-within:border-slate-300 focus-within:bg-white">
          <label className="sr-only" htmlFor="autoresearch-follow-up-input">
            继续输入任务需求
          </label>
          <textarea
            id="autoresearch-follow-up-input"
            aria-label="继续输入任务需求"
            disabled={!enabled}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder}
            rows={1}
            className="flex-1 resize-none bg-transparent text-chat-body leading-relaxed text-slate-700 placeholder-slate-300 disabled:opacity-50"
          />
          <button
            type="submit"
            aria-label="发送消息"
            disabled={!enabled || !value.trim()}
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

function AutoResearchDemoRightPanel({
  stage,
  credentialMask,
}: {
  stage: MockStage;
  credentialMask: string | null;
}) {
  const files = workspaceFilesForStage(stage);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const previewFile = files.find((file) => file.path === previewPath);
  const instances = demoInstancesForStage(stage);

  return (
    <aside
      data-testid="autoresearch-demo-right-panel"
      className="min-h-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <div className="flex h-full min-h-[520px] flex-col overflow-hidden">
        <section className="h-[45%] min-h-[290px] shrink-0 overflow-hidden border-b border-slate-200">
          <PanelHeader title="权限与环境配置" subtitle={rightPanelStatus(stage)} />
          <div className="h-[calc(100%-57px)] overflow-y-auto px-4 py-4">
            <div className="space-y-4">
              <Lab4AICredentialBlock credentialMask={credentialMask} />
              <div>
                <SectionTitle label="Lab4AI 实例" />
                {instances.length > 0 && (
                  <div className="space-y-3">
                    {instances.map((instance) => <InstanceBlock key={instance.serverId} instance={instance} />)}
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>
        <section className="min-h-0 flex-1 overflow-hidden">
          {previewPath ? (
            <WorkspacePreview file={previewFile} fallbackPath={previewPath} onBack={() => setPreviewPath(null)} />
          ) : (
            <WorkspaceFileList files={files} onPreview={setPreviewPath} />
          )}
        </section>
      </div>
    </aside>
  );
}

function Lab4AICredentialBlock({ credentialMask }: { credentialMask: string | null }) {
  const configured = Boolean(credentialMask);
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
          <CredentialRow label="账号" value={credentialMask || ""} />
          <CredentialRow label="密码" value="已安全保存" />
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-ui-small text-slate-500">
          Lab4AI 凭证未配置，等待账号登录。
        </div>
      )}
    </div>
  );
}

function WorkspaceFileList({
  files,
  onPreview,
}: {
  files: DemoWorkspaceFile[];
  onPreview: (path: string) => void;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 border-b border-slate-100 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">Workspace</div>
            <div className="mt-0.5 text-ui-small font-semibold text-slate-800">工作区文件</div>
          </div>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-ui-micro text-slate-500">
            按 step 顺序
          </span>
        </div>
      </div>
      <div data-testid="autoresearch-workspace-file-list" className="min-h-0 flex-1 overflow-y-auto">
        {files.length === 0 ? (
          <div className="px-4 py-4">
            <EmptyPanelText text="工作区待创建，确认后会展示生成文件。" />
          </div>
        ) : (
          <div className="py-2">
            {files.map((file) => (
              <DemoFileRow key={file.path} file={file} onPreview={onPreview} />
            ))}
          </div>
        )}
      </div>
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
        <div className="mt-0.5 text-ui-micro text-slate-400">
          {file.stepLabel}
          {file.kind === "file" && file.size ? ` · ${formatSize(file.size)}` : ""}
          {file.modifiedAt ? ` · ${file.modifiedAt}` : ""}
        </div>
      </div>
      {file.kind === "file" && (
        <span className="shrink-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-ui-micro font-medium text-slate-500">
          下载
        </span>
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
  stage: MockStage,
  githubUrl: string,
  experimentPlanConfig: string | null,
  trainingConfig: string | null
): WorkflowState {
  const currentStepId = AUTO_RESEARCH_STEPS[STAGE_STEP_INDEX[stage]].id;
  const visibleSteps = visibleWorkflowStepsForStage(stage);
  return {
    kind: "autoresearch_pipeline",
    name: "autoresearch_pipeline",
    version: "1.0",
    project_name: "minimind",
    current_step_id: currentStepId,
    status: stage === "completed" ? "completed" : "waiting_for_user",
    gate_log: { next_action: STAGE_COPY[stage].nextAction },
    results: {
      github_url: githubUrl,
      project_root: PROJECT_ROOT,
      server_id: SERVER_ID,
      ssh_command: SSH_COMMAND,
      report_path: REPORT_PATH,
    },
    steps: visibleSteps.map(({ index, status }) => ({
      ...AUTO_RESEARCH_STEPS[index],
      status,
      expected_output: outputForStep(stage, AUTO_RESEARCH_STEPS[index].id, experimentPlanConfig, trainingConfig),
    })),
  };
}

function pendingInputForStage(stage: MockStage, githubUrl: string): PendingUserInput | null {
  if (stage === "completed") return null;
  const shared = {
    fields: {
      repo: githubUrl,
      project_root: PROJECT_ROOT,
    },
    command_preview: commandPreviewForStage(stage, githubUrl),
    timeout_policy: "高风险动作需经 HITL 确认；正式运行按 skill 配置执行超时保护。",
  };
  if (stage === "instance_confirm") {
    return {
      ...shared,
      question: "Lab instance flow：是否创建实验室实例，用于 minimind 自动化训练实验？",
      options: ["创建实例"],
      gate: "lab_instance_flow",
      tool_name: "lab4ai_create_instance",
      workflow_step_id: "instance_provision",
      resume_action: "创建实例后进入 policies 和项目 setup 阶段。",
    };
  }
  if (stage === "teardown") {
    return {
      ...shared,
      question: "关机确认：报告已生成，是否立即关闭 Lab4AI 实验室实例？",
      options: ["立即关闭实例"],
      gate: "step_7_stop_instance",
      tool_name: "lab4ai_stop_instance",
      workflow_step_id: "instance_teardown",
      resume_action: "关闭后写入 instance_stop.json 并结束任务。",
    };
  }
  return null;
}

function statusForStep(stage: MockStage, index: number) {
  const completedCount = STAGE_COMPLETED_STEPS[stage];
  if (index < completedCount) return "completed";
  if (stage !== "completed" && index === STAGE_STEP_INDEX[stage]) {
    return STAGE_STEP_STATUS[stage] || "waiting_for_user";
  }
  return "pending";
}

function visibleWorkflowStepsForStage(stage: MockStage) {
  if (stage === "credential_required") return [];
  const lastVisibleIndex = stage === "completed" ? AUTO_RESEARCH_STEPS.length - 1 : STAGE_STEP_INDEX[stage];
  return Array.from({ length: lastVisibleIndex + 1 }, (_, index) => ({
    index,
    status: statusForStep(stage, index),
  }));
}

function outputForStep(
  stage: MockStage,
  stepId: string,
  experimentPlanConfig: string | null,
  trainingConfig: string | null
) {
  const completedOutputs: Record<string, string> = {
    instance_provision: `serverId=${SERVER_ID}；SSH=${SSH_COMMAND}`,
    policies: "Gate/HITL 策略已加载，所有高风险动作等待确认。",
    setup: `${PROJECT_ROOT}；entrypoint=train.py；results.tsv 已创建`,
    environments: "env=minimind-autoresearch；python=/opt/conda/envs/minimind-autoresearch/bin/python",
    experimentation: experimentPlanConfig
      ? `已配置实验方案：${experimentPlanConfig}`
      : "实验假设：小批量训练验证；参数范围：epochs=1 batch_size=16",
    output_and_logging: "results.tsv 记录 commit、round、val_loss、memory_gb、status",
    experiment_loop: trainingConfig
      ? `已配置训练策略：${trainingConfig}；best val_loss=2.71；日志已归档`
      : "round 3/3；best val_loss=2.71；日志已归档",
    final_report: REPORT_PATH,
    instance_teardown: "timeout_auto_stop 未触发；user_yes stop complete",
  };
  if (stepId === "experimentation" && stage === "experiment_plan_running" && experimentPlanConfig) {
    return `正在写入实验方案：${experimentPlanConfig}`;
  }
  if (stepId === "experiment_loop" && stage === "experiment_running" && trainingConfig) {
    return `执行中：${trainingConfig}`;
  }
  if (stepId === "instance_teardown" && stage === "teardown_running") {
    return "正在关闭实例并写入 instance_stop.json";
  }
  const index = AUTO_RESEARCH_STEPS.findIndex((step) => step.id === stepId);
  if (index < STAGE_COMPLETED_STEPS[stage] || stage === "completed") return completedOutputs[stepId] || "-";
  return AUTO_RESEARCH_STEPS[index]?.expected_output || "-";
}

function commandPreviewForStage(stage: MockStage, githubUrl: string) {
  if (stage === "instance_confirm" || stage === "instance_running") {
    return ["lab4ai_create_instance", `${SSH_COMMAND} # serverId=${SERVER_ID}`];
  }
  if (stage === "setup") {
    return [
      `git clone ${githubUrl} ${PROJECT_ROOT}/code`,
      `printf 'commit\\tround\\tval_loss\\tmemory_gb\\tstatus\\tdescription\\n' > ${PROJECT_ROOT}/03_setup/results.tsv`,
    ];
  }
  if (stage === "environment") {
    return [
      "conda create -n minimind-autoresearch python=3.10 -y",
      "conda run -n minimind-autoresearch python -c \"import sys; print(sys.executable)\"",
    ];
  }
  if (stage === "experiment_plan") {
    return ["epochs=1", "batch_size=8|16|24", "learning_rate=2e-4|3e-4"];
  }
  if (stage === "training_params" || stage === "experiment_running") {
    return [
      "max_rounds=3",
      "per_run_limit=5m",
      `(cd ${PROJECT_ROOT}/code && python train.py --epochs 1 --batch_size 16)`,
    ];
  }
  if (stage === "teardown" || stage === "teardown_running") return [`lab4ai_stop_instance serverId=${SERVER_ID}`];
  return [];
}

function demoInstancesForStage(stage: MockStage): DemoInstance[] {
  if (["credential_required", "instance_confirm"].includes(stage)) return [];
  return [
    {
      label: "GPU/CPU Lab",
      serverId: SERVER_ID,
      status: stage === "completed" ? "已关闭" : stage === "teardown_running" ? "关闭中" : "运行中",
      spec: "1x H100 / 8C CPU / 64GB RAM",
      username: "root",
      sshCommand: SSH_COMMAND,
    },
  ];
}

function workspaceFilesForStage(stage: MockStage) {
  const files = demoWorkspaceFiles();
  if (["credential_required", "credential_streaming", "instance_confirm", "instance_running"].includes(stage)) return [];
  if (["policies", "setup"].includes(stage)) return files.slice(0, 2);
  if (stage === "environment") return files.slice(0, 4);
  if (["experiment_plan", "experiment_plan_running", "logging", "training_params", "experiment_running"].includes(stage)) {
    return files.slice(0, 5);
  }
  if (["final_report", "teardown", "teardown_running"].includes(stage)) return files.slice(0, 9);
  if (stage === "completed") return files;
  return [];
}

function demoWorkspaceFiles(): DemoWorkspaceFile[] {
  return [
    {
      path: "01_lab_instance/lab_instance.json",
      name: "lab_instance.json",
      kind: "file",
      size: 620,
      modifiedAt: "05-26 12:01",
      stepLabel: "Step 1 实例申请",
    },
    {
      path: "01_lab_instance/ssh_connection.txt",
      name: "ssh_connection.txt",
      kind: "file",
      size: 128,
      modifiedAt: "05-26 12:01",
      stepLabel: "Step 1 实例申请",
    },
    {
      path: "03_setup/project_summary.md",
      name: "project_summary.md",
      kind: "file",
      size: 2400,
      modifiedAt: "05-26 12:03",
      stepLabel: "Step 3 项目 setup",
      content: "# minimind project summary\n\n- repository: jingyaogong/minimind\n- entrypoint: train.py\n- workspace: /workspace/user-data/codelab/minimind",
    },
    {
      path: "03_setup/results.tsv",
      name: "results.tsv",
      kind: "file",
      size: 360,
      modifiedAt: "05-26 12:03",
      stepLabel: "Step 3 项目 setup",
    },
    {
      path: "04_environment/environment.md",
      name: "environment.md",
      kind: "file",
      size: 1800,
      modifiedAt: "05-26 12:05",
      stepLabel: "Step 4 环境配置",
      content: "# Environment\n\n- env: minimind-autoresearch\n- python: /opt/conda/envs/minimind-autoresearch/bin/python\n- mirror: Lab4AI base image",
    },
    {
      path: "06_loop/round_01.log",
      name: "round_01.log",
      kind: "file",
      size: 1200,
      modifiedAt: "05-26 12:08",
      stepLabel: "Step 7 实验循环",
    },
    {
      path: "06_loop/round_02.log",
      name: "round_02.log",
      kind: "file",
      size: 1240,
      modifiedAt: "05-26 12:11",
      stepLabel: "Step 7 实验循环",
    },
    {
      path: "06_loop/round_03.log",
      name: "round_03.log",
      kind: "file",
      size: 1260,
      modifiedAt: "05-26 12:14",
      stepLabel: "Step 7 实验循环",
    },
    {
      path: "07_report/autoresearch_report.md",
      name: "autoresearch_report.md",
      kind: "file",
      size: 5400,
      modifiedAt: "05-26 12:16",
      stepLabel: "Step 8 最终报告",
      content:
        "# minimind AutoResearch Report\n\n- rounds: 3\n- best val_loss: 2.71\n- artifacts: results.tsv, round logs, environment.md\n- instance: minimind-lab-042",
    },
    {
      path: "08_teardown/instance_stop.json",
      name: "instance_stop.json",
      kind: "file",
      size: 420,
      modifiedAt: "05-26 12:17",
      stepLabel: "Step 9 实例释放",
    },
  ];
}

function rightPanelStatus(stage: MockStage) {
  if (stage === "credential_required") return "等待凭证";
  if (stage === "credential_streaming") return "凭证配置中";
  if (stage === "instance_confirm") return "等待确认";
  if (stage === "teardown_running") return "实例关闭中";
  if (stage === "completed") return "已完成";
  return "运行中";
}

function parameterPromptForStage(stage: MockStage):
  | {
      stage: ParameterStage;
      title: string;
      question: string;
      suggestions: string[];
      placeholder: string;
    }
  | null {
  if (stage === "experiment_plan") {
    return {
      stage: "experiment_plan",
      title: "Step 5 参数配置",
      question:
        "实验方案参数需要你确认。你要选哪个方案，或者你要自己配置什么参数，直接告诉我。",
      suggestions: [
        "稳妥参数：epochs=1 batch_size=16 lr=3e-4",
        "低显存参数：epochs=1 batch_size=8 lr=2e-4",
        "自定义示例：epochs=1 batch_size=12 lr=2.5e-4 seed=42",
      ],
      placeholder: "输入 Step 5 实验方案参数，例如：稳妥参数，或 epochs=1 batch_size=16 lr=3e-4",
    };
  }
  if (stage === "training_params") {
    return {
      stage: "training_params",
      title: "Step 7 训练参数配置",
      question:
        "训练循环的关键参数需要你确认。你要选择哪个执行策略，或者要自己配置轮数、时限和主指标，也可以直接告诉我。",
      suggestions: [
        "启动训练：3 轮 / 单轮 5 分钟 / val_loss",
        "降低风险：2 轮 / 单轮 4 分钟 / val_loss",
        "自定义示例：rounds=3 per_run_limit=6m metric=val_loss early_stop=true",
      ],
      placeholder: "输入 Step 7 训练参数，例如：3 轮 / 单轮 5 分钟 / val_loss",
    };
  }
  return null;
}

function workflowStep(id: string, name: string, phase: string, expectedOutput: string): WorkflowStepState {
  return {
    id,
    name,
    phase,
    execution_location: "Lab4AI",
    expected_output: expectedOutput,
    status: "pending",
  };
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
    <div className="grid grid-cols-[64px_minmax(0,1fr)] gap-3 text-ui-small">
      <span className="text-slate-400">{label}</span>
      <span className="min-w-0 break-all font-mono text-slate-700">{value}</span>
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

function fileNameFromPath(path: string) {
  return path.split("/").pop() || path;
}

function maskAccount(account: string) {
  const trimmed = account.trim();
  if (trimmed.includes("@")) {
    const [name, domain] = trimmed.split("@");
    return `${name.slice(0, 2)}****@${domain}`;
  }
  const digits = trimmed.replace(/\D/g, "");
  if (digits.length >= 8) return `${digits.slice(0, 3)}****${digits.slice(-4)}`;
  if (trimmed.length <= 4) return `${trimmed.slice(0, 1)}***`;
  return `${trimmed.slice(0, 2)}****${trimmed.slice(-2)}`;
}

function randomSshHost() {
  const lastOctet = 112 + Math.floor(Math.random() * 36);
  return `182.242.159.${lastOctet}`;
}

function formatSize(size: number) {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}
