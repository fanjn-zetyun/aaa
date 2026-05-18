import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFormPost, setToken } from "../lib/api";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      if (isRegister) {
        const res = await fetch("/api/auth/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || "注册失败");
        }
      }
      const data = await apiFormPost<{ access_token: string }>(
        "/api/auth/login",
        { username, password }
      );
      setToken(data.access_token);
      navigate("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-[#F8F9FA] font-sans">
      <div className="w-full max-w-[380px] mx-4">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2 mb-8">
          <svg className="w-6 h-6 text-orange-600" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v1.85c2.95 1.3 5 4.25 5 7.65 0 1.61-.46 3.1-1.2 4.36z" />
          </svg>
          <span className="font-bold tracking-widest text-slate-800 text-[18px]">LOBSTER</span>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-[0_12px_40px_-12px_rgba(0,0,0,0.05),0_1px_3px_rgba(0,0,0,0.02)] border border-slate-100 p-8">
          <h1 className="text-[1.4rem] font-serif text-center text-slate-800 mb-6">
            {isRegister ? "创建账号" : "欢迎回来"}
          </h1>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <input
                type="text"
                placeholder="用户名"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                className="w-full px-4 py-3 rounded-xl border border-slate-200 text-[14px] text-slate-700 placeholder-slate-300 bg-slate-50 focus:bg-white focus:border-slate-300 transition-colors"
              />
            </div>
            <div>
              <input
                type="password"
                placeholder="密码"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
                className="w-full px-4 py-3 rounded-xl border border-slate-200 text-[14px] text-slate-700 placeholder-slate-300 bg-slate-50 focus:bg-white focus:border-slate-300 transition-colors"
              />
            </div>

            {error && <p className="text-[13px] text-red-500">{error}</p>}

            <button
              type="submit"
              className="w-full py-3 rounded-xl bg-slate-800 text-white text-[14px] font-medium hover:bg-slate-700 transition-colors"
            >
              {isRegister ? "注册并登录" : "登录"}
            </button>
          </form>

          <div className="mt-5 text-center">
            <button
              onClick={() => setIsRegister(!isRegister)}
              className="text-[13px] text-slate-400 hover:text-slate-600 transition-colors"
            >
              {isRegister ? "已有账号？去登录" : "没有账号？去注册"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
