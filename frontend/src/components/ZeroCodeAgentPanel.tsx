import { Fragment } from "react";

export interface PendingUserInput {
  question: string;
  options?: string[];
  step?: string;
  workflow_step_id?: string;
  gate?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  fields?: Record<string, unknown> | PendingInputFieldLike[];
  command_preview?: string[];
  resume_action?: string;
  timeout_policy?: unknown;
  intervention?: {
    type: string;
    title?: string;
    admin_endpoint?: string;
    [key: string]: unknown;
  };
}

export interface PendingInputFieldLike {
  id?: string;
  label?: string;
  type?: string;
  value?: unknown;
  placeholder?: string;
  required?: boolean;
}

export interface SkillSelectionState {
  selected_skill?: string;
  source?: "model" | "fallback" | string;
  model_choice?: string | null;
  fallback_choice?: string | null;
  reason?: string | null;
  confidence?: number | null;
  error?: string | null;
}

export interface WorkflowStepState {
  id: string;
  name: string;
  status: string;
  output?: string;
  error?: string | null;
  expected_output?: string;
  phase?: string;
  execution_location?: string;
  progress?: string[];
  artifacts?: string[];
  attempts?: number;
  tool_calls?: unknown[];
  evidence?: Record<string, unknown>;
  validation_failures?: unknown[];
  instruction_plan?: unknown;
  gates?: string[];
  command_templates?: Record<string, string[] | string>;
  confirm_required?: boolean;
  skill_file?: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface WorkflowState {
  kind?: string;
  name?: string;
  version?: string;
  project_name?: string;
  current_step_id?: string | null;
  status?: string;
  gate_log?: Record<string, unknown>;
  completion_criteria?: string[];
  resources?: Record<string, unknown>;
  results?: Record<string, unknown>;
  steps?: WorkflowStepState[];
}

interface ZeroCodeAgentPanelProps {
  workflow: WorkflowState;
  pendingInput?: PendingUserInput | null;
  onSubmit: (content: string) => Promise<void>;
  skillSelection?: SkillSelectionState;
  workflowPath?: string | null;
  showExecutionLocation?: boolean;
  showGateLog?: boolean;
  panelTestId?: string;
  eyebrow?: string;
  title?: string;
  pipelineLabel?: string;
  completedNotice?: string;
}

export function ZeroCodeAgentPanel({
  workflow,
  pendingInput,
  onSubmit,
  skillSelection,
  workflowPath,
  showExecutionLocation = true,
  showGateLog = true,
  panelTestId = "zero-code-agent-panel",
  eyebrow = "Zero-Code Reproduction",
  title = "零代码复现流水线",
  pipelineLabel,
  completedNotice = "完成论文复现，相关产物以及报告文件可以在工作区下载",
}: ZeroCodeAgentPanelProps) {
  const steps = workflow.steps || [];
  const currentStep = workflowCurrentStep(workflow, steps);
  const gateRows = zeroCodeGateRows(workflow.gate_log);
  const isCompleted = workflow.status === "completed";
  const nextAction = isCompleted ? "" : readableWorkflowValue(workflow.gate_log?.next_action);
  const completedCount = steps.filter((step) => step.status === "completed").length;
  const selectedSkill =
    skillSelection?.selected_skill ||
    skillSelection?.model_choice ||
    skillSelection?.fallback_choice ||
    "zero-code-reproduction";

  return (
    <section
      data-testid={panelTestId}
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <div className="border-b border-slate-100 bg-white px-4 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
              {eyebrow}
            </div>
            <h3 className="mt-1 break-words text-md-h3 font-semibold text-slate-800">
              {title}
            </h3>
            <p className="mt-1 break-words text-ui-small text-slate-500">
              {selectedSkill}
              {workflowPath ? ` · ${workflowPath}` : ""}
            </p>
          </div>
          <span className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-ui-micro font-medium text-slate-500">
            {completedCount}/{steps.length} 完成
          </span>
        </div>
        {nextAction && (
          <div className="mt-3 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-ui-small text-amber-800">
            {nextAction}
          </div>
        )}
      </div>

      <div className={`grid gap-4 px-4 py-4 ${showGateLog ? "xl:grid-cols-[minmax(0,1fr)_minmax(280px,0.7fr)]" : ""}`}>
        <div className="min-w-0">
          {pipelineLabel && (
            <div className="mb-2 text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
              {pipelineLabel}
            </div>
          )}
          <div className="overflow-hidden rounded-lg border border-slate-100">
          <table className="w-full table-fixed text-ui-small">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className={showExecutionLocation ? "w-[24%] px-3 py-2 text-left font-semibold" : "w-[30%] px-3 py-2 text-left font-semibold"}>步骤</th>
                {showExecutionLocation && (
                  <th className="w-[16%] px-3 py-2 text-left font-semibold">执行位置</th>
                )}
                <th className="w-[16%] px-3 py-2 text-left font-semibold">状态</th>
                <th className="px-3 py-2 text-left font-semibold">产出</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {steps.map((step) => {
                const pending = pendingInputForStep(pendingInput, step, workflow);
                return (
                  <Fragment key={step.id}>
                    <tr data-testid={`zero-code-step-row-${step.id}`}>
                      <td className="px-3 py-2 align-top">
                        <div className="break-all font-mono text-slate-700">{step.id}</div>
                        <div className="mt-0.5 break-words text-slate-600">{step.name || step.id}</div>
                        {step.phase && (
                          <div className="mt-1 text-ui-micro text-slate-400">{step.phase}</div>
                        )}
                      </td>
                      {showExecutionLocation && (
                        <td className="break-words px-3 py-2 align-top text-slate-600">
                          {step.execution_location || "-"}
                        </td>
                      )}
                      <td className="px-3 py-2 align-top">
                        <span className={`rounded-full border px-2 py-0.5 text-ui-micro font-medium ${workflowStepStatusClass(step.status)}`}>
                          {workflowStepStatusLabel(step.status)}
                        </span>
                      </td>
                      <td className="break-words px-3 py-2 align-top text-slate-600">
                        {step.expected_output || "-"}
                      </td>
                    </tr>
                    {pending && (
                      <tr key={`${step.id}-pending`}>
                        <td className="px-3 py-3" colSpan={showExecutionLocation ? 4 : 3}>
                          <HumanInputPanel input={pending} onSubmit={onSubmit} stepId={step.id} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          </div>
        </div>

        {showGateLog && (
          <div className="min-w-0">
            <div className="mb-2 text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
              Gate Log
            </div>
            <div className="divide-y divide-slate-100 rounded-lg border border-slate-100">
              {gateRows.map((row) => (
                <div key={row.id} className="px-3 py-2 text-ui-small">
                  <div className="break-all font-mono text-slate-700">{row.id}</div>
                  <div className="mt-1 flex flex-wrap gap-2 text-slate-600">
                    {row.value && <span>{row.value}</span>}
                    {row.status && <span>{row.status}</span>}
                  </div>
                  {row.evidence && (
                    <div className="mt-1 break-words text-ui-micro text-slate-500">{row.evidence}</div>
                  )}
                </div>
              ))}
              {gateRows.length === 0 && (
                <div className="px-3 py-3 text-ui-small text-slate-500">暂无 gate 记录</div>
              )}
            </div>
            {isCompleted ? (
              <WorkflowCompletionNotice text={completedNotice} />
            ) : currentStep ? (
              <div className="mt-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-ui-small text-slate-600">
                当前步骤：{currentStep.id}
              </div>
            ) : null}
          </div>
        )}
        {!showGateLog && isCompleted && <WorkflowCompletionNotice text={completedNotice} />}
        {!showGateLog && !isCompleted && currentStep && (
          <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-ui-small text-slate-600">
            当前步骤：{currentStep.id}
          </div>
        )}
      </div>
    </section>
  );
}

function WorkflowCompletionNotice({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-ui-small text-emerald-700">
      {text}
    </div>
  );
}

function pendingInputForStep(
  pendingInput: PendingUserInput | null | undefined,
  step: WorkflowStepState,
  workflow: WorkflowState
) {
  if (!pendingInput) return null;
  if (pendingInput.workflow_step_id === step.id) return pendingInput;
  if (pendingInput.step === step.id) return pendingInput;
  if (!pendingInput.workflow_step_id && workflow.current_step_id === step.id) return pendingInput;
  return null;
}

function workflowCurrentStep(workflow: WorkflowState, steps: WorkflowStepState[]) {
  return (
    steps.find((step) => step.id === workflow.current_step_id) ||
    steps.find((step) => ["running", "waiting_for_user", "recovery"].includes(step.status)) ||
    steps.find((step) => step.status !== "completed")
  );
}

function workflowStepStatusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "⏳等待中...",
    running: "⏳执行中",
    waiting_for_user: "⏳等待中...",
    completed: "✅完成",
    recovery: "⏳执行中",
    failed: "中止",
    skipped: "跳过",
    stopped: "停止",
  };
  return labels[status] || status;
}

function workflowStepStatusClass(status: string) {
  if (status === "completed") return "border-emerald-100 bg-emerald-50 text-emerald-700";
  if (status === "running") return "border-blue-100 bg-blue-50 text-blue-700";
  if (status === "waiting_for_user") return "border-amber-100 bg-amber-50 text-amber-700";
  if (status === "recovery") return "border-amber-100 bg-amber-50 text-amber-700";
  if (status === "failed") return "border-red-100 bg-red-50 text-red-700";
  if (status === "skipped" || status === "stopped") return "border-slate-100 bg-slate-50 text-slate-500";
  return "border-slate-100 bg-slate-50 text-slate-500";
}

function zeroCodeGateRows(gateLog?: Record<string, unknown>) {
  return Object.entries(gateLog || {})
    .filter(([key]) => key !== "next_action")
    .map(([id, raw]) => {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
        return { id, value: readableWorkflowValue(raw), status: "", evidence: "" };
      }
      const record = raw as Record<string, unknown>;
      return {
        id,
        value: readableWorkflowValue(record.value ?? record.domain),
        status: readableWorkflowValue(record.status ?? record.experiment_type),
        evidence: readableWorkflowValue(record.evidence ?? record.activated_plugins),
      };
    });
}

function readableWorkflowValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(readableWorkflowValue).filter(Boolean).join(", ");
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function HumanInputPanel({
  input,
  onSubmit,
  stepId,
}: {
  input: PendingUserInput;
  onSubmit: (content: string) => Promise<void>;
  stepId?: string;
}) {
  const visibleOptions = humanInputVisibleOptions(input.options);
  const fieldRows = pendingInputFieldRows(input.fields);
  const commandPreview = input.command_preview || [];

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-3" data-testid="step-human-input">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-ui-meta font-bold uppercase text-amber-700">实验确认点</div>
          <div className="mt-1 text-ui-small font-semibold text-amber-900">
            需要你确认后继续执行受控动作
          </div>
        </div>
        <span className="rounded-full border border-amber-200 bg-white px-2 py-0.5 text-ui-micro font-medium text-amber-700">
          HITL
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-ui-micro text-amber-700">
        {stepId && <span>步骤：{stepId}</span>}
        {input.gate && <span>Gate: {input.gate}</span>}
        {input.tool_name && <span>操作：{input.tool_name}</span>}
      </div>
      <div className="mt-2 whitespace-pre-wrap text-chat-body leading-relaxed text-slate-700">
        {input.question}
      </div>
      {(fieldRows.length > 0 || Boolean(input.resume_action) || Boolean(input.timeout_policy)) && (
        <div className="mt-3 grid gap-2 rounded-md border border-amber-100 bg-white/70 px-3 py-2 text-ui-micro text-slate-600 sm:grid-cols-2">
          {fieldRows.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <span className="font-medium text-slate-700">{key}：</span>
              <span className="break-words">{readableWorkflowValue(value)}</span>
            </div>
          ))}
          {input.resume_action && (
            <div className="min-w-0">
              <span className="font-medium text-slate-700">resume_action：</span>
              <span className="break-words">{input.resume_action}</span>
            </div>
          )}
          {Boolean(input.timeout_policy) && (
            <div className="min-w-0">
              <span className="font-medium text-slate-700">timeout_policy：</span>
              <span className="break-words">{readableWorkflowValue(input.timeout_policy)}</span>
            </div>
          )}
        </div>
      )}
      {commandPreview.length > 0 && (
        <div className="mt-3 rounded-md border border-slate-200 bg-slate-950 px-3 py-2">
          <div className="mb-1 text-ui-meta font-semibold uppercase tracking-wide text-slate-400">
            Command Preview
          </div>
          <pre className="whitespace-pre-wrap break-words font-mono text-ui-micro leading-relaxed text-slate-100">
            {commandPreview.join("\n")}
          </pre>
        </div>
      )}
      {visibleOptions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {visibleOptions.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => void onSubmit(option)}
              className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-ui-small text-slate-700 hover:bg-amber-100"
            >
              {option}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function humanInputVisibleOptions(options?: string[]) {
  return (options || []).filter((option) => option.trim() !== "修改方案");
}

function pendingInputFieldRows(
  fields?: Record<string, unknown> | PendingInputFieldLike[]
): Array<[string, unknown]> {
  if (!fields) return [];
  if (!Array.isArray(fields)) return Object.entries(fields);
  return fields.map((field, index) => {
    const key = readableWorkflowValue(field.label ?? field.id) || `field_${index + 1}`;
    const value = field.value ?? field.placeholder ?? field.type ?? "";
    return [key, value];
  });
}
