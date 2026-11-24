"""外部 API 客户端（纯逻辑，不依赖 maibot_sdk，可离线测试）。"""

from __future__ import annotations

import re

import aiohttp

HITOKOTO_API = "https://v1.hitokoto.cn"
_QQ_ID_RE = re.compile(r"^\d{5,15}$")


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


def qq_avatar_url(user_id: str, size: int = 640) -> str | None:
    """构造 QQ 头像下载链接（仅接受 5~15 位纯数字 QQ 号），不合规返回 None。"""
    uid = str(user_id or "").strip()
    if not _QQ_ID_RE.fullmatch(uid):
        return None
    return f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s={int(size)}"


async def fetch_avatar_bytes(
    url: str,
    timeout: float = 8.0,
    max_bytes: int = 5 * 1024 * 1024,
) -> bytes | None:
    """异步下载头像字节流；分片读满至 EOF，协议非法、超时、非 200 或超限返回 None。"""
    target = str(url or "").strip()
    if not target.lower().startswith(("http://", "https://")):
        return None
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(
            timeout=timeout_cfg,
            trust_env=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as session:
            async with session.get(target) as resp:
                if resp.status != 200:
                    return None
                content_len = resp.headers.get("Content-Length")
                if content_len and content_len.isdigit() and int(content_len) > max_bytes:
                    return None
                buf = bytearray()
                async for chunk in resp.content.iter_chunked(65536):
                    if not chunk:
                        continue
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        return None
                if not buf:
                    return None
                return bytes(buf)
    except Exception:  # noqa: BLE001 - 头像获取失败允许降级为默认兜底图
        return None
