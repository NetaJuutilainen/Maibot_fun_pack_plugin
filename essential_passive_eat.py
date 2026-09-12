"""被动"吃什么"触发模块（纯逻辑，不依赖 maibot_sdk，可离线测试）。

设计移植自 astrbot_plugin_what_to_eat（MIT License，作者 C₂₂H₂₅NO₆）：
监听含关键词的消息，按概率推荐食物或复读"是啊，吃什么"；
带频率限制（防多 Bot 循环）与复读冷却，支持按食物名绑定图片。
"""

from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


class PassiveRateLimiter:
    """按会话记录响应频率：窗口内超限或处于复读冷却时，强制推荐而非复读。"""

    def __init__(
        self,
        max_responses: int = 3,
        window_seconds: int = 60,
        echo_cooldown_enabled: bool = True,
        echo_cooldown_seconds: int = 15,
    ) -> None:
        self.max_responses = max(1, int(max_responses))
        self.window_seconds = int(window_seconds)
        self.echo_cooldown_enabled = bool(echo_cooldown_enabled)
        self.echo_cooldown_seconds = max(0, min(3600, int(echo_cooldown_seconds)))
        # {chat_key: [timestamp, ...]}
        self._response_history: dict[str, list[float]] = {}
        # {chat_key: last_echo_timestamp}
        self._echo_cooldown_map: dict[str, float] = {}

    def check_and_record(self, chat_key: str) -> tuple[bool, bool]:
        """原子地检查并记录一次响应，返回 (can_respond, force_recommend)。"""
        if not chat_key:
            return True, False
        self._cleanup_old_records(chat_key)
        history = self._response_history.get(chat_key, [])
        force_recommend = len(history) >= self.max_responses
        self._response_history.setdefault(chat_key, []).append(time.time())
        return True, force_recommend

    def _cleanup_old_records(self, chat_key: str) -> None:
        if chat_key not in self._response_history:
            return
        cutoff = time.time() - self.window_seconds
        self._response_history[chat_key] = [
            ts for ts in self._response_history[chat_key] if ts > cutoff
        ]
        if not self._response_history[chat_key]:
            del self._response_history[chat_key]

    def is_in_echo_cooldown(self, chat_key: str) -> bool:
        if not self.echo_cooldown_enabled or not chat_key:
            return False
        self._cleanup_echo_cooldown()
        last = self._echo_cooldown_map.get(chat_key)
        return last is not None and time.time() - last < self.echo_cooldown_seconds

    def record_echo(self, chat_key: str) -> None:
        if chat_key and self.echo_cooldown_enabled:
            self._echo_cooldown_map[chat_key] = time.time()

    def _cleanup_echo_cooldown(self) -> None:
        if not self._echo_cooldown_map:
            return
        cutoff = time.time() - (self.echo_cooldown_seconds * 2 + 1)
        expired = [k for k, ts in self._echo_cooldown_map.items() if ts < cutoff]
        for k in expired:
            del self._echo_cooldown_map[k]


class PassiveResponder:
    """概率决策与回复文案。"""

    ECHO_RESPONSE = "是啊，吃什么"
    RECOMMEND_TEMPLATES = [
        "要不吃{food}？",
        "试试{food}吧！",
        "{food}怎么样？",
        "推荐你吃{food}！",
        "今天吃{food}吧！",
        "{food}了解一下？",
    ]
    FALLBACK_RESPONSE = "我想不到推荐什么...你自己决定吧！"

    def __init__(self, probability: float = 0.3) -> None:
        self.probability = max(0.0, min(1.0, float(probability)))

    def should_recommend(self) -> bool:
        return random.random() < self.probability

    def get_echo_response(self) -> str:
        return self.ECHO_RESPONSE

    def get_food_response(self, food: str | None) -> str:
        if food is None:
            return self.FALLBACK_RESPONSE
        return random.choice(self.RECOMMEND_TEMPLATES).format(food=food)


class FoodImageIndex:
    """按文件名把图片绑定到食物：食物名.jpg、食物名_1.jpg、食物名-2.png 等。"""

    _SEQ_SUFFIX = re.compile(r"[_-]\d+$")

    def __init__(self, folder: Path, rescan_interval: float = 120.0) -> None:
        self.folder = Path(folder)
        self.rescan_interval = rescan_interval
        self._index: dict[str, list[Path]] = {}
        self._last_scan = 0.0
        self.reload()

    def reload(self) -> None:
        index: dict[str, list[Path]] = {}
        if self.folder.is_dir():
            try:
                for path in sorted(self.folder.iterdir()):
                    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                        continue
                    food = self._extract_food_name(path.name)
                    if food:
                        index.setdefault(food, []).append(path)
            except OSError as e:
                logger.warning("扫描食物图片目录失败: %s", e)
        self._index = index
        self._last_scan = time.time()

    @staticmethod
    def _extract_food_name(filename: str) -> str | None:
        stem = Path(filename).stem
        cleaned = FoodImageIndex._SEQ_SUFFIX.sub("", stem).strip()
        return cleaned or None

    def _maybe_rescan(self) -> None:
        # 图片文件夹可能被用户随时丢新图，低频自动重扫
        if time.time() - self._last_scan > self.rescan_interval:
            self.reload()

    def get_random_image(self, food: str | None) -> Path | None:
        if not food:
            return None
        self._maybe_rescan()
        paths = self._index.get(food.strip())
        if not paths:
            return None
        existing = [p for p in paths if p.is_file()]
        return random.choice(existing) if existing else None

    def foods_with_images(self) -> list[str]:
        return sorted(self._index)
