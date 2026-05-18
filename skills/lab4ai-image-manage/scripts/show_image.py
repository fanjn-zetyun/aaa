import json
import os
import sys
import urllib.error
import urllib.request

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[misc, assignment]

API_URL = "https://tools.lab4ai.cn/api/v1/tools/images_list/invoke"


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    if httpx is not None:
        return httpx.post(url, json=payload, timeout=timeout).json()

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw) if raw.strip() else {"code": -1, "message": f"HTTP {e.code}", "data": []}
        except json.JSONDecodeError:
            return {"code": -1, "message": f"HTTP {e.code}: {raw[:500]}", "data": []}


def load_env_file(env_path: str = "/root/.openclaw/.env") -> None:
    """Load KEY=VALUE pairs from env file into process env."""
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ[key.strip()] = val.strip().strip('"').strip("'")


def show_images(paras: dict) -> dict:
    """
    Query image tags list from Lab4AI.

    Input example:
        paras = {"phone": "...", "password": "..."}

    Return example:
        {"code": 0, "message": "", "data": ["tag1", "tag2", ...]}
    """
    phone = paras.get("phone") or os.getenv("LAB4AI_PHONE")
    password = paras.get("password") or os.getenv("LAB4AI_PASSWORD")

    if not phone or not password:
        return {"code": -1, "message": "missing phone or password", "data": []}

    payload = {"phone": phone, "password": password}

    try:
        res_json = _post_json(API_URL, payload, timeout=30.0)
    except Exception as e:
        return {"code": -1, "message": f"request error: {str(e)}", "data": []}

    return {
        "code": res_json.get("code", -1),
        "message": res_json.get("message", "") or "",
        "data": res_json.get("data", []) or [],
    }


if __name__ == "__main__":
    load_env_file()

    if len(sys.argv) > 1:
        # CLI usage:
        # python show_image.py '{"phone":"xxx","password":"yyy"}'
        try:
            paras_arg = json.loads(sys.argv[1])
        except Exception as e:
            print(json.dumps({"code": -1, "message": f"invalid json arg: {str(e)}", "data": []}, ensure_ascii=False))
            sys.exit(1)
    else:
        # Default: read from env if args not provided.
        paras_arg = {}

    result = show_images(paras_arg)
    print(json.dumps(result, ensure_ascii=False))
