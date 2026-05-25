import type { ComponentPropsWithoutRef, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

interface MarkdownContentProps {
  content: string;
  variant?: MarkdownVariant;
}

type MarkdownVariant = "default" | "reproduction" | "workspace";

const markdownComponents = (variant: MarkdownVariant): Components => ({
  h1: ({ children, ...props }: ComponentPropsWithoutRef<"h1">) => (
    <h1 className="text-md-h1 font-semibold leading-snug text-slate-800" {...props}>
      {children}
    </h1>
  ),
  h2: ({ children, ...props }: ComponentPropsWithoutRef<"h2">) => (
    <h2 className="text-md-h2 font-semibold leading-snug text-slate-800" {...props}>
      {children}
    </h2>
  ),
  h3: ({ children, ...props }: ComponentPropsWithoutRef<"h3">) => (
    <h3 className="text-md-h3 font-semibold leading-snug text-slate-700" {...props}>
      {children}
    </h3>
  ),
  h4: ({ children, ...props }: ComponentPropsWithoutRef<"h4">) => (
    <h4 className="text-chat-body font-semibold leading-snug text-slate-700" {...props}>
      {children}
    </h4>
  ),
  h5: ({ children, ...props }: ComponentPropsWithoutRef<"h5">) => (
    <h5 className="text-chat-body font-semibold leading-snug text-slate-700" {...props}>
      {children}
    </h5>
  ),
  h6: ({ children, ...props }: ComponentPropsWithoutRef<"h6">) => (
    <h6 className="text-chat-body font-semibold leading-snug text-slate-700" {...props}>
      {children}
    </h6>
  ),
  p: ({ children, ...props }: ComponentPropsWithoutRef<"p">) => (
    <p className="leading-relaxed" {...props}>
      {children}
    </p>
  ),
  a: ({ children, href, ...props }: ComponentPropsWithoutRef<"a">) => (
    <a
      href={href}
      target={href?.startsWith("#") ? undefined : "_blank"}
      rel={href?.startsWith("#") ? undefined : "noreferrer"}
      className="text-blue-600 hover:underline"
      {...props}
    >
      {children}
    </a>
  ),
  ul: ({ children, className, ...props }: ComponentPropsWithoutRef<"ul">) => (
    <ul className={`space-y-1 ${className?.includes("contains-task-list") ? "" : "list-disc pl-5"}`} {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }: ComponentPropsWithoutRef<"ol">) => (
    <ol className="list-decimal space-y-1 pl-5" {...props}>
      {children}
    </ol>
  ),
  li: ({ children, className, ...props }: ComponentPropsWithoutRef<"li">) => (
    <li className={className?.includes("task-list-item") ? "flex items-start gap-2" : undefined} {...props}>
      {children}
    </li>
  ),
  input: (props: ComponentPropsWithoutRef<"input">) => (
    <input
      className="mt-1 h-3.5 w-3.5 shrink-0 rounded border-slate-300 accent-slate-700"
      readOnly
      {...props}
    />
  ),
  blockquote: ({ children, ...props }: ComponentPropsWithoutRef<"blockquote">) => (
    <blockquote className="border-l-4 border-slate-200 pl-3 text-slate-600" {...props}>
      {children}
    </blockquote>
  ),
  hr: (props: ComponentPropsWithoutRef<"hr">) => <hr className="my-3 border-slate-200" {...props} />,
  table: ({ children, ...props }: ComponentPropsWithoutRef<"table">) => (
    <div className="max-w-full overflow-x-auto rounded-lg border border-slate-200">
      <table
        className={`min-w-full border-collapse text-ui-small ${
          variant === "reproduction" ? "reproduction-markdown-table" : ""
        }`}
        {...props}
      >
        {children}
      </table>
    </div>
  ),
  thead: ({ children, ...props }: ComponentPropsWithoutRef<"thead">) => (
    <thead className="bg-slate-50" {...props}>
      {children}
    </thead>
  ),
  th: ({ children, align, ...props }: ComponentPropsWithoutRef<"th">) => (
    <th
      className={`border-b border-slate-200 px-3 py-2 align-top font-semibold text-slate-700 ${alignClass(align)}`}
      {...props}
    >
      {children}
    </th>
  ),
  tr: ({ children, ...props }: ComponentPropsWithoutRef<"tr">) => (
    <tr className="odd:bg-white even:bg-slate-50/50" {...props}>
      {children}
    </tr>
  ),
  td: ({ children, align, ...props }: ComponentPropsWithoutRef<"td">) => (
    <td className={`border-t border-slate-100 px-3 py-2 align-top text-slate-600 ${alignClass(align)}`} {...props}>
      {variant === "reproduction" ? renderReproductionCell(children) : children}
    </td>
  ),
  code: ({ children, className, ...props }: ComponentPropsWithoutRef<"code">) => {
    const language = className?.match(/language-(\w+)/)?.[1];
    return (
      <code
        data-language={language}
        className={
          language
            ? "bg-transparent p-0 text-ui-small text-slate-100"
            : "rounded bg-slate-100 px-1 py-0.5 text-ui-small text-slate-700"
        }
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children, ...props }: ComponentPropsWithoutRef<"pre">) => (
    <pre
      className="overflow-x-auto rounded-lg bg-slate-900 px-3 py-2 text-ui-small leading-relaxed text-slate-100"
      {...props}
    >
      {children}
    </pre>
  ),
  strong: ({ children, ...props }: ComponentPropsWithoutRef<"strong">) => (
    <strong className="font-semibold text-slate-700" {...props}>
      {children}
    </strong>
  ),
  del: ({ children, ...props }: ComponentPropsWithoutRef<"del">) => (
    <del className="text-slate-500" {...props}>
      {children}
    </del>
  ),
});

export function MarkdownContent({ content, variant = "default" }: MarkdownContentProps) {
  return (
    <div
      data-testid="markdown-content"
      className={`space-y-3 whitespace-normal break-words ${
        variant === "reproduction"
          ? "markdown-reproduction"
          : variant === "workspace"
            ? "markdown-workspace text-ui-small leading-relaxed text-slate-700"
            : ""
      }`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={markdownComponents(variant)}
        urlTransform={normalizeHref}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function renderReproductionCell(children: ReactNode) {
  const text = reactNodeText(children).trim();
  const status = reproductionStatus(text);
  if (!status) return children;
  return (
    <span
      data-testid={`reproduction-status-${status}`}
      className={`reproduction-status reproduction-status-${status}`}
    >
      {children}
    </span>
  );
}

function reactNodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(reactNodeText).join("");
  return "";
}

function reproductionStatus(text: string) {
  if (!/^\[.+\]$/.test(text)) return null;
  if (text.includes("完成") || text.includes("通过")) return "done";
  if (text.includes("执行中") || text.includes("运行中")) return "running";
  if (text.includes("等待")) return "waiting";
  if (text.includes("中止") || text.includes("失败")) return "error";
  return null;
}

function normalizeHref(href: string) {
  if (!href) return null;
  const trimmed = href.trim();
  if (/^(https?:|mailto:)/i.test(trimmed)) return trimmed;
  if (trimmed.startsWith("#") || trimmed.startsWith("/")) return trimmed;
  return null;
}

function alignClass(align: string | undefined) {
  if (align === "right") return "text-right";
  if (align === "center") return "text-center";
  return "text-left";
}
