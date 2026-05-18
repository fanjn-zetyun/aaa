import sys
import os
import json
import re
import subprocess

try:
    import httpx
except ImportError:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "httpx"],
        stdout=sys.stderr,
    )
    import httpx

API_URL = "https://tools.lab4ai.cn/api/v1/tools/instance_create/invoke"

# 默认镜像标签
DEFAULT_IMAGE_TAG = "lf0.9.4-tf4.57.1-torch2.8.0-cu12.6-1.1"

# 默认来源
DEFAULT_SOURCE = "lab"


def parse_intent(intent_str: str) -> dict:
    """从自然语言描述中解析出 targetModel、资源数量、imageTag、source。"""

    result = {
        "targetModel": "CPU",
        "cpuCount": 2,
        "gpuCount": None,
        "imageTag": DEFAULT_IMAGE_TAG,
        "source": DEFAULT_SOURCE,
    }

    # ---- 机型识别 ----
    # targetModel 只接受 CPU 或 GPU
    if re.search(r"H800|H800A|H100|GPU|显卡|训练|H20", intent_str, re.I):
        result["targetModel"] = "GPU"

    # ---- 来源识别 ----
    source_match = re.search(r"source[=:]\s*(\w+)", intent_str, re.I)
    if source_match:
        result["source"] = source_match.group(1)

    # ---- 镜像识别 ----
    image_match = re.search(r"image[=:]\s*([\w.\-]+)", intent_str, re.I)
    if image_match:
        result["imageTag"] = image_match.group(1)

    # ---- 数量识别 ----
    # 清理掉型号关键词，避免干扰数字提取
    clean_str = re.sub(r"H800A|H800|H100|H20|\d+G|显存|image[=:][\w.\-]+|source[=:]\w+",
                       "", intent_str, flags=re.I)

    # 优先找 "N张/卡/核" 模式
    num_match = re.search(r"(\d+)\s*[张卡核]", clean_str)
    if not num_match:
        # 独立数字
        num_match = re.search(r"(?<![a-zA-Z])(\d+)(?![a-zA-Z])", clean_str)

    if num_match:
        count = int(num_match.group(1))
    else:
        count = 1 if result["targetModel"] == "GPU" else 2

    if result["targetModel"] == "GPU":
        result["gpuCount"] = count
    else:
        result["cpuCount"] = count

    return result


def create_instance(intent_str: str) -> dict:
    """调用 API 创建实例，返回标准化结果。"""

    phone = os.getenv("LAB4AI_PHONE")
    password = os.getenv("LAB4AI_PASSWORD")

    if not phone or not password:
        return {"status": "failed", "msg": "环境变量 LAB4AI_PHONE / LAB4AI_PASSWORD 未设置"}

    parsed = parse_intent(intent_str)

    payload = {
        "phone": phone,
        "password": password,
        "targetModel": parsed["targetModel"],
        "cpuCount": parsed["cpuCount"],
        "imageTag": parsed["imageTag"],
        "source": parsed["source"],
    }

    # GPU 时追加 gpuCount
    if parsed["targetModel"] == "GPU" and parsed["gpuCount"]:
        payload["gpuCount"] = parsed["gpuCount"]

    try:
        resp = httpx.post(API_URL, json=payload, timeout=60.0)
        res_json = resp.json()
    except Exception as e:
        return {"status": "failed", "msg": f"请求异常: {str(e)}"}

    if res_json.get("code") != 0:
        return {
            "status": "failed",
            "msg": res_json.get("message") or res_json.get("msg", "创建失败"),
        }

    data = res_json.get("data", {})

    return {
        "status": "success",
        "serverId": data.get("serverId"),
        "instanceId": data.get("instanceId"),
        "ssh_host": data.get("sshHost"),
        "ssh_port": str(data.get("sshPort", "")),
        "ssh_user": "root",
        "ssh_pass": data.get("sshPwd"),
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

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "CPU 2核"
    result = create_instance(query)
    print(json.dumps(result, ensure_ascii=False))
