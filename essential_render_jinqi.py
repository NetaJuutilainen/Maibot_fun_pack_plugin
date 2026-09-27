"""锦旗 PIL 渲染（纯绘制逻辑，不依赖 maibot_sdk，可离线测试）。

版式沿用传统锦旗的竖排右起格式，从右到左依次是：

    赠予对象（顶部对齐） → 感谢语一 → 感谢语二 → 落款 → 日期（底部对齐）

底图 assets/jinqi_bg.png 是一张 811×1080 的竖幅锦旗图（红丝绒旗面 + 金杆流苏）；
文字用毛笔楷体 Ma Shan Zheng 叠加，缺字自动回退到 Noto Sans SC，避免出现豆腐块。

与 essential_jinqi 的边界：本模块不 import 它，只按属性读取传入的 spec
（见下方 JinqiContent 协议），这样两个模块各自都能独立加载与测试。
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Protocol, Sequence

from PIL import Image, ImageDraw, ImageFont

# 底图尺寸，必须与 assets/jinqi_bg.png 的实际尺寸一致
BG_SIZE = (811, 1080)

# 文字可用区域：落在红布内、金色围边以内、底部波浪以上
# （以下数字按底图等比放大前的坐标系量取：红布 x56..285 / y43..385，
#   围边内侧 x53 / x286，两侧直边到 y355，整体 ×2.4 后即得上面的值）
AREA_X0, AREA_Y0 = 149, 130
AREA_X1, AREA_Y1 = 672, 830

TEXT_FILL = (252, 226, 142)
TEXT_STROKE = (74, 6, 4)

LINE_SPACING = 1.06          # 竖排列距系数
MAX_COL_GAP = 56             # 列间距上限（列少时不至于散得太开）
MIN_COL_GAP = 14             # 判定"装得下"时要求的最小列间距
MIN_FONT_SIZE = 24           # 自动缩号的下限
DATE_SIZE_RATIO = 0.86       # 日期比落款略小
MISSING_PROBE_CHAR = "\ue000"  # 私用区码位，任何字体都不该有，用来探测缺字


class JinqiContent(Protocol):
    """渲染所需的内容形状（由 essential_jinqi.JinqiSpec 满足）。"""

    thanks_columns: Sequence[str]
    recipient: str
    signer: str
    date_text: str


# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------

class FontSet:
    """一套字号的字体组合：主字体 + 缺字回退字体，带缺字探测缓存。"""

    def __init__(self, primary: Path, fallback: Path | None, size: int) -> None:
        self.size = int(size)
        self.primary = ImageFont.truetype(str(primary), self.size)
        self.fallback = (
            ImageFont.truetype(str(fallback), self.size)
            if fallback and Path(fallback).exists() else None
        )
        self._missing: dict[str, bool] = {}
        self._probe: dict[int, bytes] = {}

    def _fingerprint(self, font) -> bytes:
        key = id(font)
        if key not in self._probe:
            self._probe[key] = self._render_bitmap(font, MISSING_PROBE_CHAR)
        return self._probe[key]

    def _render_bitmap(self, font, ch: str) -> bytes:
        box = max(16, int(self.size * 2))
        img = Image.new("L", (box, box), 0)
        ImageDraw.Draw(img).text((box // 4, box // 4), ch, font=font, fill=255)
        return img.tobytes()

    def _is_missing(self, font, ch: str) -> bool:
        return self._render_bitmap(font, ch) == self._fingerprint(font)

    def pick(self, ch: str) -> "ImageFont.FreeTypeFont":
        """返回能画出该字体的字体对象；主字体缺字时回退。"""
        if not self.fallback:
            return self.primary
        cached = self._missing.get(ch)
        if cached is None:
            cached = self._is_missing(self.primary, ch)
            self._missing[ch] = cached
        if not cached:
            return self.primary
        if self._is_missing(self.fallback, ch):
            return self.primary  # 回退字体也没有，只能吃豆腐块
        return self.fallback


# ---------------------------------------------------------------------------
# 版式
# ---------------------------------------------------------------------------

class _Column:
    """一列竖排文字。

    逐字占一格（含拉丁字母与数字），这是中文竖排的常见做法：整列节奏一致、
    不用歪头看，也不会像"整段旋转 90°"那样在毛笔字体里把笔画挤成一团。
    代价是拉丁串会按字母数占格，列会变长——由字号自适应兜住。
    """

    __slots__ = ("text", "fontset", "valign", "step", "ascent", "width", "height", "cx", "y0")

    def __init__(self, text: str, fontset: FontSet, valign: str) -> None:
        self.text = text
        self.fontset = fontset
        self.valign = valign
        self.ascent, descent = fontset.primary.getmetrics()
        self.step = fontset.size * LINE_SPACING
        self.width = max(
            [fontset.primary.getlength(ch) for ch in text] + [fontset.size]
        )
        self.height = (len(text) - 1) * self.step + self.ascent + descent
        self.cx = 0.0
        self.y0 = 0.0

    def layout_vertical(self) -> None:
        if self.valign == "top":
            self.y0 = AREA_Y0
        elif self.valign == "bottom":
            self.y0 = AREA_Y1 - self.height
        else:
            self.y0 = AREA_Y0 + (AREA_Y1 - AREA_Y0 - self.height) / 2

    def draw(self, draw: ImageDraw.ImageDraw) -> None:
        stroke = max(1, round(self.fontset.size / 24))
        for i, ch in enumerate(self.text):
            font = self.fontset.pick(ch)
            draw.text(
                (self.cx, self.y0 + self.ascent + i * self.step),
                ch,
                font=font,
                anchor="ms",
                fill=TEXT_FILL,
                stroke_width=stroke,
                stroke_fill=TEXT_STROKE,
            )


def _build_columns(
    spec: JinqiContent,
    primary: Path,
    fallback: Path | None,
    big_size: int,
    small_size: int,
) -> list[_Column]:
    """按"从右到左"的顺序生成列；空栏自动跳过。"""
    big = FontSet(primary, fallback, big_size)
    small = FontSet(primary, fallback, small_size)
    date = FontSet(primary, fallback, max(MIN_FONT_SIZE, round(small_size * DATE_SIZE_RATIO)))

    columns: list[_Column] = []
    if spec.recipient:
        columns.append(_Column(spec.recipient, small, "top"))
    for text in spec.thanks_columns:
        if text:
            columns.append(_Column(text, big, "center"))
    if spec.signer:
        columns.append(_Column(spec.signer, small, "bottom"))
    if spec.date_text:
        columns.append(_Column(spec.date_text, date, "bottom"))
    return columns


def _fits(columns: list[_Column]) -> bool:
    if not columns:
        return False
    if max(c.height for c in columns) > AREA_Y1 - AREA_Y0:
        return False
    total = sum(c.width for c in columns) + MIN_COL_GAP * (len(columns) - 1)
    return total <= AREA_X1 - AREA_X0


def _place(columns: list[_Column]) -> None:
    """横向居中排布，列间距均匀且不超过上限。"""
    widths = sum(c.width for c in columns)
    gaps = len(columns) - 1
    gap = 0.0
    if gaps > 0:
        gap = min(MAX_COL_GAP, max(0.0, (AREA_X1 - AREA_X0 - widths) / gaps))
    total = widths + gap * gaps
    cursor = AREA_X0 + (AREA_X1 - AREA_X0 - total) / 2 + total
    for col in columns:
        col.cx = cursor - col.width / 2
        cursor -= col.width + gap
        col.layout_vertical()


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def render_jinqi(
    bg_path: Path,
    font_path: Path,
    out_path: Path,
    spec: JinqiContent,
    *,
    fallback_font_path: Path | None = None,
    big_font_size: int = 110,
    small_font_size: int = 42,
) -> Path:
    """把 spec 渲染成锦旗图片并保存到 out_path，返回 out_path。

    字号会自动收缩，直到所有列都装得进可用区域。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    big, small = int(big_font_size), int(small_font_size)
    columns: list[_Column] = []
    while True:
        columns = _build_columns(spec, Path(font_path), fallback_font_path, big, small)
        if _fits(columns) or big <= MIN_FONT_SIZE:
            break
        big = max(MIN_FONT_SIZE, big - 2)
        small = max(MIN_FONT_SIZE, small - 1)

    img = Image.open(bg_path).convert("RGB")
    if img.size != BG_SIZE:
        img = img.resize(BG_SIZE, Image.LANCZOS)
    _place(columns)
    draw = ImageDraw.Draw(img)
    for col in columns:
        col.draw(draw)

    img.save(out_path)
    return out_path


def jinqi_output_path(runtime_dir: Path) -> Path:
    """渲染产物的落盘路径（runtime_dir 由调用方传入 ctx.paths.runtime_dir）。"""
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    return Path(runtime_dir) / f"jinqi_{stamp}.jpg"
