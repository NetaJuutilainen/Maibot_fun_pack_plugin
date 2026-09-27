"""锦旗内容规格（纯逻辑，不依赖 maibot_sdk 与 PIL，可离线单测）。

本模块只负责「把原始入参整理成一份可渲染的内容规格」：
参数分段、感谢语分列、赠予对象/落款的默认值与敬语补全、日期文案。

真正的绘制在 essential_render_jinqi.py，两者之间只通过 JinqiSpec 传值，
不互相 import —— 宿主 Runner 以文件路径加载同目录模块，兄弟模块之间
无法用普通 import 互相引用，保持"只传数据"的边界对双方都更省事。

命令语法（`|` 分段，后两段可省）：

    /锦旗 感谢语 | 赠予对象 | 落款对象

感谢语默认是一列；想分成两列，用 `/`、`、` 等分隔符，或干脆用一个空格
分成两段（如 `助人为乐 情暖人心`）。不分列时超过单列上限会自动对半折行。
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

MAX_COL_CHARS = 8        # 单列最大字数（与传统锦旗"每列不超过八字"一致）
MAX_COLS = 2             # 感谢语最多两列
MAX_THANKS_CHARS = MAX_COL_CHARS * MAX_COLS
AUTO_FOLD_OVER = 6       # 整句超过这个字数就对半折成两列（单列太长会显得头重脚轻）
MAX_NAME_CHARS = 14      # 赠予对象 / 落款字数上限
MAX_SIGNER_CHARS = 14

# 赠予对象未写敬语前缀时自动补的前缀，与参考站点的提示一致
_HONOR_PREFIXES = ("赠", "敬赠", "谢", "感谢", "授予", "奖励", "送", "致", "敬上")

_SEG_SPLIT_RE = re.compile(r"[|｜]")
# 显式分列符（用户主动写出来的分隔）
_COL_SEP_RE = re.compile(r"[/／、，,]")
_WS_RE = re.compile(r"\s+")

_CN_DIGITS = "〇一二三四五六七八九"


class JinqiError(ValueError):
    """入参不合法，message 可直接回复给用户。"""


@dataclass(frozen=True)
class JinqiSpec:
    """一面锦旗的全部内容。空字符串表示该栏不渲染。"""

    thanks_columns: tuple[str, ...] = field(default_factory=tuple)
    recipient: str = ""
    signer: str = ""
    date_text: str = ""

    @property
    def thanks_text(self) -> str:
        return "".join(self.thanks_columns)


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

def parse_segments(payload: str) -> tuple[str, str, str]:
    """按 `|` 把原始入参切成 (感谢语, 赠予对象, 落款对象)，缺失段补空串。"""
    parts = [p.strip() for p in _SEG_SPLIT_RE.split(payload or "")]
    parts += [""] * (3 - len(parts))
    return parts[0], parts[1], parts[2]


def split_thanks(text: str) -> tuple[str, ...]:
    """把感谢语整理成 1~2 列。

    判定顺序（越靠前越优先）：
      1. 显式分列符 `/` `／` `、` `，` `,` 分出恰好两段 → 两列；
      2. 空白分出恰好两段（如 `助人为乐 情暖人心`）→ 两列；
      3. 其余情况视为一整句：去掉空白后超过单列上限就对半折成两列。

    第 2 条要求"恰好两段"，是为了不把 `代码零 Bug 上线不炸服` 这种
    三段的句子误切成 `代码零` + `Bug`。
    """
    raw = (text or "").strip()
    if not raw:
        raise JinqiError("缺少感谢语，用法：/锦旗 感谢语 | 赠予对象 | 落款对象")

    parts = [p.strip() for p in _COL_SEP_RE.split(raw) if p.strip()]
    if len(parts) != 2:
        ws_parts = [p for p in _WS_RE.split(raw) if p]
        parts = ws_parts if len(ws_parts) == 2 else []

    if len(parts) == 2:
        for col in parts:
            if len(col) > MAX_COL_CHARS:
                raise JinqiError(f"「{col}」超过单列 {MAX_COL_CHARS} 字，请拆成两列")
        return (parts[0], parts[1])

    whole = _WS_RE.sub("", raw)
    if len(whole) > MAX_THANKS_CHARS:
        raise JinqiError(
            f"感谢语太长了，最多 {MAX_THANKS_CHARS} 字（可分两列，每列 {MAX_COL_CHARS} 字）"
        )
    if len(whole) <= AUTO_FOLD_OVER:
        return (whole,)
    half = (len(whole) + 1) // 2
    return (whole[:half], whole[half:])


def normalize_recipient(text: str) -> str:
    """赠予对象：空则留空；未带敬语前缀时补「赠：」。"""
    name = (text or "").strip()
    if not name:
        return ""
    if len(name) > MAX_NAME_CHARS:
        raise JinqiError(f"赠予对象最多 {MAX_NAME_CHARS} 字")
    if name.startswith(_HONOR_PREFIXES):
        return name
    return f"赠：{name}"


def normalize_signer(text: str) -> str:
    """落款对象：原样使用（用户自己写"敬赠"就不动）。"""
    name = (text or "").strip()
    if len(name) > MAX_SIGNER_CHARS:
        raise JinqiError(f"落款最多 {MAX_SIGNER_CHARS} 字")
    return name


# ---------------------------------------------------------------------------
# 日期
# ---------------------------------------------------------------------------

def chinese_date(day: datetime.date) -> str:
    """公历转中文写法，如 2026-09-27 → 二〇二六年九月廿七日。"""
    year = "".join(_CN_DIGITS[int(c)] for c in f"{day.year:04d}")
    return f"{year}年{_cn_month(day.month)}月{_cn_day(day.day)}"


def _cn_month(month: int) -> str:
    if month < 10:
        return _CN_DIGITS[month]
    if month == 10:
        return "十"
    return "十" + _CN_DIGITS[month - 10]


def _cn_day(day: int) -> str:
    if day <= 10:
        return "初" + (_CN_DIGITS[day] if day < 10 else "十")
    if day < 20:
        return "十" + _CN_DIGITS[day - 10]
    if day == 20:
        return "二十"
    if day < 30:
        return "廿" + _CN_DIGITS[day - 20]
    if day == 30:
        return "三十"
    return "卅一"


DATE_STYLES = ("chinese", "numeric", "none")


def format_date(day: datetime.date, style: str = "chinese") -> str:
    """按配置渲染日期文案；style 为 none 时返回空串（该列不渲染）。"""
    style = (style or "chinese").strip().lower()
    if style == "none":
        return ""
    if style == "numeric":
        return day.strftime("%Y-%m-%d")
    return chinese_date(day)


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------

def build_spec(
    payload: str,
    *,
    fallback_signer: str = "",
    date_style: str = "chinese",
    today: datetime.date | None = None,
) -> JinqiSpec:
    """把命令/工具的原始入参整理成 JinqiSpec；不合法时抛 JinqiError。"""
    thanks_raw, recipient_raw, signer_raw = parse_segments(payload)
    columns = split_thanks(thanks_raw)

    signer = normalize_signer(signer_raw)
    if not signer:
        name = (fallback_signer or "").strip()
        signer = f"{name} 敬赠" if name else ""

    day = today or datetime.date.today()
    return JinqiSpec(
        thanks_columns=columns,
        recipient=normalize_recipient(recipient_raw),
        signer=signer,
        date_text=format_date(day, date_style),
    )
