"""喜报/悲报 PIL 渲染（纯逻辑，不依赖 maibot_sdk，可离线测试）。

与原插件一致：每 20 个字符插入一个换行、文字水平垂直居中、带描边。
"""

from __future__ import annotations

import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WRAP_WIDTH = 20
STROKE_WIDTH = 3


def wrap_text(text: str, width: int = WRAP_WIDTH) -> str:
    msg = text
    for i in range(width, len(msg), width):
        msg = msg[:i] + "\n" + msg[i:]
    return msg


def render_report_card(
    bg_path: Path,
    font_path: Path,
    text: str,
    font_size: int,
    out_path: Path,
    fill,
    stroke_fill,
) -> Path:
    """渲染一张喜报/悲报图片并保存到 out_path，返回 out_path。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    msg = wrap_text(text)
    img = Image.open(bg_path)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(font_path), int(font_size))

    text_width, text_height = draw.textbbox((0, 0), msg, font=font)[2:4]
    x = (img.size[0] - text_width) / 2
    y = (img.size[1] - text_height) / 2

    draw.text(
        (x, y),
        msg,
        font=font,
        fill=fill,
        stroke_width=STROKE_WIDTH,
        stroke_fill=stroke_fill,
    )
    img.save(out_path)
    return out_path


def report_output_path(runtime_dir: Path, happy: bool) -> Path:
    """渲染产物的落盘路径（runtime_dir 由调用方传入 ctx.paths.runtime_dir）。"""
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    name = "congrats" if happy else "uncongrats"
    return Path(runtime_dir) / f"{name}_{stamp}.jpg"
