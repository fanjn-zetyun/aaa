# Workflow Chat UI Design

## Context

用户在对话页输入类似：

```text
帮我复现这个项目：https://github.com/jsnzwu/motion-guided-flow
```

系统已经支持由模型优先选择 skill，并在规则兜底时记录 `skill_selection.source=fallback`。下一步需要把这个能力自然地呈现在前端对话页中，同时解决当前 Agent 回复过程“日志堆叠、显示混乱”的问题。

本设计基于静态 demo：

- `docs/superpowers/mockups/reproduce-workflow-chat-demo.html`

## Goals

1. 让用户能在对话页看到模型如何选择 skill，但不暴露模型隐藏思维链。
2. 让复现过程按 `skills/lab4ai-auto-reproduct/project_reproduce.yaml` 的步骤分步显示、持续更新。
3. 让中途 human input，例如 Lab4AI 登录凭证、受限数据集确认，嵌入当前 workflow step 内，而不是出现在割裂的最终回答气泡中。
4. 让最终回答只负责总结产物、结论、报告路径和资源释放状态。
5. 保留可审计证据，方便判断某次运行是 `model` 选择还是 `fallback` 兜底。

## Non-Goals

- 不展示模型原始隐藏思维链。
- 不把敏感凭证写入普通聊天正文、普通 message content 或公开日志。
- 不在前端重新解析 YAML 文件。前端只消费后端发布的 workflow public state。
- 不改变 `project_reproduce.yaml` 的业务语义。

## UX Structure

同一轮 Agent 回复由三个稳定区域组成：

1. **Skill Selection Card**
   展示“识别任务、读取可用 skills、模型选择 skill、加载 workflow”的自然语言过程。

2. **Workflow Run Card**
   展示 `project_reproduce.yaml` 中的 workflow step。当前运行、失败、等待用户确认的 step 自动展开；已完成 step 默认显示摘要。

3. **Final Answer Card**
   仅在任务结束或失败收敛后出现，显示最终结论、报告路径、关键结果和下一步建议。

中途确认不进入 Final Answer Card。确认表单挂在当前 step 下。

## Skill Selection Display

默认展示自然语言摘要：

```text
已识别为 GitHub 项目复现任务
模型选择了 lab4ai-auto-reproduct
已加载 project_reproduce.yaml
```

卡片右侧显示来源标记：

- `模型选择`：`skill_selection.source === "model"`
- `规则兜底`：`skill_selection.source === "fallback"`

可展开“查看选择证据”区域，展示安全字段：

```text
source: model
selected_skill: lab4ai-auto-reproduct
model_choice: lab4ai-auto-reproduct
fallback_choice: -
workflow: skills/lab4ai-auto-reproduct/project_reproduce.yaml
reason: Model selected registered skill `lab4ai-auto-reproduct`.
```

这里展示的是决策摘要和审计字段，不是隐藏思维链。

## Workflow Step Display

Workflow Run Card 的顺序来源是后端解析后的 workflow public state。对 `lab4ai-auto-reproduct`，显示顺序应对应 `project_reproduce.yaml`：

1. `step_1_audit` 项目复现可行性分析
2. `step_2_condition_check` 复现可行性熔断判断
3. `step_3_deploy_cpu` 拉起廉价 CPU 实例
4. `step_4_cpu_env_setup` 在 CPU 上拉取代码与智能环境/数据构建
5. `step_5_release_cpu` 释放 CPU 实例
6. `step_6_deploy_gpu` 拉起 H800A GPU 实例
7. `step_7_gpu_execution` SSH 探活、底层算子编译与微调测试
8. `step_8_generate_report` 结构化抽取与生成 Word 报告
9. `step_9_release_gpu` 释放 GPU 实例

每个 step 显示：

- step 序号
- step id
- step name
- 状态：等待、运行中、等待你确认、完成、失败
- 当前摘要
- 最近进展，最多显示最近 3 条，展开后可看更多
- 相关工具调用 chips，例如 `claw-shell 运行中`、`lab4ai-project-prep 完成`
- 产物或结果摘要，例如审计报告、实例 ID、Word 报告路径

`workflow_step_progress` 不再作为独立大块事件堆在对话中，而是归档到对应 step 的 `progress` 列表里。

## Human Input Display

Human input 使用当前 step 内嵌面板。

示例：`step_3_deploy_cpu` 需要 Lab4AI 登录凭证：

```text
[等待你确认] 3. 拉起廉价 CPU 实例
             申请 CPU 实例前需要 Lab4AI 登录凭证。

             需要你的输入
             为了创建 Lab4AI CPU 实例，请由管理员配置平台账号。

             手机号/账号    [________________]
             密码           [________________]

             [保存并继续] [打开管理员配置] [稍后再说]
```

提交后：

- 当前 step 从 `等待你确认` 变为 `运行中`
- 页面显示 `凭证已配置`
- 不显示账号和密码明文
- Agent Loop 从当前 workflow step 继续

普通确认也使用同一个面板。例如受限数据集：

```text
检测到数据集需要人工申请权限。是否跳过该数据集，使用示例数据做 Smoke Test？

[跳过并继续] [我已准备好数据] [暂停任务]
```

## Data Flow

### Skill Selection

后端在完成 skill selection 后，持久化并通过 stream 暴露：

```json
{
  "skill_selection": {
    "selected_skill": "lab4ai-auto-reproduct",
    "source": "model",
    "model_choice": "lab4ai-auto-reproduct",
    "fallback_choice": null,
    "reason": "Model selected registered skill `lab4ai-auto-reproduct`.",
    "confidence": null,
    "error": null
  }
}
```

前端用这个对象渲染 Skill Selection Card。运行中如果收到 `stage="skill_selection"` 的 progress 事件，也更新同一张卡片，而不是追加无关消息。

### Workflow

后端继续使用已有 workflow stream 事件：

- `workflow_loaded`
- `workflow_step_started`
- `workflow_step_progress`
- `workflow_step_waiting`
- `workflow_step_completed`
- `workflow_step_failed`
- `workflow_step_recovery_started`
- `workflow_step_recovery_progress`
- `workflow_step_recovery_exhausted`

这些事件都应携带或能关联到 `workflow_public_state(metadata)`。前端按 `step.id` 合并到同一份 workflow UI 状态。

### Human Input

后端已有 `metadata.pending_user_input` 概念。前端渲染时应优先把 pending input 挂到对应 step：

1. 若 `pending_user_input.step` 存在，挂到该 step。
2. 若无 step，但 `workflow_current_step_id` 存在，挂到当前 step。
3. 若无法关联 step，才显示为 Agent 气泡下方的通用确认面板。

Lab4AI 凭证类输入使用现有管理员配置 API `/api/admin/settings/lab4ai`，保存到加密的 admin settings，不拼接进普通聊天消息。普通 yes/no 选择沿用现有消息确认流程。

## Frontend Components

建议在 `frontend/src/pages/ChatPage.tsx` 附近拆出或新增以下组件：

- `AgentRunCard`
  包含 skill selection、workflow run、final answer 三块。

- `SkillSelectionCard`
  渲染模型选择摘要和可展开证据。

- `WorkflowRunCard`
  渲染 workflow header 和 step list。

- `WorkflowStepRow`
  渲染单个 step 的状态、摘要、进展和工具调用。

- `HumanInputPanel`
  渲染当前 step 下的人类确认、选项或凭证表单。

- `FinalAnswer`
  保持最终总结职责，不承载中途确认。

当前 `REPRO_WORKFLOW_STEPS` 可以保留为极端情况下的展示 fallback，但正常路径应使用后端传来的 `workflow.steps`。

## Error Handling

- 模型未配置：Skill Selection Card 显示 `规则兜底`，证据区显示 `error=llm_not_configured`。
- 模型选到未知 skill：显示 `规则兜底`，证据区保留 `model_choice` 和 `error=unknown_skill`。
- 未找到 workflow skill：workflow 区显示失败状态，不启动旧的硬编码流程。
- step 失败：对应 step 自动展开，显示 error、最近 progress、相关工具调用。
- 等待用户：对应 step 自动展开并显示 Human Input Panel。
- 用户刷新页面：从 conversation metadata 恢复 skill selection、workflow state 和 pending input。

## Security

- 密码、token 等敏感字段只通过安全表单处理。
- 前端不把敏感字段写入普通 message content。
- stream 和 metadata 中只记录“凭证已配置”或凭证配置状态，不记录明文。
- 复制 Agent 消息时，不复制隐藏表单值。
- 展开证据区只展示安全审计字段。

## Testing

### Backend

- skill selection metadata 包含 `source=model` 时，API detail 和 stream 均能暴露安全字段。
- fallback 场景包含 `source=fallback` 和 error。
- `workflow_loaded` 和 step event 携带的 public state 能恢复 YAML step 顺序。
- pending user input 带 step 时，metadata 可被前端关联到当前 step。
- 凭证类输入不落入普通 conversation message content。

### Frontend

- 收到 `skill_selection` metadata 后显示 `模型选择` 或 `规则兜底`。
- `workflow_step_progress` 被归档到对应 step，而不是产生散乱独立气泡。
- 当前运行 step 自动展开，完成 step 显示摘要。
- `pending_user_input` 挂到当前 step，并显示 Human Input Panel。
- 凭证表单提交后不在聊天正文中显示明文。
- 刷新页面后能从 conversation detail 恢复 skill selection、workflow steps 和 human input 状态。

### Visual Verification

- 使用本地 dev server 打开对话页。
- 模拟 GitHub 复现任务，确认首屏能看到 skill selection 和 workflow card。
- 模拟 waiting_for_user 状态，确认确认面板嵌入当前 step。
- 检查桌面和移动宽度下文本不重叠、表单不溢出。

## Acceptance Criteria

- 用户输入 GitHub 复现请求后，对话页能自然展示模型选择 skill 的过程。
- 用户能展开查看 `source=model`、`model_choice` 等证据。
- 复现进度按 YAML step 更新，不再堆叠散乱日志。
- Human input 出现在当前 step 内，不出现在最终回答里。
- 最终回答只展示总结、产物和结论。
- 敏感凭证不会出现在普通消息、复制内容或可见日志中。
