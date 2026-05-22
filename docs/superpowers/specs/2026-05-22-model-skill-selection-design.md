# 模型驱动 Skill 选择设计

## 背景

当前复现任务的入口已经能从用户输入中解析 GitHub URL，并通过后端 Agent Loop 执行 `lab4ai-auto-reproduct` 的 `project_reproduce.yaml` workflow。问题在于 skill 选择仍由程序规则直接决定：只要任务类型是 `reproduce` 或 metadata 中存在 `github_url`，后端就选择 `lab4ai-auto-reproduct`。

目标是让大模型参与 skill 选择：当用户输入“帮我复现这个项目：https://github.com/jsnzwu/motion-guided-flow”时，模型基于用户意图和可用 skill 摘要选择 `lab4ai-auto-reproduct`。后端再加载该 skill 绑定的 workflow 并执行。现有规则保留为 fallback，保证模型未配置或调用失败时流程仍可运行。

## 范围

本设计只调整 skill 选择链路，不改变 workflow 的执行语义。

包含：
- 新增模型优先的 skill selection 阶段。
- 保留当前 reproduce/GitHub URL 规则作为 fallback。
- 将模型选择结果、fallback 原因和最终选择写入 conversation metadata。
- 确保 workflow 文件仍由后端从 skill registry 中加载。
- 增加后端测试覆盖模型选择、失败回退和 workflow 加载路径。

不包含：
- 不改写 `skills/` 目录中的 skill 模板。
- 不改变 `project_reproduce.yaml` 的 step 定义、顺序和 allowed_tools。
- 不让模型直接传入 workflow 文件路径。
- 不扩大 ToolRegistry 的工具权限。
- 不同时重构 workflow runner 或 Lab4AI/SSH 执行器。

## 推荐方案

采用“模型优先选择 skill，现有规则 fallback”的方案。

流程如下：

```text
用户输入
  -> 前端解析 github_url / paper_url / user_prompt
  -> 后端创建 conversation metadata
  -> Agent Loop 加载所有 skill 的安全摘要
  -> 如果 LLM 配置可用，调用模型选择 skill
  -> 后端校验模型返回的 skill_name
  -> 校验通过则使用模型选择结果
  -> 校验失败或模型不可用则使用 fallback 规则
  -> 后端按最终 skill 加载 workflow_context
  -> SkillWorkflowRunner 按 project_reproduce.yaml 执行
```

模型只决定 `skill_name`，不决定 workflow 路径、不决定执行顺序、不绕过 ToolRegistry。

## 组件边界

### SkillLoader

继续负责扫描 `skills/*/SKILL.md`，加载 skill 元信息。对于 `lab4ai-auto-reproduct`，继续加载 `project_reproduce.yaml` 到 `workflow_context`。

后续可增加一个只读摘要方法，返回模型可见字段：
- `name`
- `description`
- `when_to_use`
- `triggers`
- `allowed_tools`
- `has_workflow`

### SkillSelector

新增独立服务，负责 skill 选择。它接收：
- 用户最近输入。
- conversation metadata。
- 当前可用 skill 摘要。
- LLM runtime config。

它返回：

```python
class SkillSelectionResult:
    skill_name: str
    reason: str
    confidence: float
    source: Literal["model", "fallback"]
    error: str | None = None
```

`SkillSelector` 不执行 workflow，也不调用 ToolRegistry。

### AgentLoopManager

Agent Loop 不再直接调用规则函数选择 skill，而是调用 `SkillSelector`。拿到最终 skill 后，继续执行现有逻辑：
- 构建 system prompt。
- 注入 skill prompt context。
- 如果 skill 有 workflow_context，则 `parse_workflow()`。
- 交给 `SkillWorkflowRunner` 执行。

### SkillWorkflowRunner

保持现有职责。workflow step 顺序、allowed_tools、HITL、资源释放和合约校验仍由后端控制。

## 模型选择方式

优先使用 Anthropic-compatible tool-use 进行结构化选择。模型可调用一个后端声明的内部工具，例如 `select_skill`。该工具不产生副作用，只用于让模型输出结构化选择。

工具输入由模型生成，但后端只接受以下字段：

```json
{
  "skill_name": "lab4ai-auto-reproduct",
  "reason": "用户提供 GitHub 仓库并要求复现项目",
  "confidence": 0.93
}
```

如果当前兼容端点不稳定支持 tool-use，可以在第一阶段使用严格 JSON 输出作为降级实现，但最终接口仍应收敛到同一个 `SkillSelectionResult`。

## Fallback 规则

以下情况触发 fallback：
- 用户未配置 LLM API Key。
- 模型请求超时、网络失败或返回空结果。
- 模型输出无法解析。
- 模型返回的 `skill_name` 不在当前 skill registry 中。
- 当前任务需要 workflow，但模型选择的 skill 没有 workflow。
- `confidence < 0.6`。

fallback 规则保留当前语义：

```text
metadata.task_type == reproduce 或 metadata.github_url 存在
  => lab4ai-auto-reproduct

否则
  => general-chat 或普通对话路径
```

fallback 只在模型不可用或模型选择无效时触发。模型返回合法 skill 时，不再用规则覆盖模型选择。

## 安全约束

- 模型只能返回 skill 名称。
- 后端只接受 `SkillLoader` registry 中存在的 skill。
- 模型不能指定 YAML 路径、远程 URL、脚本入口或任意本地路径。
- workflow 文件路径由后端根据 skill 固定解析。
- `project_reproduce.yaml` 必须通过 `parse_workflow()`。
- workflow 内的工具调用仍受 step allowlist 和 ToolRegistry 控制。
- 高风险或计费操作继续经过 HITL 与审计 metadata。

## Metadata 记录

conversation metadata 中增加 `skill_selection` 字段，便于前端、日志和测试判断实际路径。

示例：

```json
{
  "skill_selection": {
    "selected_skill": "lab4ai-auto-reproduct",
    "source": "model",
    "model_choice": "lab4ai-auto-reproduct",
    "fallback_choice": null,
    "reason": "用户提供 GitHub 仓库并要求复现项目",
    "confidence": 0.93,
    "error": null
  }
}
```

fallback 示例：

```json
{
  "skill_selection": {
    "selected_skill": "lab4ai-auto-reproduct",
    "source": "fallback",
    "model_choice": "unknown-skill",
    "fallback_choice": "lab4ai-auto-reproduct",
    "reason": "模型返回的 skill 不存在，使用 reproduce fallback",
    "confidence": 0.2,
    "error": "unknown_skill"
  }
}
```

## 测试计划

后端单元测试：
- 模型返回 `lab4ai-auto-reproduct` 时，最终选择来源为 `model`。
- 未配置模型时，不请求模型，fallback 到 `lab4ai-auto-reproduct`。
- 模型返回未知 skill 时，fallback 到 `lab4ai-auto-reproduct` 并记录 `error`。
- 模型低置信度时，fallback 到 `lab4ai-auto-reproduct`。
- 无 GitHub URL 且非复现任务时，不误选 `lab4ai-auto-reproduct`。

集成级路径：
- 输入 `帮我复现这个项目：https://github.com/jsnzwu/motion-guided-flow`。
- metadata 中存在 `github_url`。
- 模型可用时，`skill_selection.source == "model"`。
- 最终 `skill_selection.selected_skill == "lab4ai-auto-reproduct"`。
- 后端加载 `project_reproduce.yaml` 并产生 workflow metadata。
- 前端显示“选择复现流程”和 workflow 看板。
- 模型不可用时，`skill_selection.source == "fallback"`，但 workflow 仍能启动。

## 验收标准

- skill 选择不再只依赖 `if github_url then lab4ai-auto-reproduct`。
- 模型可用且返回合法选择时，metadata 明确记录来源为 `model`。
- 模型不可用或选择无效时，现有复现流程不退化，metadata 明确记录来源为 `fallback`。
- workflow 执行仍由 `project_reproduce.yaml` 和后端 runner 控制。
- 新增测试能稳定覆盖模型选择成功、fallback 和无复现意图三类路径。
