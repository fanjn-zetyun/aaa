import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFormPost, setToken } from "../lib/api";

type ApiErrorDetail = string | Array<{ loc?: Array<string | number>; msg?: string }>;

export default function LoginPage() {
  const [phone, setPhone] = useState("");
  const [institution, setInstitution] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");

    const validationError = validateForm({ phone, institution, password, confirmPassword, isRegister });
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsSubmitting(true);
    try {
      if (isRegister) {
        const res = await fetch("/api/auth/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ phone, institution, password }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(formatAuthError(body.detail, "注册失败，请稍后重试"));
        }
      }
      const data = await apiFormPost<{ access_token: string }>("/api/auth/login", {
        username: phone,
        password,
      });
      setToken(data.access_token);
      navigate("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "操作失败，请稍后重试");
    } finally {
      setIsSubmitting(false);
    }
  }

  function toggleMode() {
    setIsRegister((value) => !value);
    setError("");
    setConfirmPassword("");
  }

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-[#F8F9FA] font-sans">
      <div className="w-full max-w-[380px] mx-4">
        <div className="flex items-center justify-center gap-2 mb-8">
          <svg className="w-6 h-6 text-orange-600" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v1.85c2.95 1.3 5 4.25 5 7.65 0 1.61-.46 3.1-1.2 4.36z" />
          </svg>
          <span className="font-bold tracking-widest text-slate-800 text-ui-title">LOBSTER</span>
        </div>

        <div className="bg-white rounded-2xl shadow-[0_12px_40px_-12px_rgba(0,0,0,0.05),0_1px_3px_rgba(0,0,0,0.02)] border border-slate-100 p-8">
          <h1 className="text-auth-title font-serif text-center text-slate-800 mb-6">
            {isRegister ? "创建账号" : "欢迎回来"}
          </h1>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div>
              <input
                type="text"
                inputMode="tel"
                placeholder="手机号"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                aria-label="手机号"
                className="w-full px-4 py-3 rounded-xl border border-slate-200 text-ui-body text-slate-700 placeholder-slate-300 bg-slate-50 focus:bg-white focus:border-slate-300 transition-colors"
              />
            </div>

            {isRegister && (
              <div>
                <input
                  type="text"
                  placeholder="机构/学校"
                  value={institution}
                  onChange={(e) => setInstitution(e.target.value)}
                  aria-label="机构/学校"
                  className="w-full px-4 py-3 rounded-xl border border-slate-200 text-ui-body text-slate-700 placeholder-slate-300 bg-slate-50 focus:bg-white focus:border-slate-300 transition-colors"
                />
              </div>
            )}

            <div>
              <input
                type="password"
                placeholder="密码"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-label="密码"
                className="w-full px-4 py-3 rounded-xl border border-slate-200 text-ui-body text-slate-700 placeholder-slate-300 bg-slate-50 focus:bg-white focus:border-slate-300 transition-colors"
              />
            </div>

            {isRegister && (
              <div>
                <input
                  type="password"
                  placeholder="确认密码"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  aria-label="确认密码"
                  className="w-full px-4 py-3 rounded-xl border border-slate-200 text-ui-body text-slate-700 placeholder-slate-300 bg-slate-50 focus:bg-white focus:border-slate-300 transition-colors"
                />
              </div>
            )}

            {error && <p className="text-ui-small text-red-500">{error}</p>}

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-3 rounded-xl bg-slate-800 text-white text-ui-body font-medium hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300 transition-colors"
            >
              {isSubmitting ? (isRegister ? "注册中..." : "登录中...") : isRegister ? "注册并登录" : "登录"}
            </button>
          </form>

          <div className="mt-5 text-center">
            <button
              type="button"
              onClick={toggleMode}
              className="text-ui-small text-slate-400 hover:text-slate-600 transition-colors"
            >
              {isRegister ? "已有账号？去登录" : "没有账号？去注册"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function validateForm({
  phone,
  institution,
  password,
  confirmPassword,
  isRegister,
}: {
  phone: string;
  institution: string;
  password: string;
  confirmPassword: string;
  isRegister: boolean;
}) {
  if (!phone.trim()) return "请输入手机号";
  const loginId = phone.trim().replace(/\s+/g, "");
  const isAdminBackdoor = !isRegister && loginId === "admin";
  if (!isAdminBackdoor && !/^(\+?86)?1[3-9]\d{9}$/.test(loginId)) {
    return "请输入有效的中国大陆手机号";
  }
  if (isRegister && !institution.trim()) return "请输入机构或学校名称";
  if (!password) return "请输入密码";
  if (password.length < 6) return "密码至少需要 6 位";
  if (isRegister && !confirmPassword) return "请再次输入密码";
  if (isRegister && password !== confirmPassword) return "两次输入的密码不一致";
  return "";
}

function formatAuthError(detail: ApiErrorDetail | undefined, fallback: string) {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  const first = detail[0];
  const field = first?.loc?.at(-1);
  if (field === "phone") return "请输入有效的中国大陆手机号";
  if (field === "institution") return "请输入机构或学校名称";
  if (field === "password") return "密码至少需要 6 位";
  return first?.msg || fallback;
}
