"""Lab4AI API 客户端：封装 instance-create / instance-list / instance-stop 调用。"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(slots=True)
class Lab4AIInstance:
    server_id: str
    instance_id: str = ""
    rule_name: str = ""
    cpu_count: int = 0
    gpu_count: int = 0
    ssh_host: str = ""
    ssh_port: str = ""
    ssh_user: str = "root"
    ssh_pass: str = ""
    start_time: str = ""
    raw_payload: dict | None = None


@dataclass(slots=True)
class Lab4AIStopResult:
    server_id: str
    start_time: str = ""
    stop_time: str = ""
    raw_payload: dict | None = None


CREATE_URL = "https://tools.lab4ai.cn/api/v1/tools/instance_create/invoke"
LIST_URL = "https://tools.lab4ai.cn/api/v1/tools/instance_running_list/invoke"
STOP_URL = "https://tools.lab4ai.cn/api/v1/tools/instance_stop/invoke"

DEFAULT_IMAGE_TAG = "lf0.9.4-tf4.57.1-torch2.8.0-cu12.6-1.1"
DEFAULT_SOURCE = "lab"


async def create_instance(
    phone: str,
    password: str,
    *,
    target_model: str,
    cpu_count: int = 2,
    gpu_count: int | None = None,
    image_tag: str = DEFAULT_IMAGE_TAG,
    source: str = DEFAULT_SOURCE,
) -> Lab4AIInstance:
    """创建 Lab4AI 实例并返回标准化连接信息。"""
    payload = {
        "phone": phone,
        "password": password,
        "targetModel": target_model,
        "cpuCount": cpu_count,
        "imageTag": image_tag,
        "source": source,
    }
    if target_model.upper() == "GPU" and gpu_count:
        payload["gpuCount"] = gpu_count

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(CREATE_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(data.get("message") or data.get("msg") or "Lab4AI 创建实例失败")

    item = data.get("data") or {}
    return _parse_instance(item, fallback_rule=target_model)


async def list_instances(phone: str, password: str) -> list[Lab4AIInstance]:
    """查询当前账号下所有运行中的实例。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            LIST_URL,
            json={"phone": phone, "password": password, "source": DEFAULT_SOURCE},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(data.get("message") or data.get("msg") or "Lab4AI 查询实例失败")

    instances: list[Lab4AIInstance] = []
    raw_items = data.get("data") or []
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("instances") or []
    for item in raw_items:
        instances.append(_parse_instance(item))
    return instances


async def stop_instance_details(phone: str, password: str, server_id: str) -> Lab4AIStopResult:
    """关停指定实例，返回标准化结果。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            STOP_URL,
            json={"phone": phone, "password": password, "serverId": server_id},
        )
        resp.raise_for_status()
        data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(data.get("message") or data.get("msg") or "Lab4AI 关停实例失败")
    item = data.get("data") or {}
    return Lab4AIStopResult(
        server_id=server_id,
        start_time=str(item.get("startTime") or ""),
        stop_time=str(item.get("stopTime") or ""),
        raw_payload=item,
    )


async def stop_instance(phone: str, password: str, server_id: str) -> bool:
    """关停指定实例，返回是否成功。"""
    try:
        await stop_instance_details(phone, password, server_id)
    except Exception:
        return False
    return True


def _parse_instance(item: dict, *, fallback_rule: str = "") -> Lab4AIInstance:
    rule_name = str(item.get("ruleName") or item.get("targetModel") or fallback_rule or "")
    return Lab4AIInstance(
        server_id=str(item.get("serverId") or ""),
        instance_id=str(item.get("instanceId") or ""),
        rule_name=rule_name,
        cpu_count=_as_int(item.get("cpuCount")),
        gpu_count=_as_int(item.get("gpuCount")),
        ssh_host=str(item.get("sshHost") or item.get("ssh_host") or ""),
        ssh_port=str(item.get("sshPort") or item.get("ssh_port") or ""),
        ssh_user=str(item.get("sshUser") or item.get("ssh_user") or "root"),
        ssh_pass=str(item.get("sshPwd") or item.get("ssh_pass") or ""),
        start_time=str(item.get("startTime") or ""),
        raw_payload=item,
    )


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
