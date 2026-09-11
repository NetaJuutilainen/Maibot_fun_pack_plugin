"""data_dir JSON 持久化（纯逻辑，不依赖 maibot_sdk）。

文件 IO 是同步的，调用方（plugin.py）负责放 asyncio.to_thread，避免阻塞 Runner 事件循环。
"""

from __future__ import annotations

import datetime
import json
import random
import shutil
from pathlib import Path

TIME_FMT = "%Y-%m-%d %H:%M:%S"


class FoodStore:
    """食物清单。首次加载时若 data_dir 中无文件，则从插件 assets 复制初始清单。"""

    def __init__(self, path: Path, default_asset: Path | None = None) -> None:
        self.path = Path(path)
        self.default_asset = Path(default_asset) if default_asset else None
        self.items: list[str] = []

    def load(self) -> None:
        if not self.path.exists() and self.default_asset and self.default_asset.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.default_asset, self.path)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = data.get("data") if isinstance(data, dict) else data
            self.items = [str(i) for i in (items or [])]
        else:
            self.items = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"data": self.items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, names) -> int:
        added = 0
        for name in names:
            name = str(name).strip()
            if name and name not in self.items:
                self.items.append(name)
                added += 1
        return added

    def remove(self, names) -> int:
        removed = 0
        for name in names:
            name = str(name).strip()
            if name in self.items:
                self.items.remove(name)
                removed += 1
        return removed

    def choice(self) -> str:
        return random.choice(self.items) if self.items else "随便"


class AnswerBook:
    """答案之书词条库（只读，来自插件 assets/answer_book.json）。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.answers: list[str] = []

    def load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            entries = data.get("answers") if isinstance(data, dict) else data
            self.answers = [str(a).strip() for a in (entries or []) if str(a).strip()]
        else:
            self.answers = []

    def choice(self) -> str:
        return random.choice(self.answers) if self.answers else "答案之书今天是空白的，明天再来看看吧"


class GoodMorningStore:
    """早晚安作息记录。

    结构：{stream_id: {user_id: {"daily": {"morning_time": str, "night_time": str}}}}
    时间均为 UTC+8 的 "%Y-%m-%d %H:%M:%S" 字符串。
    原版插件写文件时丢了 "good_morning" 包装层导致重启丢数据，这里读写闭环修复。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict = {}

    def load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            # 兼容两种历史形态：{"good_morning": {...}} 或裸 {stream_id: {...}}
            data = raw.get("good_morning", raw) if isinstance(raw, dict) else {}
            self.data = data if isinstance(data, dict) else {}
        else:
            self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"good_morning": self.data}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def user_record(self, stream_id: str, user_id: str) -> dict:
        umo = self.data.setdefault(stream_id, {})
        user = umo.setdefault(user_id, {})
        daily = user.setdefault("daily", {})
        daily.setdefault("morning_time", "")
        daily.setdefault("night_time", "")
        return user

    def count_sleeping_today(self, stream_id: str, day_of_month: int) -> int:
        """统计本会话今天说过晚安且尚未说早安的人数（沿用原版按"日"判断的口径）。"""
        umo = self.data.get(stream_id, {})
        count = 0
        for record in umo.values():
            daily = record.get("daily", {})
            night = daily.get("night_time", "")
            morning = daily.get("morning_time", "")
            if night and not morning:
                try:
                    if datetime.datetime.strptime(night, TIME_FMT).day == day_of_month:
                        count += 1
                except ValueError:
                    continue
        return count
