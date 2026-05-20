import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost } from "../lib/api";

interface WelcomePageProps {
  title: string;
  placeholder: string;
  suggestions: string[];
  requireGithubUrl?: boolean;
  basePath?: string;
}

export default function WelcomePage({ title, placeholder, suggestions, requireGithubUrl = true, basePath = "/reproduce" }: WelcomePageProps) {
  const [input, setInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    setError("");
    setSubmitting(true);

    const { githubUrl, paperUrl, userPrompt } = parseTaskInput(input);

    if (requireGithubUrl && !githubUrl) {
      setError("请在消息中包含一个 GitHub URL");
      setSubmitting(false);
      return;
    }

    try {
      const inst = await apiPost<{ id: number }>("/api/conversations", {
        task_type: basePath.includes("search")
          ? "search"
          : basePath.includes("paper-only")
            ? "paper_only"
            : basePath.includes("experiments")
              ? "experiments"
              : basePath.includes("polish")
                ? "polish"
                : "reproduce",
        github_url: githubUrl || null,
        paper_url: paperUrl || null,
        user_prompt: userPrompt || null,
        original_input: input.trim(),
      });
      navigate(`${basePath}/task/${inst.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as FormEvent);
    }
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 py-8">
      <h1 className="text-hero-title font-serif text-[#333] tracking-wide mb-8">
        {title}
      </h1>

      <div className="w-full max-w-3xl">
        <form onSubmit={handleSubmit}>
          <div className="w-full flex flex-col rounded-2xl border border-slate-200 bg-white shadow-[0_12px_40px_-12px_rgba(0,0,0,0.05),0_1px_3px_rgba(0,0,0,0.02)] focus-within:border-slate-300 transition-colors">
            <div className="px-5 py-4">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={placeholder}
                rows={4}
                className="w-full text-chat-body text-slate-700 placeholder-slate-300 bg-transparent resize-none leading-relaxed"
              />
            </div>

            <div className="px-5 pb-4 pt-1 flex justify-between items-center border-t border-slate-100">
              <div className="flex items-center gap-2 text-ui-meta text-slate-400">
                <span>支持 GitHub URL + 自然语言指令</span>
              </div>
              <button
                type="submit"
                disabled={submitting || !input.trim()}
                className="w-[32px] h-[32px] flex items-center justify-center rounded-full bg-slate-800 hover:bg-slate-700 disabled:bg-slate-300 text-white transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              </button>
            </div>
          </div>
        </form>

        {error && (
          <p className="mt-3 text-ui-small text-red-500 text-center">{error}</p>
        )}

        <div className="mt-6 flex flex-wrap gap-2 justify-center">
          {suggestions.map((s) => (
            <button
              key={s}
              onClick={() => setInput(s)}
              className="px-3 py-1.5 rounded-full border border-slate-200 bg-white text-ui-small text-slate-500 hover:text-slate-700 hover:border-slate-300 transition-colors"
            >
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function parseTaskInput(input: string) {
  const githubMatch = input.match(/https?:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+/i);
  const paperMatch = input.match(/https?:\/\/(?:www\.)?arxiv\.org\/(?:abs|pdf)\/[A-Za-z0-9.:-]+(?:\.pdf)?/i);

  const githubUrl = cleanUrl(githubMatch?.[0] || "");
  const paperUrl = cleanUrl(paperMatch?.[0] || "");
  const userPrompt = cleanPrompt(
    input
      .replace(githubMatch?.[0] || "", "")
      .replace(paperMatch?.[0] || "", "")
  );

  return { githubUrl, paperUrl, userPrompt };
}

function cleanUrl(url: string) {
  return url.replace(/[)。），,.;；:：!?！？]+$/u, "");
}

function cleanPrompt(prompt: string) {
  return prompt
    .replace(/(?:论文|paper)\s*(?:链接|地址|url)?\s*[:：]/giu, " ")
    .replace(/(?:github|代码|仓库)\s*(?:链接|地址|url)?\s*[:：]/giu, " ")
    .replace(/^[\s。。，,.;；:：!?！？、/|-]+/u, "")
    .replace(/\s+/g, " ")
    .trim();
}
