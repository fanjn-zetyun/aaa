import sys
import os
import json
import httpx

API_URL = "https://tools.lab4ai.cn/api/v1/tools/instance_running_list/invoke"

DEFAULT_SOURCE = "lab"


def list_running_instances(source=DEFAULT_SOURCE):
    """查询当前运行中的实例列表。"""

    phone = os.getenv("LAB4AI_PHONE")
    password = os.getenv("LAB4AI_PASSWORD")

    if not phone or not password:
        return {"status": "failed", "msg": "环境变量 LAB4AI_PHONE / LAB4AI_PASSWORD 未设置"}

    payload = {
        "phone": phone,
        "password": password,
        "source": source,
    }

    try:
        resp = httpx.post(API_URL, json=payload, timeout=30.0)
        res_json = resp.json()
    except Exception as e:
        return {"status": "failed", "msg": f"请求异常: {str(e)}"}

    if res_json.get("code") != 0:
        return {
            "status": "failed",
            "msg": res_json.get("message") or res_json.get("msg", "查询失败"),
            "hint": "如果持续报 '获取用户信息异常'，可能是平台 API 临时故障，请稍后重试或联系平台支持",
        }

    data = res_json.get("data", [])

    instances = []
    for item in data:
        inst = {
            "serverId": item.get("serverId"),
            "instanceId": item.get("instanceId"),
            "ruleName": item.get("ruleName", ""),
            "ssh_host": item.get("sshHost"),
            "ssh_port": str(item.get("sshPort", "")),
            "ssh_user": item.get("sshUser", "root"),
            "ssh_pass": item.get("sshPwd"),
            "startTime": item.get("startTime"),
        }
        # CPU 实例附加 cpuCount，GPU 实例附加 gpuCount
        if item.get("ruleName", "").upper() == "CPU":
            inst["cpuCount"] = item.get("cpuCount")
        else:
            inst["gpuCount"] = item.get("gpuCount")
        instances.append(inst)

    result = {
        "status": "success",
        "count": len(instances),
        "instances": instances,
    }

    if len(instances) == 0:
        result["message"] = "当前无运行中的实例"

    return result


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

    # 可选参数: source
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    result = list_running_instances(source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
