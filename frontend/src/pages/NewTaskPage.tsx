import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost } from "../lib/api";

export default function NewTaskPage() {
  const [githubUrl, setGithubUrl] = useState("");
  const [paperUrl, setPaperUrl] = useState("");
  const [userPrompt, setUserPrompt] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const inst = await apiPost<{ id: number }>("/api/claw-instances", {
        github_url: githubUrl,
        paper_url: paperUrl || null,
        user_prompt: userPrompt || null,
      });
      navigate(`/tasks/${inst.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ maxWidth: 600, margin: "40px auto", padding: 24 }}>
      <h1>新建复现任务</h1>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 16 }}>
          <label>
            GitHub URL <span style={{ color: "red" }}>*</span>
          </label>
          <input
            type="url"
            value={githubUrl}
            onChange={(e) => setGithubUrl(e.target.value)}
            placeholder="https://github.com/org/repo"
            required
            style={{ width: "100%", padding: 8, marginTop: 4 }}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label>论文 URL（可选）</label>
          <input
            type="url"
            value={paperUrl}
            onChange={(e) => setPaperUrl(e.target.value)}
            placeholder="https://arxiv.org/abs/..."
            style={{ width: "100%", padding: 8, marginTop: 4 }}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label>自然语言指令（可选）</label>
          <textarea
            value={userPrompt}
            onChange={(e) => setUserPrompt(e.target.value)}
            placeholder="例如：只复现 Table 1 的结果"
            rows={3}
            style={{ width: "100%", padding: 8, marginTop: 4 }}
          />
        </div>
        {error && <p style={{ color: "red" }}>{error}</p>}
        <button type="submit" disabled={submitting} style={{ padding: "10px 24px" }}>
          {submitting ? "提交中..." : "提交任务"}
        </button>
      </form>
    </div>
  );
}
