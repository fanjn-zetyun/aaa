import { render, screen } from "@testing-library/react";
import { MarkdownContent } from "../components/MarkdownContent";

describe("MarkdownContent", () => {
  it("renders common markdown blocks including tables", () => {
    render(
      <MarkdownContent
        content={`# Title

> quoted text

1. first
2. second

- [x] done
- [ ] todo

| Name | Value |
| --- | ---: |
| A | 1 |
| B | 2 |

\`\`\`ts
const value = 1;
\`\`\`

[link](https://example.com)`}
      />
    );

    expect(screen.getByRole("heading", { name: "Title", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("quoted text")).toBeInTheDocument();
    expect(screen.getByText("first")).toBeInTheDocument();
    expect(screen.getByText("second")).toBeInTheDocument();

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[0]).toBeChecked();
    expect(checkboxes[1]).not.toBeChecked();

    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Value")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    expect(screen.getByText("const value = 1;")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "link" })).toHaveAttribute("href", "https://example.com");
  });

  it("marks reproduction workflow markdown and highlights status tokens", () => {
    render(
      <MarkdownContent
        variant="reproduction"
        content={`#### 复现流水线实时看板 \`PhotoDoodle\`

| 序号 | 执行步骤 (对应 YAML Task) | 当前状态 | 核心产出 / 详情 |
| :--- | :--- | :--- | :--- |
| 1 | \`step_1_audit\`: 项目与论文双重审计 | [完成] | score=80 |
| 2 | \`step_2_condition_check\`: 复现可行性熔断判断 | [执行中] | 正在判断 |
| 3 | \`step_3_deploy_cpu\`: 创建 CPU 实例 | [等待中] | 等待确认 |
| 4 | \`step_4_cpu_env_setup\`: 环境构建 | [中止] | SSH 失败 |`}
      />
    );

    expect(screen.getByTestId("markdown-content")).toHaveClass("markdown-reproduction");
    expect(screen.getByTestId("reproduction-status-done")).toHaveTextContent("[完成]");
    expect(screen.getByTestId("reproduction-status-running")).toHaveTextContent("[执行中]");
    expect(screen.getByTestId("reproduction-status-waiting")).toHaveTextContent("[等待中]");
    expect(screen.getByTestId("reproduction-status-error")).toHaveTextContent("[中止]");
  });

  it("does not apply reproduction status markup to default markdown", () => {
    render(<MarkdownContent content={`| A | B |
| --- | --- |
| [完成] | normal |`} />);

    expect(screen.getByTestId("markdown-content")).not.toHaveClass("markdown-reproduction");
    expect(screen.queryByTestId("reproduction-status-done")).not.toBeInTheDocument();
  });
});
