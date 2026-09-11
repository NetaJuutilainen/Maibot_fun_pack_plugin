"""外部 API 客户端（纯逻辑，不依赖 maibot_sdk，可离线测试）。"""

from __future__ import annotations

import aiohttp

HITOKOTO_API = "https://v1.hitokoto.cn"


async def fetch_hitokoto(timeout: float = 10.0) -> dict:
    """请求一条一言，返回 {"hitokoto": str, "from": str, ...}；失败抛异常。"""
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        async with session.get(HITOKOTO_API) as resp:
            if resp.status != 200:
                raise RuntimeError(f"一言接口返回 HTTP {resp.status}")
            data = await resp.json()
    if not isinstance(data, dict) or not data.get("hitokoto"):
        raise RuntimeError("一言接口返回数据异常")
    return data
