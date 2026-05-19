import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

interface LLMConfig {
  provider: string;
  base_url: string;
  model: string;
  max_tokens: number;
  api_key_configured: boolean;
}

interface LLMConfigTestResponse {
  ok: boolean;
  message: string;
}

export default function ModelSettingsPage() {
  const [provider, setProvider] = useState("anthropic");
  const [baseUrl, setBaseUrl] = useState("https://api.anthropic.com");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("claude-sonnet-4-6");
  const [maxTokens, setMaxTokens] = useState("4096");
  const [status, setStatus] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);

  useEffect(() => {
    apiFetch<LLMConfig>("/api/llm-config").then((cfg) => {
      setProvider(cfg.provider);
      setBaseUrl(cfg.base_url);
      setModel(cfg.model);
      setMaxTokens(String(cfg.max_tokens));
      setStatus(cfg.api_key_configured ? "已配置 API Key" : "尚未配置 API Key");
    });
  }, []);

  const payload = {
    provider,
    base_url: baseUrl,
    api_key: apiKey || null,
    model,
    max_tokens: Number(maxTokens),
  };

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setIsSaving(true);
    setStatus("");
    try {
      await apiFetch("/api/llm-config", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setApiKey("");
      setStatus("已保存，下一次对话会使用新的模型配置");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "保存失败");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleTest() {
    setIsTesting(true);
    setStatus("正在测试模型连通性...");
    try {
      const result = await apiFetch<LLMConfigTestResponse>("/api/llm-config/test", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setStatus(result.ok ? `连通性测试成功：${result.message}` : result.message);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "连通性测试失败");
    } finally {
      setIsTesting(false);
    }
  }

  return (
    <div className="flex-1 px-8 py-8 overflow-y-auto">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-[22px] font-semibold text-slate-800 mb-6">模型设置</h1>
        <form
          onSubmit={handleSubmit}
          className="space-y-4 bg-white border border-slate-200 rounded-xl p-5"
        >
          <Field label="Provider">
            <input
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Base URL">
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="API Key">
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className={inputClass}
              placeholder="留空表示不更新已保存的 Key"
            />
          </Field>
          <Field label="Model">
            <input value={model} onChange={(e) => setModel(e.target.value)} className={inputClass} />
          </Field>
          <Field label="Max Tokens">
            <input
              type="number"
              value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
              className={inputClass}
            />
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={isSaving || isTesting}
              className="px-4 py-2 rounded-lg bg-slate-800 text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSaving ? "保存中..." : "保存"}
            </button>
            <button
              type="button"
              onClick={handleTest}
              disabled={isSaving || isTesting}
              className="px-4 py-2 rounded-lg border border-slate-300 text-slate-700 bg-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isTesting ? "测试中..." : "测试连通性"}
            </button>
            <span className="text-sm text-slate-500">{status}</span>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-sm text-slate-600 mb-2">{label}</div>
      {children}
    </label>
  );
}

const inputClass =
  "w-full px-3 py-2 border border-slate-200 rounded-lg text-sm text-slate-700 bg-white";
