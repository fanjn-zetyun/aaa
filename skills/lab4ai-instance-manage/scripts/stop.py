import sys
import os
import json
import subprocess

try:
    import httpx
except ImportError:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "httpx"],
        stdout=sys.stderr,
    )
    import httpx

API_URL = "https://tools.lab4ai.cn/api/v1/tools/instance_stop/invoke"


def stop_instance(server_id: str) -> dict:
    """调用新 API 关闭实例，返回标准化结果。"""

    phone = os.getenv("LAB4AI_PHONE")
    password = os.getenv("LAB4AI_PASSWORD")

    if not phone or not password:
        return {"status": "failed", "msg": "环境变量 LAB4AI_PHONE / LAB4AI_PASSWORD 未设置"}

    if not server_id:
        return {"status": "failed", "msg": "未提供 serverId，无法关闭"}

    payload = {
        "phone": phone,
        "password": password,
        "serverId": server_id,
    }

    try:
        resp = httpx.post(API_URL, json=payload, timeout=30.0)
        res_json = resp.json()
    except Exception as e:
        return {"status": "failed", "msg": f"请求异常: {str(e)}"}

    if res_json.get("code") != 0:
        return {"status": "failed", "msg": res_json.get("message") or res_json.get("msg", "关机失败")}

    data = res_json.get("data", {})

    return {
        "status": "success",
        "serverId": server_id,
        "startTime": data.get("startTime"),
        "stopTime": data.get("stopTime"),
    }


if __name__ == "__main__":
    # 从 .env 加载环境变量
    env_path = os.path.expanduser("/root/.openclaw/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")

    server_id = sys.argv[1] if len(sys.argv) > 1 else ""
    result = stop_instance(server_id)
    print(json.dumps(result, ensure_ascii=False))
