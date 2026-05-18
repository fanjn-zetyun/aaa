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
      navigate("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "80px auto", padding: 24 }}>
      <h1>{isRegister ? "注册" : "登录"}</h1>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 12 }}>
          <input
            type="text"
            placeholder="用户名"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            style={{ width: "100%", padding: 8 }}
          />
        </div>
        <div style={{ marginBottom: 12 }}>
          <input
            type="password"
            placeholder="密码"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
            style={{ width: "100%", padding: 8 }}
          />
        </div>
        {error && <p style={{ color: "red" }}>{error}</p>}
        <button type="submit" style={{ width: "100%", padding: 10 }}>
          {isRegister ? "注册并登录" : "登录"}
        </button>
      </form>
      <p style={{ marginTop: 12, textAlign: "center" }}>
        <button
          onClick={() => setIsRegister(!isRegister)}
          style={{ background: "none", border: "none", color: "#0066cc", cursor: "pointer" }}
        >
          {isRegister ? "已有账号？去登录" : "没有账号？去注册"}
        </button>
      </p>
    </div>
  );
}
