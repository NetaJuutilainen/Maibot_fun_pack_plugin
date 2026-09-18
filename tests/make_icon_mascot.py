"""生成麦麦吉祥物版图标预览 v2（使用官方头像原图合成，输出预览不直接使用）。

运行：python tests/make_icon_mascot.py <官方头像路径>
方案 A：红金喜庆底 + 头像圆 + 四个功能徽章（碗/书/图/钟）
方案 B：奶白底 + 金圈 + 头像圆 + 四个功能徽章
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 512
CX = S // 2
GOLD = (245, 198, 60, 255)
BROWN = (74, 46, 20, 255)
CREAM = (255, 247, 232, 255)

AVATAR = Path(
    r"C:\Users\Neta Juutilainen\.zcode\cli\image-cache"
    r"\sess_47c35dd7-2831-4a06-ae42-b04a79a53507"
    r"\image-b57ba1353f2aaebfcf5103a5bf1311ff.png"
)
OUT_DIR = Path(__file__).resolve().parent.parent.parent / "tmp"


def rounded_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def extract_avatar_circle(size: int) -> Image.Image:
    """从官方头像（1024 白圆 + 黑色晕角）抠出圆形头像，缩放到目标尺寸。

    裁切时向内收 40px，确保圆内全是白色区域，不带黑色晕边。
    """
    src = Image.open(AVATAR).convert("RGBA")
    w, h = src.size
    side = min(w, h) - 80
    box = (
        (w - side) // 2,
        (h - side) // 2,
        (w + side) // 2,
        (h + side) // 2,
    )
    avatar = src.crop(box).resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([8, 8, size - 9, size - 9], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    avatar.putalpha(mask)
    return avatar


def red_bg():
    grad = Image.radial_gradient("L").resize((S, S))
    edge = Image.new("RGB", (S, S), (158, 28, 19))
    center = Image.new("RGB", (S, S), (226, 84, 55))
    img = Image.composite(edge, center, grad)
    draw = ImageDraw.Draw(img, "RGBA")
    for i in range(28):
        angle = i * (2 * math.pi / 28)
        half = math.radians(3.5)
        r0, r1 = 60, 320
        pts = [
            (CX + r0 * math.cos(angle - half), CX + r0 * math.sin(angle - half)),
            (CX + r1 * math.cos(angle), CX + r1 * math.sin(angle)),
            (CX + r0 * math.cos(angle + half), CX + r0 * math.sin(angle + half)),
        ]
        draw.polygon(pts, fill=(255, 210, 120, 10))
    draw.rounded_rectangle([15, 15, S - 16, S - 16], radius=104, outline=GOLD, width=9)
    return img


def cream_bg():
    img = Image.new("RGB", (S, S), CREAM)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rounded_rectangle([15, 15, S - 16, S - 16], radius=104, outline=GOLD, width=9)
    return img


# --- 功能徽章：直接贴 emoji（以后加功能 = 加一个 (emoji, 说明) 再排个位置） --

EMOJI_FONT = "C:/Windows/Fonts/seguiemj.ttf"

EMOJI_BADGES = [
    ("🍚", "今天吃什么"),
    ("📖", "答案之书"),
    ("🎉", "喜报/悲报"),
    ("🌙", "早晚安"),
]
BADGE_POS = [(CX - 141, CX - 141), (CX + 141, CX - 141),
             (CX - 141, CX + 141), (CX + 141, CX + 141)]


def draw_badges(base: Image.Image, ring_color, badge_fill):
    emoji_font = ImageFont.truetype(EMOJI_FONT, 48)
    for (emoji, _label), (bx, by) in zip(EMOJI_BADGES, BADGE_POS):
        r = 52
        tile = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        td.ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=badge_fill)
        td.text((r, r + 2), emoji, font=emoji_font, embedded_color=True, anchor="mm")
        td.ellipse([0, 0, 2 * r - 1, 2 * r - 1], outline=ring_color, width=6)
        mask = Image.new("L", (2 * r, 2 * r), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
        base.paste(tile, (bx - r, by - r), mask)
    return base


def make(path: str, bg: str) -> None:
    avatar = extract_avatar_circle(350)
    avatar = avatar.rotate(-6, resample=Image.BICUBIC)

    img = red_bg() if bg == "red" else cream_bg().convert("RGBA")
    if bg == "red":
        d = ImageDraw.Draw(img, "RGBA")
        d.ellipse([CX - 180, CX - 180, CX + 180, CX + 180], fill=(255, 255, 255, 255))
    img = img.convert("RGBA")
    img.alpha_composite(avatar, (CX - 175, CX - 175 - 4))
    img = draw_badges(img, GOLD, (255, 252, 244, 255) if bg == "red" else (255, 255, 255, 255))

    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), rounded_mask(S, 118))
    out.convert("RGB").save(path)
    print("已生成:", path)


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    make(str(OUT_DIR / "icon_mascot_A_红底.png"), "red")
    make(str(OUT_DIR / "icon_mascot_B_奶白底.png"), "cream")
