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
});
