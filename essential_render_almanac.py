"""今日宜忌 PIL 渲染（纯绘制逻辑，不依赖 maibot_sdk，可离线测试）。

版式（720×1080，黄历纸底 + 朱砂双线框）：
    · 标题「今日宜忌」（楷书 + 两侧菱形装饰）
    · 公历/星期一行 + 农历（干支年·生肖·月日·日干支）一行
    · 冲煞 / 幸运色信息条
    · 「宜 / 忌」两枚方形朱印各带一组事项（区块垂直居中，超宽自动缩号）
    · 十二时辰吉凶格（吉=朱红 / 中=褪色 / 凶=墨色）
    · 底部彩蛋两行（吉利方位 / 幸运数字 / 运势星级 / 幸运物）
    · 满运（5★）时在忌区块右下盖一枚半透明「百无禁忌」斜章
    · 全图覆盖低透明度旧纸纹理

与 essential_almanac 的边界：本模块不 import 它，只按属性读取传入的 draw
（AlmanacDraw 协议：day / yi / ji / direction / lucky_number / lucky_thing /
stars / lucky_color / shichen / ganzhi_year / weekday_cn / lunar_text / zodiac /
day_ganzhi_cn / chong / sha），两个模块各自都能独立加载与测试。

字体：楷体 MaShanZheng.ttf（标题 / 印章 / 事项 / 时辰），NotoSansSC.ttf（日期 /
底注）；缺字逐字回退到 Noto Sans SC，探测方式与锦旗渲染一致。
"""

from __future__ import annotations

import random
from datetime import date as Date
from pathlib import Path
from typing import Protocol, Sequence

from PIL import Image, ImageDraw, ImageFont

W, H = 720, 1080
CX = W // 2
INNER_RIGHT = W - 31 - 24          # 内框右缘再留 24px 安全边

PAPER = (243, 230, 197)
INK = (43, 38, 36)
RED = (169, 28, 19)                # 与插件图标底色一致
FADE = (139, 126, 100)

TITLE_Y = 100
DATE1_Y = 172                      # 公历 + 星期
DATE2_Y = 214                      # 农历干支年·生肖·月日·日干支
INFO_Y = 254                       # 冲煞 · 幸运色 信息条
DIV_TOP_Y = 284
YI_TOP, YI_BOTTOM = 294, 536
DIV_MID_Y = 548
JI_TOP, JI_BOTTOM = 558, 798
SHICHEN_LABEL_Y = 822              # 「· 时辰吉凶 ·」
SHICHEN_NAME_Y = 852
SHICHEN_FORTUNE_Y = 886
FOOT_Y1, FOOT_Y2 = 930, 970

SEAL_HALF = 66                     # 方形朱印半边长
SEAL_X1_OFF = 28                   # 印章右缘相对中轴的偏移（占左半幅）
ITEM_STEP = 54
ITEM_SIZE_MAX, ITEM_SIZE_MIN = 42, 26
CN_NUM = "一二三四五六"

FORTUNE_COLOR = {"吉": RED, "中": FADE, "凶": INK}

# 纸纹用固定种子：纹理是"纸"的属性，与日期无关，每天同一张纸
_SPECKLE_SEED = 0xA91C13


class AlmanacDrawProtocol(Protocol):
    """渲染所需的内容形状（由 essential_almanac.AlmanacDraw 满足）。"""

    day: Date
    yi: Sequence[str]
    ji: Sequence[str]
    direction: str
    lucky_number: int
    lucky_thing: str
    stars: int
    lucky_color: str
    shichen: Sequence[tuple[str, str]]

    @property
    def ganzhi_year(self) -> str: ...

    @property
    def weekday_cn(self) -> str: ...

    @property
    def lunar_text(self) -> str: ...

    @property
    def zodiac(self) -> str: ...

    @property
    def day_ganzhi_cn(self) -> str: ...

    @property
    def chong(self) -> str: ...

    @property
    def sha(self) -> str: ...


class FontPair:
    """主字体 + 缺字回退：逐字探测（渲染成位图与私用区缺字指纹比对，同锦旗渲染）。"""

    _PROBE = "\ue000"

    def __init__(self, primary: Path, fallback: Path | None, size: int) -> None:
        self.size = int(size)
        self.primary = ImageFont.truetype(str(primary), self.size)
        self.fallback = (
            ImageFont.truetype(str(fallback), self.size)
            if fallback and Path(fallback).exists() else None
        )
        self._missing: dict[tuple[int, str], bool] = {}

    def _bitmap(self, font, ch: str) -> bytes:
        box = max(16, int(self.size * 2))
        img = Image.new("L", (box, box), 0)
        ImageDraw.Draw(img).text((box // 4, box // 4), ch, font=font, fill=255)
        return img.tobytes()

    def _is_missing(self, font, ch: str) -> bool:
        key = (id(font), ch)
        if key not in self._missing:
            self._missing[key] = self._bitmap(font, ch) == self._bitmap(font, self._PROBE)
        return self._missing[key]

    def font_for(self, ch: str):
        if self.fallback is not None and ch.strip() and self._is_missing(self.primary, ch):
            return self.fallback
        return self.primary

    def text(self, draw: ImageDraw.ImageDraw, xy: tuple[float, float], s: str,
             fill, anchor: str = "lm") -> None:
        """整串绘制；主字体有缺字时逐字选字体、按实宽推进（只处理中轴/左中锚）。"""
        if self.fallback is None or all(
            not ch.strip() or not self._is_missing(self.primary, ch) for ch in s
        ):
            draw.text(xy, s, font=self.primary, fill=fill, anchor=anchor)
            return
        widths = [draw.textlength(ch, font=self.font_for(ch)) for ch in s]
        x = xy[0] - sum(widths) / 2 if anchor[0] == "m" else xy[0]
        for ch, w in zip(s, widths):
            draw.text((x, xy[1]), ch, font=self.font_for(ch), fill=fill,
                      anchor=f"l{anchor[1]}")
            x += w


def _add_speckle(img: Image.Image) -> None:
    """纸纹：内框区域内撒低透明度细点，模拟旧纸质感。"""
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    rng = random.Random(_SPECKLE_SEED)
    for _ in range(420):
        x = rng.randint(40, W - 41)
        y = rng.randint(40, H - 41)
        r = rng.choice((1, 1, 1, 2))
        a = rng.randint(6, 16)
        odraw.ellipse([x - r, y - r, x + r, y + r], fill=(120, 100, 70, a))
    merged = Image.alpha_composite(img.convert("RGBA"), overlay)
    img.paste(merged.convert("RGB"), (0, 0))


def _make_baiwujinji_stamp(kai_path: Path) -> Image.Image:
    """「百无禁忌」斜章：双线圆角红框 + 楷书，旋转后压 alpha 供半透明粘贴。"""
    size = 60
    font = ImageFont.truetype(str(kai_path), size)
    text = "百无禁忌"
    probe = Image.new("RGBA", (8, 8))
    bbox = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 22
    stamp = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(stamp)
    d.rounded_rectangle([3, 3, stamp.width - 4, stamp.height - 4], radius=12,
                        outline=RED, width=6)
    d.rounded_rectangle([14, 14, stamp.width - 15, stamp.height - 15], radius=7,
                        outline=RED, width=2)
    d.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=RED)
    stamp = stamp.rotate(14, expand=True, resample=Image.BICUBIC)
    alpha = stamp.getchannel("A").point(lambda a: a * 72 // 100)
    stamp.putalpha(alpha)
    return stamp


def render_almanac(
    out_path: Path,
    draw_data: AlmanacDrawProtocol,
    kai_font_path: Path,
    hei_font_path: Path,
) -> Path:
    """渲染今日宜忌并保存 PNG。draw_data 需满足 AlmanacDrawProtocol。"""
    d: Date = draw_data.day
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)

    f_title = FontPair(kai_font_path, hei_font_path, 88)
    f_stamp = FontPair(kai_font_path, hei_font_path, 84)
    f_item = FontPair(kai_font_path, hei_font_path, ITEM_SIZE_MAX)
    f_lunar = FontPair(kai_font_path, hei_font_path, 32)
    f_date = FontPair(hei_font_path, kai_font_path, 28)
    f_info = FontPair(hei_font_path, kai_font_path, 24)
    f_sc_name = FontPair(kai_font_path, hei_font_path, 24)
    f_sc_fortune = FontPair(kai_font_path, hei_font_path, 28)
    f_foot = FontPair(hei_font_path, kai_font_path, 24)

    # 朱砂双线框
    draw.rectangle([16, 16, W - 17, H - 17], outline=RED, width=7)
    draw.rectangle([30, 30, W - 31, H - 31], outline=RED, width=2)

    # 标题 + 两侧菱形装饰
    title = "今日宜忌"
    f_title.text(draw, (CX, TITLE_Y), title, INK, anchor="mm")
    tw = draw.textlength(title, font=f_title.primary)
    for sx in (CX - tw / 2 - 38, CX + tw / 2 + 38):
        r = 9
        draw.polygon([(sx, TITLE_Y - r), (sx + r, TITLE_Y),
                      (sx, TITLE_Y + r), (sx - r, TITLE_Y)], fill=RED)

    # 公历 / 星期；农历（干支年·生肖·月日·日干支）
    f_date.text(draw, (CX, DATE1_Y),
                f"{d.year} 年 {d.month} 月 {d.day} 日  {draw_data.weekday_cn}",
                INK, anchor="mm")
    f_lunar.text(draw, (CX, DATE2_Y),
                 f"农历{draw_data.ganzhi_year}（{draw_data.zodiac}）"
                 f"{draw_data.lunar_text} · {draw_data.day_ganzhi_cn}日",
                 INK, anchor="mm")

    # 冲煞 / 幸运色信息条
    f_info.text(draw, (CX, INFO_Y),
                f"冲{draw_data.chong} 煞{draw_data.sha}    今日幸运色：{draw_data.lucky_color}",
                RED, anchor="mm")

    draw.line([70, DIV_TOP_Y, W - 70, DIV_TOP_Y], fill=RED, width=3)

    def block(top: int, bottom: int, stamp_ch: str, seal_color: tuple,
              items: Sequence[str]) -> None:
        """一枚方形朱印 + 一组事项；两者都在区块内垂直居中，事项超宽自动缩号。"""
        cy = (top + bottom) // 2
        # 方形印章（圆角 + 内衬纸色细框）
        x0, x1 = CX - SEAL_X1_OFF - SEAL_HALF * 2, CX - SEAL_X1_OFF
        y0, y1 = cy - SEAL_HALF, cy + SEAL_HALF
        draw.rounded_rectangle([x0, y0, x1, y1], radius=14, fill=seal_color)
        draw.rounded_rectangle([x0 + 8, y0 + 8, x1 - 8, y1 - 8], radius=9,
                               outline=PAPER, width=3)
        f_stamp.text(draw, ((x0 + x1) // 2, cy), stamp_ch, PAPER, anchor="mm")

        # 事项（中文序号与正文同字体，基线天然对齐）
        n = len(items)
        first_cy = cy - (n - 1) * ITEM_STEP // 2
        for i, item in enumerate(items):
            row_cy = first_cy + i * ITEM_STEP
            num = CN_NUM[i]
            num_w = draw.textlength(num, font=f_item.primary)
            f_item.text(draw, (CX + 12, row_cy), num, FADE, anchor="lm")
            x = CX + 12 + num_w + 14
            pair = f_item
            size = ITEM_SIZE_MAX
            while size > ITEM_SIZE_MIN and draw.textlength(
                item, font=ImageFont.truetype(str(kai_font_path), size)
            ) > INNER_RIGHT - x:
                size -= 2
            if size != ITEM_SIZE_MAX:
                pair = FontPair(kai_font_path, hei_font_path, size)
            pair.text(draw, (x, row_cy), item, INK, anchor="lm")

    block(YI_TOP, YI_BOTTOM, "宜", RED, draw_data.yi)
    draw.line([70, DIV_MID_Y, W - 70, DIV_MID_Y], fill=RED, width=3)
    block(JI_TOP, JI_BOTTOM, "忌", INK, draw_data.ji)

    # 十二时辰吉凶格
    f_info.text(draw, (CX, SHICHEN_LABEL_Y), "· 时辰吉凶 ·", FADE, anchor="mm")
    cell_w = (W - 60) / 12
    for i, (name, fortune) in enumerate(draw_data.shichen):
        cx_cell = 30 + cell_w * (i + 0.5)
        f_sc_name.text(draw, (cx_cell, SHICHEN_NAME_Y), name, INK, anchor="mm")
        f_sc_fortune.text(draw, (cx_cell, SHICHEN_FORTUNE_Y), fortune,
                          FORTUNE_COLOR.get(fortune, FADE), anchor="mm")

    # 底部彩蛋两行（星级逐字上色：实星朱红、空星褪色）
    stars_full = "★" * draw_data.stars
    stars_empty = "☆" * (5 - draw_data.stars)
    seg1 = f"吉利方位：{draw_data.direction}    幸运数字：{draw_data.lucky_number}    "
    w1 = draw.textlength(seg1, font=f_foot.primary)
    w2 = draw.textlength(stars_full, font=f_foot.primary) if stars_full else 0
    w3 = draw.textlength(stars_empty, font=f_foot.primary) if stars_empty else 0
    x = CX - (w1 + w2 + w3) / 2
    for seg, fill in ((seg1, FADE), (stars_full, RED), (stars_empty, FADE)):
        if seg:
            f_foot.text(draw, (x, FOOT_Y1), seg, fill, anchor="lm")
            x += draw.textlength(seg, font=f_foot.primary)
    f_foot.text(draw, (CX, FOOT_Y2), f"幸运物：{draw_data.lucky_thing} · 仅供娱乐",
                FADE, anchor="mm")

    _add_speckle(img)

    # 满运彩蛋：百无禁忌斜章（压在忌区块右下）
    if draw_data.stars >= 5:
        stamp = _make_baiwujinji_stamp(kai_font_path)
        img.paste(stamp, (545 - stamp.width // 2, 742 - stamp.height // 2), stamp)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
