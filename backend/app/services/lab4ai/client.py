"""Lab4AI API 客户端：封装 instance-list / instance-stop 调用。"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(slots=True)
class Lab4AIInstance:
    server_id: str
    instance_id: str
    rule_name: str
    gpu_count: int
    ssh_host: str
    ssh_port: str
    ssh_user: str
    ssh_pass: str
    start_time: str


LIST_URL = "https://tools.lab4ai.cn/api/v1/tools/instance_list/invoke"
STOP_URL = "https://tools.lab4ai.cn/api/v1/tools/instance_stop/invoke"


async def list_instances(phone: str, password: str) -> list[Lab4AIInstance]:
    """查询当前账号下所有运行中的实例。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(LIST_URL, json={"phone": phone, "password": password})
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        return []

    instances: list[Lab4AIInstance] = []
    for item in data.get("data", {}).get("instances", []):
        instances.append(
            Lab4AIInstance(
                server_id=item.get("serverId", ""),
                instance_id=item.get("instanceId", ""),
                rule_name=item.get("ruleName", ""),
                gpu_count=item.get("gpuCount", 0),
                ssh_host=item.get("ssh_host", ""),
                ssh_port=item.get("ssh_port", ""),
                ssh_user=item.get("ssh_user", ""),
                ssh_pass=item.get("ssh_pass", ""),
                start_time=item.get("startTime", ""),
            )
        )
    return instances


async def stop_instance(phone: str, password: str, server_id: str) -> bool:
    """关停指定实例，返回是否成功。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            STOP_URL,
            json={"phone": phone, "password": password, "serverId": server_id},
        )
        resp.raise_for_status()
        data = resp.json()
    return data.get("code") == 0
