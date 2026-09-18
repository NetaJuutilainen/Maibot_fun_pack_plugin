"""麦麦小工具合集（部分功能移植自 AstrBot astrbot_plugin_essential）。

功能：喜报/悲报图片生成、一言（/一言，回复不计入消息）、答案之书（<问题> 翻看答案）、
今天吃什么（命令 + 被动触发：关键词概率推荐/复读，移植自 astrbot_plugin_what_to_eat）、
群早晚安作息记录。同时注册 3 个 LLM 工具（deferred 池，由麦麦经 tool_search 按需发现）。
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any, ClassVar

from maibot_sdk import Command, Field, HookHandler, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import (
    CONFIG_RELOAD_SCOPE_SELF,
    ErrorPolicy,
    HookMode,
    ToolParameterInfo,
    ToolParamType,
)

_PLUGIN_DIR = Path(__file__).resolve().parent


def _load_sibling_module(stem: str) -> Any:
    """以受控方式加载同目录核心模块：不改动 Runner 的全局 sys.path，
    模块以"maibot_fun_pack_"前缀注册进 sys.modules，避免与其他插件或宿主模块撞名。"""
    module_name = f"maibot_fun_pack_{stem}"
    spec = importlib.util.spec_from_file_location(module_name, _PLUGIN_DIR / f"{stem}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"无法定位核心模块: {stem}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_services = _load_sibling_module("essential_services")
_storage = _load_sibling_module("essential_storage")
_render = _load_sibling_module("essential_render_card")

fetch_hitokoto = _services.fetch_hitokoto
AnswerBook = _storage.AnswerBook
FoodStore = _storage.FoodStore
GoodMorningStore = _storage.GoodMorningStore
strip_bracket_placeholders = _storage.strip_bracket_placeholders
render_report_card = _render.render_report_card
report_output_path = _render.report_output_path

_passive_eat = _load_sibling_module("essential_passive_eat")
PassiveRateLimiter = _passive_eat.PassiveRateLimiter
PassiveResponder = _passive_eat.PassiveResponder
FoodImageIndex = _passive_eat.FoodImageIndex
sniff_image_ext = _passive_eat.sniff_image_ext

SUPPORTED_CONFIG_VERSION = "1.3.3"  # 与 manifest version 保持同步

TZ8 = datetime.timezone(datetime.timedelta(hours=8))
TIME_FMT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# 配置模型
# ---------------------------------------------------------------------------

class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "celebration"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(
        default=SUPPORTED_CONFIG_VERSION,
        description="配置版本（与插件版本同步）",
        json_schema_extra={"hidden": True, "disabled": True},
    )


class ReportSection(PluginConfigBase):
    """喜报/悲报。"""

    __ui_label__ = "喜报 / 悲报"
    __ui_icon__ = "campaign"
    __ui_order__ = 1

    font_size: int = Field(default=65, ge=20, le=200, description="喜报/悲报字体大小")


class GoodMorningSection(PluginConfigBase):
    """早晚安作息记录。"""

    __ui_label__ = "早晚安"
    __ui_icon__ = "bedtime"
    __ui_order__ = 2

    cooldown_minutes: int = Field(
        default=30, ge=0, description="同一用户两次早晚安的最小间隔（分钟，0 为不限制）"
    )
    forward_to_mai: bool = Field(
        default=True,
        description="记录后把统计信息追加进麦麦上下文，供其自行决定是否再回复",
    )


class HitokotoSection(PluginConfigBase):
    """一言。"""

    __ui_label__ = "一言"
    __ui_icon__ = "format_quote"
    __ui_order__ = 3

    request_timeout_sec: int = Field(default=10, ge=1, description="一言 API 请求超时（秒）")


class WhatToEatSection(PluginConfigBase):
    """今天吃什么（命令 + 被动触发）。"""

    __ui_label__ = "今天吃什么"
    __ui_icon__ = "restaurant"
    __ui_order__ = 4

    enabled: bool = Field(
        default=True, description="启用被动触发：聊天含关键词时按概率推荐食物或复读"
    )
    trigger_keywords: list[str] = Field(
        default_factory=lambda: ["吃什么"], description="被动触发关键词列表（命中任意一个即触发）"
    )
    recommend_probability: float = Field(
        default=0.3, ge=0.0, le=1.0, description="被动触发时推荐食物的概率，其余概率复读"
    )
    intercept_message: bool = Field(
        default=True, description="被动回复后拦截该消息（麦麦不再对其回复）；关闭则麦麦也可以接话"
    )
    rate_limit_enabled: bool = Field(default=True, description="启用频率限制（防多 Bot 循环）")
    rate_limit_max: int = Field(default=3, ge=1, description="时间窗口内最大被动响应次数，超过后强制推荐")
    rate_limit_window_seconds: int = Field(default=60, ge=1, description="频率限制窗口（秒）")
    echo_cooldown_enabled: bool = Field(default=True, description="启用复读冷却")
    echo_cooldown_seconds: int = Field(
        default=15, ge=0, description="复读后的冷却秒数，冷却期内触发强制推荐"
    )


class EssentialConfig(PluginConfigBase):
    """插件完整配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    report: ReportSection = Field(default_factory=ReportSection)
    good_morning: GoodMorningSection = Field(default_factory=GoodMorningSection)
    hitokoto: HitokotoSection = Field(default_factory=HitokotoSection)
    what_to_eat: WhatToEatSection = Field(default_factory=WhatToEatSection)


# ---------------------------------------------------------------------------
# 插件主体
# ---------------------------------------------------------------------------

class EssentialPlugin(MaiBotPlugin):
    """必备娱乐插件。"""

    config_model: ClassVar[type[PluginConfigBase] | None] = EssentialConfig

    def __init__(self) -> None:
        super().__init__()
        self._food: FoodStore | None = None
        self._good_morning: GoodMorningStore | None = None
        self._answer_book: AnswerBook | None = None
        self._passive_limiter: PassiveRateLimiter | None = None
        self._passive_responder: PassiveResponder | None = None
        self._food_images: FoodImageIndex | None = None
        self._good_morning_cd: dict[str, datetime.datetime] = {}

    # -- 生命周期 -----------------------------------------------------------

    async def on_load(self) -> None:
        data_dir = self.ctx.paths.data_dir
        self._food = FoodStore(data_dir / "food.json", _PLUGIN_DIR / "assets" / "food.json")
        self._good_morning = GoodMorningStore(data_dir / "good_morning.json")
        self._answer_book = AnswerBook(_PLUGIN_DIR / "assets" / "answer_book.json")
        try:
            (data_dir / "food_images").mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._food_images = FoodImageIndex(data_dir / "food_images")
        await asyncio.to_thread(self._food.load)
        await asyncio.to_thread(self._good_morning.load)
        await asyncio.to_thread(self._answer_book.load)
        self._init_what_to_eat_components()
        try:
            self.ctx.paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.ctx.logger.info(
            "麦麦小工具合集已加载：食物 %d 项，早晚安记录 %d 个会话，答案之书 %d 条，食物图片 %d 种",
            len(self._food.items),
            len(self._good_morning.data),
            len(self._answer_book.answers),
            len(self._food_images.foods_with_images()),
        )

    def _init_what_to_eat_components(self) -> None:
        """按当前配置重建"今天吃什么"共享组件（on_load 与配置热更新共用）。"""
        cfg = self.config.what_to_eat
        if cfg.rate_limit_enabled:
            self._passive_limiter = PassiveRateLimiter(
                max_responses=cfg.rate_limit_max,
                window_seconds=cfg.rate_limit_window_seconds,
                echo_cooldown_enabled=cfg.echo_cooldown_enabled,
                echo_cooldown_seconds=cfg.echo_cooldown_seconds,
            )
        else:
            self._passive_limiter = None
        self._passive_responder = PassiveResponder(cfg.recommend_probability)
        if self._food_images is not None:
            self._food_images.reload()

    async def on_unload(self) -> None:
        self.ctx.logger.info("麦麦小工具合集已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        if scope == CONFIG_RELOAD_SCOPE_SELF:
            self._init_what_to_eat_components()
            self.ctx.logger.info("插件配置已热更新 version=%s", version)

    # -- 内部工具 -----------------------------------------------------------

    @staticmethod
    def _stream_id(kwargs: dict) -> str:
        return str(kwargs.get("stream_id") or "")

    @staticmethod
    def _user_id(kwargs: dict) -> str:
        return str(kwargs.get("user_id") or "")

    @staticmethod
    def _nickname(kwargs: dict) -> str:
        try:
            info = (kwargs.get("message") or {}).get("message_info") or {}
            return str((info.get("user_info") or {}).get("user_nickname") or "")
        except Exception:
            return ""

    async def _append_context(self, stream_id: str, note: str) -> None:
        """向麦麦会话追加一条插件上下文（失败只记日志，不影响命令结果）。"""
        if not stream_id:
            return
        try:
            await self.ctx.maisaka.context.append(
                stream_id,
                [{"type": "text", "data": note}],
                visible_text=note,
                source_kind="plugin",
            )
        except Exception as e:  # noqa: BLE001 - 兼容旧版宿主无此能力的情况
            self.ctx.logger.warning("追加上下文失败（不影响命令结果）: %s", e)

    async def _send_report_card(self, *, happy: bool, text: str, stream_id: str) -> None:
        """渲染喜报/悲报并发送图片；发送失败时降级为文本提示。"""
        bg = _PLUGIN_DIR / "assets" / ("congrats.jpg" if happy else "uncongrats.jpg")
        font = _PLUGIN_DIR / "assets" / "NotoSansSC.ttf"
        out_path = report_output_path(self.ctx.paths.runtime_dir, happy)
        fill = (255, 0, 0) if happy else (0, 0, 0)
        stroke = (255, 255, 0) if happy else (255, 255, 255)
        try:
            await asyncio.to_thread(
                render_report_card,
                bg, font, text, int(self.config.report.font_size), out_path, fill, stroke,
            )
            image_b64 = base64.b64encode(out_path.read_bytes()).decode("ascii")
        finally:
            try:
                out_path.unlink(missing_ok=True)
            except OSError:
                pass
        sent = await self.ctx.send.image(image_b64, stream_id)
        if not sent:
            await self.ctx.send.text("图片发送失败了，请查看主进程日志排查。", stream_id)

    # -- 命令组件 -----------------------------------------------------------

    MENU_TEXT = (
        "【麦麦小工具合集 · 指令列表】\n"
        "/喜报 <内容> —— 生成喜报图片\n"
        "/悲报 <内容> —— 生成悲报图片\n"
        "一言 [文字] —— 随机一条一言（/ 可省；回复不计入消息）\n"
        "<问题> 翻看答案 —— 答案之书，随机翻一页\n"
        "/今天吃什么 —— 立即推荐今天吃什么（有绑定图则图文发送）\n"
        "/今天吃什么 添加|删除 <食物...> —— 维护食物清单\n"
        "聊天中提到“吃什么” —— 概率推荐美食或复读“是啊，吃什么”（被动触发）\n"
        "早安 / 晚安 —— 记录作息并统计（麦麦可能会接话）\n"
        "/工具列表 —— 显示本菜单\n"
        "本插件另有 3 个 LLM 工具（一言/推荐食物/喜报悲报），麦麦会在合适时机自主调用。"
    )

    @Command("tool_list", description="查看本插件全部指令", pattern=r"(?<!\S)/工具列表(?:\s*\[[^\]]*\])*\s*$")
    async def cmd_tool_list(self, **kwargs: Any):
        stream_id = self._stream_id(kwargs)
        await self.ctx.send.text(self.MENU_TEXT, stream_id)
        return True, "已发送指令列表", True

    @Command("happy_report", description="喜报图片生成", pattern=r"(?<!\S)/喜报\s+(?P<text>[\s\S]+?)\s*(?:\[[^\]]*\]\s*)*$")
    async def cmd_happy_report(self, **kwargs: Any):
        text = strip_bracket_placeholders(
            str((kwargs.get("matched_groups") or {}).get("text") or "")
        ).strip()
        stream_id = self._stream_id(kwargs)
        if not text:
            await self.ctx.send.text("用法：/喜报 <内容>", stream_id)
            return False, "缺少内容", True
        await self._send_report_card(happy=True, text=text, stream_id=stream_id)
        return True, "喜报已生成", True

    @Command("sad_report", description="悲报图片生成", pattern=r"(?<!\S)/悲报\s+(?P<text>[\s\S]+?)\s*(?:\[[^\]]*\]\s*)*$")
    async def cmd_sad_report(self, **kwargs: Any):
        text = strip_bracket_placeholders(
            str((kwargs.get("matched_groups") or {}).get("text") or "")
        ).strip()
        stream_id = self._stream_id(kwargs)
        if not text:
            await self.ctx.send.text("用法：/悲报 <内容>", stream_id)
            return False, "缺少内容", True
        await self._send_report_card(happy=False, text=text, stream_id=stream_id)
        return True, "悲报已生成", True

    @Command(
        "answer_book",
        description="答案之书：在问题后面加上「翻看答案」",
        pattern=r"(?<!\S)(?:(?P<question>.+?)\s+)?翻看答案\s*$",
    )
    async def cmd_answer_book(self, **kwargs: Any):
        """经典答案之书玩法：从本地词条库随机抽一条，引用回复。"""
        question = str((kwargs.get("matched_groups") or {}).get("question") or "").strip()
        stream_id = self._stream_id(kwargs)
        if not question:
            await self.ctx.send.text(
                "在心里想好你的问题，然后把它发出来，并在末尾加上「翻看答案」。\n"
                "例如：今天能否起飞 翻看答案",
                stream_id,
            )
            return False, "缺少问题", True
        answer = self._answer_book.choice()
        # 引用回复需要显式给出被引用消息的 ID（缺了宿主会拒绝整条发送）
        trigger_message = kwargs.get("message") or {}
        reply_message_id = str(trigger_message.get("message_id") or "")
        sent = False
        if reply_message_id:
            sent = await self.ctx.send.text(
                answer, stream_id, set_reply=True, reply_message_id=reply_message_id,
            )
        if not sent:
            # 引用回复不可用时降级：把问题写进正文，确保答案一定能发出
            fallback = await self.ctx.send.text(f"（关于「{question}」）\n{answer}", stream_id)
            if not fallback:
                self.ctx.logger.warning("答案之书回复发送失败（含降级路径），请查主进程日志")
        return True, "答案之书已翻页", True

    @Command("hitokoto", description="来一条一言", pattern=r"(?<!\S)/?一言(?:\s+(?P<extra>[\s\S]+?))?\s*(?:\[[^\]]*\]\s*)*$")
    async def cmd_hitokoto(self, **kwargs: Any):
        """一言：随取随看，命令回复不入库、不同步进麦麦上下文（不计入消息）。"""
        stream_id = self._stream_id(kwargs)
        try:
            data = await fetch_hitokoto(timeout=int(self.config.hitokoto.request_timeout_sec))
        except Exception as e:  # noqa: BLE001
            await self.ctx.send.text(
                "一言获取失败了，稍后再试喵。", stream_id,
                storage_message=False, sync_to_maisaka_history=False,
            )
            return False, f"一言获取失败: {e}", True

        quote = f"『{data['hitokoto']}』——{data.get('from') or '未知出处'}"
        await self.ctx.send.text(
            quote, stream_id, storage_message=False, sync_to_maisaka_history=False,
        )
        return True, "一言已发送", True

    @Command(
        "what_to_eat",
        description="今天吃什么",
        pattern=r"(?<!\S)/今天吃什么(?:\s+(?P<action>添加|删除)(?:\s+(?P<items>[\s\S]+?))?)?(?:\s*\[[^\]]*\])*\s*$",
    )
    async def cmd_what_to_eat(self, **kwargs: Any):
        groups = kwargs.get("matched_groups") or {}
        action = str(groups.get("action") or "").strip()
        items = str(groups.get("items") or "").strip()
        stream_id = self._stream_id(kwargs)

        if action:
            # 带图消息的文本尾部会带 [图片：AI 描述] 占位符，先剥掉再解析
            items = strip_bracket_placeholders(items)
            names = [n for n in items.split() if "[" not in n and "]" not in n]
            self.ctx.logger.info("今天吃什么：items=%r names=%r", items, names)
            if not names:
                await self.ctx.send.text(f"格式：/今天吃什么 {action} [食物1] [食物2] ...", stream_id)
                return False, "缺少食物名", True
            if action == "添加":
                before = set(self._food.items)
                added = self._food.add(names)
                await asyncio.to_thread(self._food.save)
                segs = (kwargs.get("message") or {}).get("raw_message") or []
                seg_types = [s.get("type") for s in segs if isinstance(s, dict)]
                has_attached = any(t in ("image", "emoji") for t in seg_types)
                if segs:
                    self.ctx.logger.info("今天吃什么：命令消息段类型 %s", seg_types)
                bound = 0
                if has_attached and len(names) == 1:
                    bound = await self._save_attached_food_images(names[0], segs)
                    if bound:
                        await asyncio.to_thread(self._food_images.reload)
                total = len(self._food.items)
                if bound and names[0] not in before:
                    reply = f"已添加 {names[0]}，并绑定 {bound} 张图片。现在共 {total} 个食物。"
                elif bound:
                    reply = f"{names[0]} 已在清单中，新增绑定 {bound} 张图片。"
                elif has_attached and len(names) > 1:
                    reply = (
                        f"添加成功（新增 {added} 个），现在共 {total} 个食物。"
                        "附带图片未绑定：一次只添加一个食物时才会绑定图片。"
                    )
                elif has_attached and bound == 0:
                    reply = f"添加成功（新增 {added} 个），但没能从消息里取到图片数据。现在共 {total} 个食物。"
                else:
                    reply = f"添加成功（新增 {added} 个），现在共 {total} 个食物。"
                await self.ctx.send.text(reply, stream_id)
            else:
                removed = self._food.remove(names)
                await asyncio.to_thread(self._food.save)
                await self.ctx.send.text(
                    f"删除成功（移除 {removed} 个），现在共 {len(self._food.items)} 个食物。",
                    stream_id,
                )
            return True, "食物清单已更新", True

        pick = self._food.choice()
        await self.ctx.send.text(f"今天吃 {pick}！", stream_id)
        return True, "已推荐", True

    @Command(
        "good_morning",
        description="早晚安作息记录",
        pattern=r"(?<!\S)/?(?P<kind>早安|晚安)[呀啊喵哦咯啦哟唷~～，,。！!。\s]*$",
    )
    async def cmd_good_morning(self, **kwargs: Any):
        kind = str((kwargs.get("matched_groups") or {}).get("kind") or "")
        stream_id = self._stream_id(kwargs)
        user_id = self._user_id(kwargs)
        nickname = self._nickname(kwargs) or user_id or "朋友"
        now = datetime.datetime.now(TZ8)
        curr_human = now.strftime(TIME_FMT)
        cooldown_minutes = int(self.config.good_morning.cooldown_minutes)

        # 冷却检查（内存态，重启即清零）
        last = self._good_morning_cd.get(user_id) if user_id else None
        if cooldown_minutes > 0 and last and (now - last).total_seconds() < cooldown_minutes * 60:
            await self.ctx.send.text(
                f"你刚刚已经说过早安/晚安了，请{cooldown_minutes}分钟后再试喵~", stream_id
            )
            return False, "冷却中", True

        is_night = kind == "晚安"
        user = self._good_morning.user_record(stream_id, user_id)
        if is_night:
            user["daily"]["night_time"] = curr_human
            user["daily"]["morning_time"] = ""  # 晚安后清空早安时间
        else:
            user["daily"]["morning_time"] = curr_human
        await asyncio.to_thread(self._good_morning.save)
        if user_id:
            self._good_morning_cd[user_id] = now

        # 本群今天第几个睡觉的（沿用原版口径：晚安时间与当前日期同"日"）
        sleeping_count = self._good_morning.count_sleeping_today(stream_id, now.day)

        if not is_night:
            duration_human = "……咦，没记录到你的晚安时间喵"
            if user["daily"]["night_time"]:
                try:
                    night_time = datetime.datetime.strptime(user["daily"]["night_time"], TIME_FMT)
                    morning_time = datetime.datetime.strptime(user["daily"]["morning_time"], TIME_FMT)
                    seconds = (morning_time - night_time).total_seconds()
                    duration_human = f"{int(seconds // 3600)}小时{int(seconds % 3600 // 60)}分"
                except ValueError:
                    pass
            reply = f"早上好喵，{nickname}！\n现在是 {curr_human}，昨晚你睡了 {duration_human}。"
        else:
            reply = f"快睡觉喵，{nickname}！\n现在是 {curr_human}，你是本群今天第 {sleeping_count} 个睡觉的。"

        await self.ctx.send.text(reply, stream_id)

        # 统计回复已发出，把记录信息交给麦麦，由它自行决定是否再回复其他内容
        if self.config.good_morning.forward_to_mai:
            if is_night:
                note = (
                    f"[插件] 已为 {nickname} 记录晚安：现在是 {curr_human}，"
                    f"TA 是本群今天第 {sleeping_count} 个睡觉的。"
                )
            else:
                note = f"[插件] 已为 {nickname} 记录早安：现在是 {curr_human}，昨晚睡了 {duration_human}。"
            await self._append_context(stream_id, note)

        return True, "作息已记录", False  # ★ 放行：麦麦自行决定是否再回复

    # -- LLM 工具组件（deferred 池，麦麦经 tool_search 发现） -----------------

    @Tool(
        "get_hitokoto",
        brief_description="获取一条随机一言（文学/动漫摘句）",
        detailed_description="获取一条随机一言并返回给你阅读。仅当用户明确想要一言、句子、语录时调用，不要主动滥用。",
        parameters=None,
    )
    async def tool_get_hitokoto(self, **kwargs: Any):
        try:
            data = await fetch_hitokoto(timeout=int(self.config.hitokoto.request_timeout_sec))
        except Exception as e:  # noqa: BLE001
            return {"content": f"一言获取失败: {e}"}
        return {"content": f"『{data['hitokoto']}』——{data.get('from') or '未知出处'}"}

    @Tool(
        "random_food",
        brief_description="从食物清单随机推荐今天吃什么",
        detailed_description="从插件维护的食物清单中随机选一个返回给你。仅当用户想让你推荐吃什么、纠结吃什么时调用。清单由命令「/今天吃什么 添加/删除 ...」维护。",
        parameters=None,
    )
    async def tool_random_food(self, **kwargs: Any):
        return {"content": f"推荐：{self._food.choice()}"}

    @Tool(
        "report_card",
        brief_description="生成并发送喜报或悲报图片",
        detailed_description="把指定文字渲染成喜报（红字黄边）或悲报（黑字白边）图片并发送到当前会话。仅当用户明确要求生成喜报/悲报时调用。参数：text（string，必填，喜报/悲报内容）；mood（string，可选，happy=喜报 / sad=悲报，默认 happy）。",
        parameters=[
            ToolParameterInfo(
                name="text",
                param_type=ToolParamType.STRING,
                description="喜报/悲报的内容",
                required=True,
            ),
            ToolParameterInfo(
                name="mood",
                param_type=ToolParamType.STRING,
                description="happy=喜报，sad=悲报",
                required=False,
                default="happy",
                enum_values=["happy", "sad"],
            ),
        ],
    )
    async def tool_report_card(self, text: str = "", mood: str = "happy", **kwargs: Any):
        text = (text or "").strip()
        if not text:
            return {"content": "缺少 text 参数，未生成。"}
        stream_id = self._stream_id(kwargs)
        if not stream_id:
            return {"content": "当前调用没有会话上下文，无法发送图片。"}
        happy = mood != "sad"
        try:
            await self._send_report_card(happy=happy, text=text, stream_id=stream_id)
        except Exception as e:  # noqa: BLE001
            return {"content": f"喜报/悲报生成失败: {e}"}
        return {"content": f"已生成并发送{'喜报' if happy else '悲报'}图片：{text}"}

    # -- 被动触发（今天吃什么，移植自 astrbot_plugin_what_to_eat） -----------

    def _load_food_image_b64(self, food: str | None) -> str | None:
        """取食物的随机绑定图并转 base64；无图或读图失败返回 None。"""
        if self._food_images is None or not food:
            return None
        path = self._food_images.get_random_image(food)
        if path is None:
            return None
        try:
            return base64.b64encode(Path(path).read_bytes()).decode("ascii")
        except OSError:
            return None

    async def _save_attached_food_images(self, food: str, segments: list) -> int:
        """把命令消息附带的图片按 hash 从宿主图片库定位并保存，返回保存张数。

        命令载荷不含二进制，但图片段带 sha256 hash；宿主图片库按
        data/images/<hash>.<ext>（表情为 data/emoji/）落盘，直接探测读取，
        避开宿主数据库连接池的旧快照问题（get_by_id 在命令时刻查不到新消息）。
        """
        saved = 0
        host_data_dir = Path(self.ctx.paths.data_dir).parent.parent
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            seg_type = str(seg.get("type") or "")
            image_hash = str(seg.get("hash") or "").strip().lower()
            if not self._IMAGE_HASH_RE.match(image_hash):
                if seg_type in ("image", "emoji"):
                    self.ctx.logger.warning(
                        "图片段 hash 缺失或格式异常，跳过绑定（type=%s）", seg_type
                    )
                continue
            data = await asyncio.to_thread(
                self._read_host_image_bytes, host_data_dir, seg_type, image_hash
            )
            if data:
                saved += await asyncio.to_thread(self._food_images.save_image, food, data)
            else:
                self.ctx.logger.warning(
                    "宿主图片库中未找到 %s（探测数据目录: %s）",
                    image_hash[:16], host_data_dir,
                )
        return saved

    _IMAGE_HASH_RE = re.compile(r"^[a-f0-9]{64}$")

    @staticmethod
    def _read_host_image_bytes(
        host_data_dir: Path, seg_type: str, image_hash: str
    ) -> bytes | None:
        """按宿主图片库的落盘约定（<数据目录>/<images|emoji>/<hash>.<ext>）读取图片。"""
        exts = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        dirs = ("emoji", "images") if seg_type == "emoji" else ("images", "emoji")
        for sub in dirs:
            for ext in exts:
                path = host_data_dir / sub / f"{image_hash}{ext}"
                try:
                    if path.is_file():
                        return path.read_bytes()
                except OSError:
                    continue
        return None

    async def _resolve_stream_id(self, message: dict, group_id: str, user_id: str) -> str:
        """Hook 载荷里 session_id 可能缺失，按群号/用户号回查聊天流。"""
        stream_id = str(message.get("session_id") or "")
        if stream_id:
            return stream_id
        try:
            if group_id:
                stream = await self.ctx.chat.get_stream_by_group_id(group_id=group_id)
            else:
                stream = await self.ctx.chat.get_stream_by_user_id(user_id=user_id)
            return str((stream or {}).get("session_id") or "")
        except Exception as e:  # noqa: BLE001
            self.ctx.logger.warning("被动触发定位会话失败: %s", e)
            return ""

    @HookHandler(
        "chat.receive.after_process",
        name="passive_what_to_eat",
        mode=HookMode.BLOCKING,
        error_policy=ErrorPolicy.SKIP,
    )
    async def hook_passive_what_to_eat(self, **kwargs: Any):
        """被动触发：消息含"吃什么"类关键词时，按概率推荐食物或复读"是啊，吃什么"。"""

        cfg = self.config.what_to_eat
        if not cfg.enabled or self._passive_responder is None:
            return None

        message = kwargs.get("message") or {}
        if message.get("is_notify"):
            return None
        text = str(message.get("processed_plain_text") or "").strip()
        if not text or text.startswith("/"):
            return None  # 斜杠消息交给命令系统处理
        if not any(kw and str(kw) in text for kw in (cfg.trigger_keywords or [])):
            return None

        info = message.get("message_info") or {}
        group_id = str((info.get("group_info") or {}).get("group_id") or "")
        user_id = str((info.get("user_info") or {}).get("user_id") or "")
        chat_key = str(message.get("session_id") or f"{group_id or 'private'}:{user_id}")

        _, force_recommend = (
            self._passive_limiter.check_and_record(chat_key)
            if self._passive_limiter
            else (True, False)
        )
        in_cooldown = (
            self._passive_limiter.is_in_echo_cooldown(chat_key)
            if self._passive_limiter
            else False
        )
        should_recommend = (
            force_recommend or in_cooldown or self._passive_responder.should_recommend()
        )

        stream_id = await self._resolve_stream_id(message, group_id, user_id)
        if not stream_id:
            return None  # 定位不到会话，放弃本次触发

        if should_recommend:
            food = self._food.choice_or_none()
            response = self._passive_responder.get_food_response(food)
            image_b64 = await asyncio.to_thread(self._load_food_image_b64, food)
            if image_b64:
                sent = False
                try:
                    sent = await self.ctx.send.hybrid(
                        [
                            {"type": "text", "content": response},
                            {"type": "image", "content": image_b64},
                        ],
                        stream_id,
                    )
                except Exception as e:  # noqa: BLE001 - 能力未授权等异常时降级为分开发送
                    self.ctx.logger.warning("send.hybrid 失败，降级为文本+图片分开发送: %s", e)
                if not sent:
                    await self.ctx.send.text(response, stream_id)
                    await self.ctx.send.image(image_b64, stream_id)
            else:
                await self.ctx.send.text(response, stream_id)
        else:
            await self.ctx.send.text(self._passive_responder.get_echo_response(), stream_id)
            if self._passive_limiter:
                self._passive_limiter.record_echo(chat_key)

        if cfg.intercept_message:
            return {"action": "abort", "abort_message": "passive_what_to_eat 已响应"}
        return None


def create_plugin() -> EssentialPlugin:
    """Runner 加载入口。"""
    return EssentialPlugin()
