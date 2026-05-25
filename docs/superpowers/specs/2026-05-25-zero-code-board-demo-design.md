# 零代码复现交互式演示看板设计

## 背景

用户希望录制“纯论文复现（无代码）”流程演示视频。演示需要从真实左侧入口进入，输入论文地址后展示 Agent 回复消息中的零代码复现流程看板，并保留 HITL 确认交互。演示不能创建真实 Lab4AI 实例、不能调用真实后端任务，也不能产生计费。

现有前端已经具备 `ZeroCodeAgentPanel`，可根据 `workflow.kind = zero_code_reproduction_pipeline` 的 metadata 渲染 12 步零代码复现看板。因此本次应复用现有面板，新增一个本地状态驱动的演示路径，而不是重写看板 UI。

## 已确认决策

1. 不新增或修改左侧导航入口。
2. 用户仍从现有“纯论文复现（无代码）”页面进入。
3. `/paper-only` 页面提交论文 URL 后进入演示路由，而不是创建真实 conversation。
4. 演示页展示聊天式体验：用户消息 + Agent 回复看板。
5. 演示数据使用真实形态的数据，例如 serverId、SSH、目录、插件、报告路径，不显示“mock”字样。
6. HITL 交互必须保留，但只更新前端本地演示状态，不调用 Lab4AI 或后端任务。

## 目标

- 从左侧现有“纯论文复现（无代码）”入口开始，完成录屏所需的自然路径。
- 用户在 `/paper-only` 输入论文 URL 后，跳转到 `/paper-only/demo/zero-code-board?paper_url=...`。
- 演示页显示一条用户气泡，内容来自输入的论文 URL 和复现请求。
- 演示页显示一条 Agent 气泡，内部复用 `ZeroCodeAgentPanel`。
- 初始看板停在 Step 0 `waiting_for_user`，展示创建远程 CPU 实例前的确认卡。
- 用户点击“创建远程 CPU 实例并开始”后，看板按本地状态推进，填入真实形态的 CPU/GPU 实例、SSH、路由、产出路径和报告路径。
- 用户点击“停止任务”后，看板进入 stopped/skipped 状态，说明未创建计费实例。
- 演示过程中不调用 `/api/conversations`、不调用 Lab4AI Tool、不写真实 conversation history。

## 非目标

- 不改 Agent Runtime 的真实执行逻辑。
- 不改 `skills/` 目录内容。
- 不新增左侧导航项。
- 不实现真实定时流式执行器；演示状态推进可由按钮触发后一次性更新到预设阶段。
- 不把演示数据写入数据库。
- 不改变 `/reproduce`、`/experiments`、`/search`、`/polish` 等入口行为。

## 路由与入口

新增前端路由：

```text
/paper-only/demo/zero-code-board
```

`PaperOnlyPage` 继续复用 `WelcomePage`，但通过新增配置让该页面提交时进入 demo 模式：

```text
/paper-only
  输入论文 URL
  -> navigate('/paper-only/demo/zero-code-board?paper_url=<encoded>')
```

`WelcomePage` 应保持通用，不把 demo 逻辑硬编码到所有入口。推荐为 `WelcomePage` 增加可选 `demoSubmitPath` 或 `onSubmitOverride`。`PaperOnlyPage` 传入该配置，其他页面保持原行为。

## 演示页结构

新增 `ZeroCodeBoardDemoPage`：

- 读取 `paper_url` query 参数。
- 生成用户消息文案，例如：`请基于这篇论文做纯论文无代码复现：<paper_url>`。
- 维护本地 `workflow`、`pendingInput`、`skillSelection` 状态。
- 使用与 `ChatPage` Agent 气泡一致的视觉结构展示：
  - 用户气泡
  - Agent 气泡
  - `ZeroCodeAgentPanel`
- `onSubmit` 只处理演示确认文本，不发送网络请求。

为了避免复制 `ZeroCodeAgentPanel`，应将其从 `ChatPage.tsx` 拆分到可复用组件，例如：

```text
frontend/src/components/ZeroCodeAgentPanel.tsx
```

拆分范围只包含零代码面板及其直接依赖的纯展示函数。若依赖过多，可以先导出一个更窄的 `ZeroCodeDemoPanel` 包装组件，但不得复制整段 UI 导致真实看板和演示看板分叉。

## 演示数据

演示数据必须像真实运行结果，但不声称来自真实实例。示例数据：

- 论文标题：`GeneCLR: A Context-Aware Protein Language Model for Defense System Discovery`
- 项目名：`geneclr-zero-code`
- CPU 实例：`serverId=lab4ai-cpu-20260525-083142-a19f`
- CPU 规格：`2C CPU / 8GB RAM`
- CPU SSH：`ssh -p 31247 root@compute.lab4ai.example`
- GPU 实例：`serverId=lab4ai-gpu-20260525-091806-b72c`
- GPU 规格：`1x H100 / 80GB VRAM`
- GPU SSH：`ssh -p 31892 root@gpu.lab4ai.example`
- 路由结果：`domain=CS_AI + BIOINFO`，`experiment_type=HYBRID`
- 激活插件：`zero-code-reproduction`, `zero-code-repro-csai`, `zero-code-repro-biodefense`
- 远程目录：`/workspace/user-data/codelab/geneclr-zero-code/`
- 脚手架目录：`/workspace/user-data/codelab/geneclr-zero-code/code/reproduction_scaffold/`
- 报告路径：`/workspace/user-data/codelab/geneclr-zero-code/code/reproduction_scaffold/CONFIDENCE_REPORT.md`

## 状态流程

初始状态：

- Workflow kind：`zero_code_reproduction_pipeline`
- Step 0：`waiting_for_user`
- Step 1-11：`pending`
- Gate Log：
  - `step_0_cpu_instance`: `unresolved / blocked`
  - `routing`: `unknown / pending`
  - `next_action`: `请确认是否创建远程 CPU 实例并开始零代码复现流水线。`
- Pending input：
  - 问题：`是否创建远程 CPU 实例并开始零代码复现流水线？`
  - 选项：`创建远程 CPU 实例并开始`、`停止任务`

确认继续后：

- Step 0-8：`completed`
- Step 9：`running`
- Step 10-11：`pending`
- Step 0 evidence 写入 CPU serverId、SSH、远程目录。
- Step 2 evidence 写入路由结果和激活插件。
- Step 4 expected output 可显示 `data_pipeline/ + models/ + training/ + configs/`。
- Step 8 expected output 显示 CPU 实例已释放和示例耗时。
- Step 9 expected output 显示 H100 轻量验证训练进行中。
- Gate Log `next_action` 更新为 `GPU 轻量验证训练进行中，等待训练日志与 loss 下降验证。`
- Pending input 清空。

停止后：

- Step 0：`skipped` 或 `stopped`
- Step 1-11：`pending`
- Workflow status：`stopped`
- Gate Log `step_0_cpu_instance`: `no / completed`
- Gate Log `next_action`: `演示任务已停止，未创建计费实例。`
- Pending input 清空。

## HITL 行为

HITL 使用现有 `HumanInputPanel` 的视觉体验。演示页传入的 `pendingInput` 必须绑定 `workflow_step_id=step_0_remote_instance_init`，使确认卡出现在 Step 0 行下方。

`onSubmit` 行为：

- 输入包含 `创建`、`开始`、`继续` 或点击继续按钮：进入确认继续后的演示状态。
- 输入包含 `停止`、`取消`：进入停止状态。
- 其他输入不改变状态，可在 Agent 气泡下方保留当前等待确认状态。

## 测试策略

- 添加 `WelcomePage` 或 `PaperOnlyPage` 测试：`/paper-only` 提交论文 URL 时跳转 demo 路由，不调用 `/api/conversations`。
- 添加 demo 页面测试：初始渲染用户气泡、`zero-code-agent-panel`、Step 0 等待确认卡。
- 添加 demo 页面测试：点击“创建远程 CPU 实例并开始”后，出现 CPU serverId、GPU serverId、路由插件、Step 9 running。
- 添加 demo 页面测试：点击“停止任务”后，显示未创建计费实例和 stopped/skipped 状态。
- 保留既有 `ChatPage` 测试，确保真实 conversation 的零代码看板不受影响。

## 验收标准

- 左侧导航不出现新增入口。
- `/paper-only` 输入论文地址后进入演示页。
- 页面看起来像一次真实 Agent 对话，而不是孤立组件展示。
- HITL 确认卡可点击，点击后看板状态发生变化。
- 演示数据包含真实形态的 CPU/GPU `serverId`、SSH、路由插件和产出路径。
- 无任何真实 Lab4AI API 或 conversation 创建请求。
- `npm run test:run` 和 `npm run build` 通过。
