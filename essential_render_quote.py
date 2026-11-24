"""文字版群友语录 PIL 渲染（纯绘制逻辑，不依赖 maibot_sdk，可离线测试）。

仿 MakeItAQuote 电影感布局，结合大引号、群友昵称与日期元素：
    · 画布：默认 1200×630 横版深黑底（#050507）
    · 左侧：群友头像正方形裁切，支持黑白（默认）/彩色切换，经平滑余弦曲线
      遮罩自然融入右侧背景；无头像或解码失败时自动生成暗调首字肖像兜底
    · 右侧：大号半透明弯引号（“ / ”）围合自适应字号的语录正文，下方附短分割线、
      群友昵称（— 昵称）与日期（可选）

模块隔离约束：不 import maibot_sdk，不 import 同目录其他 essential_*.py，
不发起任何网络请求。
"""

from __future__ import annotations

import datetime
import io
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

BG_COLOR = (5, 5, 7)
TEXT_COLOR = (245, 245, 247)
TEXT_SHADOW = (0, 0, 0, 170)
NICK_COLOR = (212, 212, 222)
DATE_COLOR = (132, 132, 146)
QUOTE_MARK_COLOR = (220, 186, 118, 92)
DIVIDER_COLOR = (220, 186, 118, 138)
WATERMARK_COLOR = (130, 130, 142, 105)

_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_@#%&+\-./:]+")
_NO_LINE_START = frozenset("，。！？；：、”’》）】….,!?;:)]}~～")


def format_quote_date(day: datetime.date | None = None, style: str = "chinese") -> str:
    """按配置风格格式化日期：chinese=2026年11月24日，dot=2026.11.24，none=空串。"""
    target = day if day is not None else datetime.date.today()
    mode = str(style or "chinese").strip().lower()
    if mode == "none":
        return ""
    if mode == "dot":
        return f"{target.year}.{target.month:02d}.{target.day:02d}"
    return f"{target.year}年{target.month}月{target.day}日"


def _load_font(
    font_path: Path | str,
    size: int,
    variation: str | None = None,
) -> ImageFont.FreeTypeFont:
    """加载 TrueType/OpenType 字体，若支持可变字重则尝试切换。"""
    font = ImageFont.truetype(str(font_path), max(8, int(size)))
    if variation:
        try:
            font.set_variation_by_name(variation)
        except Exception:
            pass
    return font


def _glyph_bitmap(font: ImageFont.FreeTypeFont, ch: str, box: int = 96) -> bytes:
    img = Image.new("L", (box, box), 0)
    ImageDraw.Draw(img).text((box // 6, box // 6), ch, font=font, fill=255)
    return img.tobytes()


def _supports_distinct_curly_quotes(font_path: Path | str) -> bool:
    """探测字体是否同时拥有独立且字形不同的中/英文弯引号 “ 与 ”。"""
    try:
        font = _load_font(font_path, 64)
        probe = _glyph_bitmap(font, "\ue000")
        left = _glyph_bitmap(font, "\u201c")
        right = _glyph_bitmap(font, "\u201d")
    except Exception:
        return False
    if left == probe or right == probe or left == right:
        return False
    bbox = font.getbbox("\u201c")
    if bbox is None or (bbox[2] - bbox[0]) < 24:
        return False
    return True


def _pick_first_char(nickname: str) -> str:
    """从昵称提取兜底头像中心单字（跳过空白和标点符号优先取首字）。"""
    cleaned = (nickname or "").strip()
    for ch in cleaned:
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            return ch.upper() if ch.isascii() else ch
    return cleaned[0] if cleaned else "语"


def _make_fallback_avatar(
    side: int,
    nickname: str,
    font_path: Path | str,
    grayscale: bool,
) -> Image.Image:
    """无头像或图片解码失败时生成暗调渐变肖像兜底底图。"""
    base = Image.new("RGB", (side, side), (18, 20, 26))
    cx, cy = int(side * 0.43), int(side * 0.46)
    max_r = max(1.0, math.hypot(side, side) * 0.65)

    # 逐行径向渐变背景（无 numpy 依赖，630px 尺寸耗时仅数毫秒）
    top_rgb = (46, 52, 68) if not grayscale else (48, 48, 52)
    bot_rgb = (10, 11, 14)
    pixels: list[tuple[int, int, int]] = []
    for y in range(side):
        dy = y - cy
        for x in range(side):
            dx = x - cx
            dist = min(1.0, math.hypot(dx, dy) / max_r)
            t = 1.0 - dist
            t = t * t * (3.0 - 2.0 * t)
            r = int(bot_rgb[0] + (top_rgb[0] - bot_rgb[0]) * t)
            g = int(bot_rgb[1] + (top_rgb[1] - bot_rgb[1]) * t)
            b = int(bot_rgb[2] + (top_rgb[2] - bot_rgb[2]) * t)
            pixels.append((r, g, b))
    base.putdata(pixels)

    # 叠加柔和光环与昵称首字
    overlay = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    ring_r1 = int(side * 0.30)
    ring_r2 = int(side * 0.24)
    odraw.ellipse(
        [cx - ring_r1, cy - ring_r1, cx + ring_r1, cy + ring_r1],
        fill=(255, 255, 255, 10),
        outline=(255, 255, 255, 24),
        width=2,
    )
    odraw.ellipse(
        [cx - ring_r2, cy - ring_r2, cx + ring_r2, cy + ring_r2],
        outline=(255, 255, 255, 16),
        width=1,
    )

    ch = _pick_first_char(nickname)
    glyph_font = _load_font(font_path, int(side * 0.34), variation="SemiBold")
    odraw.text((cx, cy), ch, font=glyph_font, fill=(235, 236, 242, 68), anchor="mm")

    merged = Image.alpha_composite(base.convert("RGBA"), overlay)
    return merged.convert("RGB")


def _prepare_avatar_layer(
    avatar_bytes: bytes | None,
    side: int,
    nickname: str,
    font_path: Path | str,
    grayscale: bool,
) -> Image.Image:
    """裁切缩放头像、处理黑白/彩色调色，并施加平滑右侧渐变融合遮罩。"""
    avatar_rgb: Image.Image | None = None
    if avatar_bytes:
        try:
            with Image.open(io.BytesIO(avatar_bytes)) as raw:
                if raw.mode in ("RGBA", "LA") or (
                    raw.mode == "P" and "transparency" in raw.info
                ):
                    rgba = raw.convert("RGBA")
                    backdrop = Image.new("RGBA", rgba.size, (*BG_COLOR, 255))
                    raw_rgb = Image.alpha_composite(backdrop, rgba).convert("RGB")
                else:
                    raw_rgb = raw.convert("RGB")

                src_w, src_h = raw_rgb.size
                crop_side = min(src_w, src_h)
                left = (src_w - crop_side) // 2
                top = (src_h - crop_side) // 2
                cropped = raw_rgb.crop((left, top, left + crop_side, top + crop_side))
                avatar_rgb = cropped.resize((side, side), Image.Resampling.LANCZOS)
        except Exception:
            avatar_rgb = None

    if avatar_rgb is None:
        avatar_rgb = _make_fallback_avatar(side, nickname, font_path, grayscale)

    if grayscale:
        gray = avatar_rgb.convert("L")
        gray = ImageEnhance.Contrast(gray).enhance(1.14)
        gray = ImageEnhance.Brightness(gray).enhance(0.90)
        avatar_rgb = gray.convert("RGB")
    else:
        avatar_rgb = ImageEnhance.Contrast(avatar_rgb).enhance(1.06)
        avatar_rgb = ImageEnhance.Brightness(avatar_rgb).enhance(0.88)

    # 横向平滑渐隐遮罩：0..25% 保留较高不透明度，25%..95% 余弦丝滑过渡到 0
    fade_start = int(side * 0.25)
    fade_end = max(fade_start + 1, int(side * 0.95))
    max_alpha = 242
    row_alpha: list[int] = []
    for x in range(side):
        if x <= fade_start:
            a = max_alpha
        elif x >= fade_end:
            a = 0
        else:
            t = (x - fade_start) / (fade_end - fade_start)
            # 余弦插值 + 微指数，让右侧尾部收得更干净自然
            s = 0.5 * (1.0 + math.cos(math.pi * t))
            a = int(round(max_alpha * (s ** 1.15)))
        row_alpha.append(a)

    # 上下边缘施加极轻暗角，避免高对比头像贴边生硬
    edge_v = max(1, int(side * 0.06))
    mask_data: list[int] = []
    for y in range(side):
        v_factor = 1.0
        if y < edge_v:
            v_factor = 0.84 + 0.16 * (y / edge_v)
        elif y >= side - edge_v:
            v_factor = 0.84 + 0.16 * ((side - 1 - y) / edge_v)
        if v_factor >= 0.999:
            mask_data.extend(row_alpha)
        else:
            mask_data.extend(int(a * v_factor) for a in row_alpha)

    mask = Image.new("L", (side, side))
    mask.putdata(mask_data)

    avatar_rgba = avatar_rgb.convert("RGBA")
    avatar_rgba.putalpha(mask)
    return avatar_rgba


def _tokenize_paragraph(paragraph: str) -> list[str]:
    """把段落拆分为“英文词块 + 单字”序列，避免英文单词被拦腰截断。"""
    tokens: list[str] = []
    pos = 0
    n = len(paragraph)
    while pos < n:
        match = _ASCII_WORD_RE.match(paragraph, pos)
        if match:
            tokens.append(match.group(0))
            pos = match.end()
        else:
            tokens.append(paragraph[pos])
            pos += 1
    return tokens


def _wrap_paragraph_tokens(
    tokens: list[str],
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> list[str]:
    """将单个非空段落折行，严格避免行首出现闭标点，并尽量避免极短孤行。"""
    lines: list[str] = []
    current_tokens: list[str] = []

    def _cur_str() -> str:
        return "".join(current_tokens)

    for tok in tokens:
        if not current_tokens:
            if tok.isspace():
                continue
            if font.getlength(tok) <= max_width:
                current_tokens = [tok]
                continue
            # 超长英文/数字词按字符拆分
            buf = ""
            for ch in tok:
                if not buf or font.getlength(buf + ch) <= max_width:
                    buf += ch
                else:
                    lines.append(buf)
                    buf = ch
            if buf:
                current_tokens = [buf]
            continue

        candidate = _cur_str() + tok
        if font.getlength(candidate) <= max_width:
            current_tokens.append(tok)
            continue

        # 避头标点处理：绝不允许闭标点落在下一行行首
        if tok in _NO_LINE_START:
            if font.getlength(candidate) <= max_width + font.size * 0.75:
                current_tokens.append(tok)
                lines.append("".join(current_tokens).rstrip())
                current_tokens = []
                continue
            # 超出较多时，把前一个非空白字符拉到新行陪标点一起落行
            if len(current_tokens) >= 2:
                pulled = current_tokens.pop()
                line_text = "".join(current_tokens).rstrip()
                if line_text:
                    lines.append(line_text)
                current_tokens = [pulled, tok]
                continue

        lines.append(_cur_str().rstrip())
        if tok.isspace():
            current_tokens = []
        elif font.getlength(tok) <= max_width:
            current_tokens = [tok]
        else:
            current_tokens = []
            buf = ""
            for ch in tok:
                if not buf or font.getlength(buf + ch) <= max_width:
                    buf += ch
                else:
                    lines.append(buf)
                    buf = ch
            if buf:
                current_tokens = [buf]

    if current_tokens and "".join(current_tokens).strip():
        lines.append("".join(current_tokens).rstrip())

    return lines


def _wrap_text_to_width(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> list[str]:
    """按像素宽度将支持显式换行的中英混排文本折行。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        normalized = "……"

    lines: list[str] = []
    for raw_para in normalized.split("\n"):
        para = raw_para.strip()
        if not para:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        tokens = _tokenize_paragraph(para)
        lines.extend(_wrap_paragraph_tokens(tokens, font, max_width))

    while lines and lines[-1] == "":
        lines.pop()
    return lines or ["……"]


def _truncate_line(
    line: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> str:
    """将单行文本截断至不超过 max_width 并追加省略号。"""
    ellipsis = "…"
    if font.getlength(line) <= max_width:
        return line
    trimmed = line.rstrip()
    while trimmed and font.getlength(trimmed + ellipsis) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


def _has_short_orphan(
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> bool:
    """判断多行文本末行是否为仅有 1~2 个有效字/标点的孤行。"""
    non_empty = [ln for ln in lines if ln.strip()]
    if len(non_empty) <= 1:
        return False
    last = non_empty[-1].strip()
    core = "".join(ch for ch in last if ch not in _NO_LINE_START and not ch.isspace())
    if len(core) <= 2:
        return True
    return font.getlength(last) < min(max_width * 0.24, font.size * 2.6)


def _fit_quote_layout(
    text: str,
    font_path: Path | str,
    max_width: float,
    max_height: float,
    *,
    max_size: int = 54,
    min_size: int = 18,
    max_lines: int = 10,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """在字号区间内搜索能舒适容纳正文的最大字号与折行结果（兼顾避孤行）。"""
    candidates: list[tuple[ImageFont.FreeTypeFont, list[str], int]] = []
    for size in range(max_size, min_size - 1, -2):
        font = _load_font(font_path, size, variation="Medium")
        lines = _wrap_text_to_width(text, font, max_width)
        line_step = max(size + 8, int(round(size * 1.42)))
        total_h = len(lines) * line_step - (line_step - size)
        if len(lines) <= max_lines and total_h <= max_height:
            candidates.append((font, lines, line_step))
            if not _has_short_orphan(lines, font, max_width):
                if len(candidates) == 1:
                    return font, lines, line_step
                break

    if candidates:
        best_font, best_lines, best_step = candidates[0]
        if _has_short_orphan(best_lines, best_font, max_width):
            for f_c, l_c, s_c in candidates[1:]:
                if best_font.size - f_c.size <= 14 and not _has_short_orphan(l_c, f_c, max_width):
                    return f_c, l_c, s_c
        return best_font, best_lines, best_step

    # 最坏情况：使用最小字号并对超出行数做省略号截断
    font = _load_font(font_path, min_size, variation="Medium")
    line_step = max(min_size + 8, int(round(min_size * 1.42)))
    fit_lines = max(1, min(max_lines, int((max_height + (line_step - min_size)) // line_step)))
    lines = _wrap_text_to_width(text, font, max_width)
    if len(lines) > fit_lines:
        lines = lines[:fit_lines]
        while lines and lines[-1] == "":
            lines.pop()
        if lines:
            lines[-1] = _truncate_line(lines[-1], font, max_width * 0.94)
        else:
            lines = ["……"]
    return font, lines, line_step


def _fit_nickname_layout(
    nickname: str,
    font_path: Path | str,
    max_width: float,
    *,
    max_size: int = 27,
    min_size: int = 18,
    max_lines: int = 3,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """自适应排版群友昵称：优先 1~2 行大字号，超长自动缩号并换行完整显示。"""
    clean_nick = (nickname or "").strip() or "匿名群友"
    full_text = f"— {clean_nick}"

    for line_budget in (2, max_lines):
        for size in range(max_size, min_size - 1, -2):
            font = _load_font(font_path, size, variation="Medium")
            lines = _wrap_text_to_width(full_text, font, max_width)
            if len(lines) <= line_budget:
                line_step = max(size + 6, int(round(size * 1.32)))
                return font, lines, line_step

    # 极端超长安全阀：保留 max_lines 行并在末行补省略号
    font = _load_font(font_path, min_size, variation="Medium")
    line_step = max(min_size + 6, int(round(min_size * 1.32)))
    lines = _wrap_text_to_width(full_text, font, max_width)[:max_lines]
    if lines:
        lines[-1] = _truncate_line(lines[-1], font, max_width * 0.94)
    return font, lines, line_step


def _render_tight_glyph_rgba(
    glyph: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
) -> Image.Image:
    """将单个大号标点按实际墨迹包围盒紧致裁切，避免字体留白不均导致的偏移。"""
    pad = max(32, int(font.size * 2))
    canvas = Image.new("RGBA", (pad, pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((pad // 2, pad // 2), glyph, font=font, fill=fill, anchor="mm")
    bbox = canvas.getbbox()
    if bbox is None:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    return canvas.crop(bbox)


def _draw_text_with_shadow(
    layer: Image.Image,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, ...],
    *,
    anchor: str = "mm",
    shadow_offset: tuple[int, int] = (0, 2),
    shadow_alpha: int = 165,
) -> None:
    """在 RGBA 图层上绘制带柔和深色投影的文字，提高跨渐变区对比度。"""
    draw = ImageDraw.Draw(layer)
    sx, sy = xy[0] + shadow_offset[0], xy[1] + shadow_offset[1]
    draw.text((sx, sy), text, font=font, fill=(0, 0, 0, shadow_alpha), anchor=anchor)
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def render_quote_card(
    text: str,
    nickname: str,
    *,
    avatar_bytes: bytes | None = None,
    date_text: str = "",
    font_path: Path | str,
    accent_font_path: Path | str | None = None,
    grayscale: bool = True,
    width: int = 1200,
    height: int = 630,
    watermark: str = "",
) -> bytes:
    """渲染文字版群友语录图片，返回 PNG 字节流。"""
    width = max(640, int(width))
    height = max(360, int(height))
    font_path = Path(font_path)

    canvas = Image.new("RGBA", (width, height), (*BG_COLOR, 255))

    # 1. 左侧头像层（高度撑满的正方形）
    avatar_side = min(height, int(width * 0.56))
    avatar_layer = _prepare_avatar_layer(
        avatar_bytes=avatar_bytes,
        side=avatar_side,
        nickname=nickname,
        font_path=font_path,
        grayscale=grayscale,
    )
    canvas.alpha_composite(avatar_layer, dest=(0, (height - avatar_side) // 2))

    # 2. 计算右侧文字排版版心
    content_left = int(width * 0.455)
    content_right = width - int(width * 0.052)
    content_width = max(240, content_right - content_left)
    content_cx = (content_left + content_right) / 2.0

    # 为大引号与落款留出舒适呼吸空间（先确定落款多行高度，再计算正文可用高度）
    quote_body_max_w = content_width - 104
    nick_font, nick_lines, nick_step = _fit_nickname_layout(
        nickname,
        font_path,
        max_width=content_width - 24,
        max_size=max(20, int(round(height * 0.043))),
        min_size=18,
        max_lines=3,
    )
    date_font = _load_font(font_path, max(15, int(round(height * 0.031))), variation="Regular")

    clean_date = (date_text or "").strip()
    nick_font_size = nick_font.size
    nick_block_h = len(nick_lines) * nick_step - (nick_step - nick_font_size)
    date_h = 0
    if clean_date:
        date_bbox = date_font.getbbox(clean_date)
        date_h = (date_bbox[3] - date_bbox[1]) if date_bbox else date_font.size

    gap_body_div = 24
    divider_h = 2
    gap_div_nick = 18
    gap_nick_date = 10 if clean_date else 0
    footer_h = gap_body_div + divider_h + gap_div_nick + nick_block_h + gap_nick_date + date_h

    top_margin = int(height * 0.10)
    bottom_margin = int(height * 0.095)
    body_max_h = max(100, height - top_margin - bottom_margin - footer_h)

    body_font, lines, line_step = _fit_quote_layout(
        text,
        font_path,
        max_width=quote_body_max_w,
        max_height=body_max_h,
        max_size=max(36, int(round(height * 0.084))),
        min_size=18,
        max_lines=10,
    )

    body_font_size = body_font.size
    body_block_h = len(lines) * line_step - (line_step - body_font_size)
    total_block_h = body_block_h + footer_h
    block_top = (height - total_block_h) / 2.0 - 4.0
    block_top = max(float(top_margin), block_top)

    # 3. 测算正文最大实际行宽，使大引号自然贴合语录四周
    max_line_w = max((body_font.getlength(line) for line in lines if line), default=120.0)
    body_left_edge = content_cx - max_line_w / 2.0
    body_right_edge = content_cx + max_line_w / 2.0
    body_bottom = block_top + body_block_h

    # 4. 绘制大引号图层（位于正文下层，低透明度暖金色）
    quote_font_path = font_path
    if accent_font_path and _supports_distinct_curly_quotes(accent_font_path):
        quote_font_path = Path(accent_font_path)
    quote_glyph_size = max(56, min(132, int(round(body_font_size * 2.45))))
    quote_font = _load_font(quote_font_path, quote_glyph_size, variation="Black")

    open_glyph = _render_tight_glyph_rgba("\u201c", quote_font, QUOTE_MARK_COLOR)
    close_glyph = _render_tight_glyph_rgba("\u201d", quote_font, QUOTE_MARK_COLOR)

    # 大引号留出清晰间距，避免与正文字首/字尾粘连
    gap_q_x = max(10, int(round(body_font_size * 0.28)))
    open_x = int(round(body_left_edge - open_glyph.width - gap_q_x))
    open_y = int(round(block_top - open_glyph.height * 0.48))
    open_x = max(content_left - 18, open_x)
    open_y = max(20, open_y)

    close_x = int(round(body_right_edge + gap_q_x))
    close_y = int(round(body_bottom - close_glyph.height * 0.24))
    close_x = min(width - close_glyph.width - 24, close_x)
    close_y = min(height - close_glyph.height - 20, close_y)

    text_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    text_layer.alpha_composite(open_glyph, dest=(open_x, open_y))
    text_layer.alpha_composite(close_glyph, dest=(close_x, close_y))

    # 5. 绘制语录正文（逐行水平居中）
    shadow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_layer)
    for idx, line in enumerate(lines):
        if not line:
            continue
        ly = block_top + idx * line_step + body_font_size / 2.0
        sdraw.text((content_cx, ly + 2), line, font=body_font, fill=(0, 0, 0, 175), anchor="mm")
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=2.5))
    text_layer = Image.alpha_composite(text_layer, shadow_layer)

    tdraw = ImageDraw.Draw(text_layer)
    for idx, line in enumerate(lines):
        if not line:
            continue
        ly = block_top + idx * line_step + body_font_size / 2.0
        tdraw.text((content_cx, ly), line, font=body_font, fill=(*TEXT_COLOR, 255), anchor="mm")

    # 6. 绘制分割线、群友昵称（支持多行）与日期
    div_y = int(round(body_bottom + gap_body_div))
    div_half_w = 28
    tdraw.rounded_rectangle(
        [content_cx - div_half_w, div_y, content_cx + div_half_w, div_y + divider_h],
        radius=1,
        fill=DIVIDER_COLOR,
    )

    nick_top = div_y + divider_h + gap_div_nick
    for idx, nline in enumerate(nick_lines):
        if not nline:
            continue
        nick_cy = nick_top + idx * nick_step + nick_font_size / 2.0
        _draw_text_with_shadow(
            text_layer,
            (content_cx, nick_cy),
            nline,
            nick_font,
            (*NICK_COLOR, 255),
            anchor="mm",
            shadow_offset=(0, 1),
            shadow_alpha=145,
        )

    if clean_date:
        date_cy = nick_top + nick_block_h + gap_nick_date + date_h / 2.0
        _draw_text_with_shadow(
            text_layer,
            (content_cx, date_cy),
            clean_date,
            date_font,
            (*DATE_COLOR, 255),
            anchor="mm",
            shadow_offset=(0, 1),
            shadow_alpha=130,
        )

    # 7. 可选右下角暗水印
    clean_wm = (watermark or "").strip()
    if clean_wm:
        wm_font = _load_font(font_path, 14, variation="Regular")
        tdraw.text(
            (width - 24, height - 18),
            clean_wm,
            font=wm_font,
            fill=WATERMARK_COLOR,
            anchor="rb",
        )

    final = Image.alpha_composite(canvas, text_layer).convert("RGB")
    buf = io.BytesIO()
    final.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_quote_card_to_file(
    output_path: Path | str,
    text: str,
    nickname: str,
    **kwargs,
) -> Path:
    """渲染文字版群友语录并写入指定路径，返回 Path。"""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = render_quote_card(text, nickname, **kwargs)
    out.write_bytes(data)
    return out
