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
import re
import sqlite3
import time
from pathlib import Path

INDEX_VERSION = 1
MIGRATION_MARKER = "quotes_migration.json"
# 群号白名单：平台群号一律为数字/字母/下划线/短横，最长 64 字符。
# 任何不在白名单内的字符（尤其是 `.` `/` `\\` 与空字符）都拒绝入库，
# 从源头堵死「把用户输入直接当文件名」导致的路径穿越（插件中心评审阻断项）。
_SAFE_GROUP_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# 图片文件名白名单（索引 JSON 里的 file 字段同样视为外部输入，可能被手改）
_SAFE_FILE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# 图片文件名由 sha256 派生，只接受 64 位小写十六进制；不合规一律按内容重算
_SAFE_IMAGE_HASH = re.compile(r"^[a-f0-9]{64}$")


def _safe_group_id(group_id: object) -> str | None:
    """把外部传入的 group_id 规整成可安全当目录名的字符串；非法返回 None。"""
    text = str(group_id if group_id is not None else "").strip()
    return text if _SAFE_GROUP_ID.fullmatch(text) else None


def _contained(base: Path, target: Path) -> bool:
    """target 解析后是否仍位于 base 之内（二次兜底，防白名单被绕过）。"""
    try:
        base_r = base.resolve()
        target_r = target.resolve()
    except (OSError, RuntimeError):
        return False
    return target_r == base_r or base_r in target_r.parents


class QuoteStore:
    """按群隔离的语录库：JSON 索引 + 图片文件，按图片内容哈希去重。"""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / "quote_images"
        self._cache: dict[str, list[dict]] = {}

    # -- 索引读写 -----------------------------------------------------------

    def _index_path(self, group_id: str) -> Path:
        """索引文件路径；group_id 必须先过 _safe_group_id 校验。"""
        return self.data_dir / f"quotes_{group_id}.json"

    def _image_path(self, group_id: object, file_name: object) -> Path | None:
        """拼图片文件路径并做双重校验：白名单 + resolve 后仍在 images_dir 内。

        索引 JSON 里的 file 字段同样按外部输入对待（文件可能被手工改过），
        任何不合规的名字一律返回 None，调用方按「图片丢了」处理。
        """
        gid = _safe_group_id(group_id)
        name = str(file_name if file_name is not None else "").strip()
        if gid is None or not _SAFE_FILE_NAME.fullmatch(name) or name in (".", ".."):
            return None
        target = self.images_dir / gid / name
        return target if _contained(self.images_dir, target) else None

    def _load(self, group_id: str) -> list[dict]:
        gid = _safe_group_id(group_id)
        if gid is None:
            # 非法群号当作空库：不读盘、不落盘、不进缓存
            return []
        if gid not in self._cache:
            path = self._index_path(gid)
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    quotes = data.get("quotes", []) if isinstance(data, dict) else []
                    self._cache[gid] = [q for q in quotes if isinstance(q, dict)]
                except (json.JSONDecodeError, OSError):
                    self._cache[gid] = []
            else:
                self._cache[gid] = []
        return self._cache[gid]

    def _save(self, group_id: str) -> None:
        gid = _safe_group_id(group_id)
        if gid is None:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._index_path(gid).write_text(
            json.dumps(
                {"version": INDEX_VERSION, "quotes": self._cache.get(gid, [])},
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
        """投稿一条语录。返回 (是否成功, 说明)；同一群内同一图片视为重复。

        group_id 与 image_hash 都会先规范化：群号不过白名单直接判失败（不会
        产生任何文件），哈希不合规则按图片内容重算 —— 调用方传什么都没法让
        落盘路径跑到数据目录之外。
        """
        gid = _safe_group_id(group_id)
        if gid is None:
            return False, "invalid_group_id"
        digest = str(image_hash or "").strip().lower()
        if not _SAFE_IMAGE_HASH.fullmatch(digest):
            digest = hashlib.sha256(image_bytes).hexdigest()
        quotes = self._load(gid)
        if any(q.get("image_hash") == digest for q in quotes):
            return False, "duplicate"

        group_dir = self.images_dir / gid
        image_path = group_dir / f"{digest}.png"
        if not _contained(self.images_dir, image_path):
            return False, "invalid_image_path"
        group_dir.mkdir(parents=True, exist_ok=True)
        if not image_path.exists():
            image_path.write_bytes(image_bytes)

        quotes.append({
            "image_hash": digest,
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
                # 路径再校验一次：索引里的 file 字段可能是被手改过的脏数据，
                # 校验不过就只从索引里剔除、绝不 unlink 数据目录外的文件
                old_path = self._image_path(gid, old.get("file"))
                if old_path is None:
                    continue
                try:
                    old_path.unlink(missing_ok=True)
                except OSError:
                    pass
        self._save(gid)
        return True, "ok"

    def random(self, group_id: str) -> dict | None:
        """随机抽一条；索引里图片文件已丢失的条目顺手清掉。"""
        gid = _safe_group_id(group_id)
        if gid is None:
            return None
        quotes = self._load(gid)
        alive: list[dict] = []
        for q in quotes:
            path = self._image_path(gid, q.get("file"))
            if path is not None and path.is_file():
                alive.append(q)
        if len(alive) != len(quotes):
            self._cache[gid] = alive
            self._save(gid)
        if not alive:
            return None
        return random.choice(alive)

    def read_image_b64(self, group_id: str, quote: dict) -> str | None:
        path = self._image_path(group_id, (quote or {}).get("file"))
        if path is None:
            return None
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
            "missing_image": 0, "skipped_groups": 0, "source": str(db_path),
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
            # 旧库里的 group_id 同样是外部数据，先过白名单再用（迁移路径与投稿
            # 路径同源，不校验一样能穿越）。不合规的记录计入 skipped_groups。
            group_id = _safe_group_id(row["group_id"])
            image_hash = str(row["image_hash"] or "").strip()
            if group_id is None:
                report["skipped_groups"] = report.get("skipped_groups", 0) + 1
                continue
            if not image_hash:
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
