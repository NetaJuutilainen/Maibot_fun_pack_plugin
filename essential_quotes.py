"""群友语录存储与旧数据迁移（纯逻辑 + 文件 IO，不依赖 maibot_sdk）。

投稿与随机抽取玩法参考/移植自 pan-ice 的 plugins-uumessage（MIT License）：
回复一张图片发 /投稿语录 收进本群语录库，/群友语录 随机抽一张回放。
本模块把原插件的 SQLite 索引换成**按群一个 JSON 索引**（与本插件其他功能的
持久化惯例一致），图片仍按 `{群号}/{sha256}.png` 落盘、按内容哈希去重。

文件 IO 是同步的，调用方（plugin.py）负责放 asyncio.to_thread，避免阻塞事件循环。

目录结构（data_dir = data/plugins/maibot.fun-pack/）：
    quotes_{group_id}.json          每群一个索引
    quote_images/{group_id}/{hash}.png
    quotes_migration.json           旧数据（uumessage）迁移标记，成功后不再重跑

旧数据迁移 migrate_legacy_uumessage()：
    只**读**旧插件目录（plugins/github.pan-ice.plugins-uumessage/data/）下的
    quotes.db 与 images/，把记录与图片复制进本插件数据目录；旧目录原样保留，
    迁移成功后写标记文件，之后不再重复执行。
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import sqlite3
import time
from pathlib import Path

INDEX_VERSION = 1
MIGRATION_MARKER = "quotes_migration.json"


class QuoteStore:
    """按群隔离的语录库：JSON 索引 + 图片文件，按图片内容哈希去重。"""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / "quote_images"
        self._cache: dict[str, list[dict]] = {}

    # -- 索引读写 -----------------------------------------------------------

    def _index_path(self, group_id: str) -> Path:
        return self.data_dir / f"quotes_{group_id}.json"

    def _load(self, group_id: str) -> list[dict]:
        if group_id not in self._cache:
            path = self._index_path(group_id)
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    quotes = data.get("quotes", []) if isinstance(data, dict) else []
                    self._cache[group_id] = [q for q in quotes if isinstance(q, dict)]
                except (json.JSONDecodeError, OSError):
                    self._cache[group_id] = []
            else:
                self._cache[group_id] = []
        return self._cache[group_id]

    def _save(self, group_id: str) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._index_path(group_id).write_text(
            json.dumps(
                {"version": INDEX_VERSION, "quotes": self._cache.get(group_id, [])},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    # -- 对外接口 -----------------------------------------------------------

    def count(self, group_id: str) -> int:
        return len(self._load(group_id))

    def add(
        self,
        group_id: str,
        user_id: str,
        nickname: str,
        image_hash: str,
        image_bytes: bytes,
        *,
        message_id: str = "",
        created_at: float | None = None,
        max_per_group: int = 500,
    ) -> tuple[bool, str]:
        """投稿一条语录。返回 (是否成功, 说明)；同一群内同一图片视为重复。"""
        quotes = self._load(group_id)
        if any(q.get("image_hash") == image_hash for q in quotes):
            return False, "duplicate"

        group_dir = self.images_dir / group_id
        group_dir.mkdir(parents=True, exist_ok=True)
        image_path = group_dir / f"{image_hash}.png"
        if not image_path.exists():
            image_path.write_bytes(image_bytes)

        quotes.append({
            "image_hash": image_hash,
            "file": image_path.name,
            "user_id": str(user_id),
            "user_nickname": str(nickname or ""),
            "message_id": str(message_id or ""),
            "created_at": float(created_at if created_at is not None else time.time()),
        })
        # 超上限时清理最旧（含图片文件）；原地删除，保证缓存与落盘同步收缩
        if max_per_group > 0 and len(quotes) > max_per_group:
            excess = len(quotes) - max_per_group
            stale = quotes[:excess]
            del quotes[:excess]
            for old in stale:
                old_path = self.images_dir / group_id / str(old.get("file") or "")
                try:
                    old_path.unlink(missing_ok=True)
                except OSError:
                    pass
        self._save(group_id)
        return True, "ok"

    def random(self, group_id: str) -> dict | None:
        """随机抽一条；索引里图片文件已丢失的条目顺手清掉。"""
        quotes = self._load(group_id)
        alive = [q for q in quotes if (self.images_dir / group_id / str(q.get("file") or "")).is_file()]
        if len(alive) != len(quotes):
            self._cache[group_id] = alive
            self._save(group_id)
        if not alive:
            return None
        return random.choice(alive)

    def read_image_b64(self, group_id: str, quote: dict) -> str | None:
        path = self.images_dir / group_id / str(quote.get("file") or "")
        try:
            return base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            return None

    # -- 旧数据迁移（uumessage） ---------------------------------------------

    def migrate_legacy_uumessage(self, legacy_data_dir: Path) -> dict:
        """把 uumessage 的 quotes.db + images/ 迁进本插件数据目录。

        只读旧库、复制图片，**不删除、不改写**旧插件目录里的任何东西；
        成功后写 quotes_migration.json 标记，重复调用直接跳过。
        """
        legacy_data_dir = Path(legacy_data_dir)
        db_path = legacy_data_dir / "quotes.db"
        report: dict = {
            "skipped": False, "imported": 0, "duplicate": 0,
            "missing_image": 0, "source": str(db_path),
        }
        marker = self.data_dir / MIGRATION_MARKER
        if marker.exists():
            report["skipped"] = True
            return report
        if not db_path.is_file():
            report["error"] = "旧库不存在"
            return report

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='group_quotes'"
            ).fetchone()
            if table is None:
                report["error"] = "旧库缺少 group_quotes 表"
                return report
            rows = conn.execute(
                "SELECT group_id, user_id, user_nickname, image_hash, image_path,"
                " message_id, created_at FROM group_quotes ORDER BY created_at ASC"
            ).fetchall()
        finally:
            conn.close()

        legacy_images = legacy_data_dir / "images"
        for row in rows:
            group_id = str(row["group_id"])
            image_hash = str(row["image_hash"] or "").strip()
            if not group_id or not image_hash:
                report["missing_image"] += 1
                continue
            # 旧库里的 image_path 是入库机器上的绝对路径，优先用，其次按
            # 旧插件目录约定 images/{群号}/{hash}.png 兜底（跨机迁移时命中这条）
            image_path = Path(str(row["image_path"] or ""))
            if not image_path.is_file():
                image_path = legacy_images / group_id / f"{image_hash}.png"
            try:
                image_bytes = image_path.read_bytes()
            except OSError:
                report["missing_image"] += 1
                continue
            # 实际内容校验哈希（旧端可能没存 hash）
            actual = hashlib.sha256(image_bytes).hexdigest()
            ok, reason = self.add(
                group_id,
                str(row["user_id"] or ""),
                str(row["user_nickname"] or ""),
                actual,
                image_bytes,
                message_id=str(row["message_id"] or ""),
                created_at=float(row["created_at"] or 0.0),
            )
            if ok:
                report["imported"] += 1
            elif reason == "duplicate":
                report["duplicate"] += 1
            else:
                report["missing_image"] += 1

        report["migrated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
