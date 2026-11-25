"""文字版群友语录 PIL 渲染（纯绘制逻辑，不依赖 maibot_sdk，可离线测试）。

仿 MakeItAQuote 电影感布局，结合大引号、群友昵称与日期元素：
    · 画布：默认 1200×630 横版深黑底（#050507）
    · 左侧：群友头像正方形裁切，支持黑白（默认）/彩色切换，经平滑余弦曲线
      遮罩自然融入右侧背景；无头像或解码失败时自动生成暗调首字肖像兜底
    · 右侧：大号半透明弯引号（“ / ”）围合自适应字号的语录正文，下方附短分割线、
      群友昵称（— 昵称）与日期（可选）；正文与昵称支持彩色 Emoji（含 ZWJ / 肤色 /
      国旗 / 键帽等复合序列，无需 libraqm 即可跨平台离线渲染）

模块隔离约束：不 import maibot_sdk，不 import 同目录其他 essential_*.py，
不发起任何网络请求。
"""

from __future__ import annotations

import datetime
import io
import math
import re
import struct
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

_ASCII_WORD_CHAR_RE = re.compile(r"[A-Za-z0-9_@#%&+\-./:]")
_NO_LINE_START = frozenset("，。！？；：、”’》）】….,!?;:)]}~～")

_SYSTEM_EMOJI_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/seguiemj.ttf"),
    Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    Path("/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf"),
)

_PRIMARY_PROBE_CACHE: dict[str, "_PrimaryFontChecker"] = {}
_EMOJI_FONT_CACHE: dict[str, "_EmojiFont"] = {}


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


def _glyph_bitmap(font: ImageFont.FreeTypeFont, ch: str, box: int = 80) -> bytes:
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


class _PrimaryFontChecker:
    """主字体缺字探测器（按字体文件缓存，避免字号搜索循环重复探测）。"""

    def __init__(self, font_path: Path | str) -> None:
        self._font = _load_font(font_path, 40)
        self._probe = _glyph_bitmap(self._font, "\ue000")
        self._cache: dict[str, bool] = {}

    def has_glyph(self, ch: str) -> bool:
        if not ch:
            return True
        if len(ch) == 1 and (ord(ch) < 128 or ch.isspace()):
            return True
        cached = self._cache.get(ch)
        if cached is not None:
            return cached
        ok = _glyph_bitmap(self._font, ch) != self._probe
        self._cache[ch] = ok
        return ok


def _get_primary_checker(font_path: Path | str) -> _PrimaryFontChecker:
    key = str(Path(font_path).resolve())
    checker = _PRIMARY_PROBE_CACHE.get(key)
    if checker is None:
        checker = _PrimaryFontChecker(font_path)
        _PRIMARY_PROBE_CACHE[key] = checker
    return checker


def _read_coverage_gids(data: bytes, cov_off: int) -> list[int]:
    """解析 OpenType Coverage 表（Format 1/2）返回 GlyphID 列表。"""
    fmt = struct.unpack(">H", data[cov_off : cov_off + 2])[0]
    if fmt == 1:
        cnt = struct.unpack(">H", data[cov_off + 2 : cov_off + 4])[0]
        return list(struct.unpack(f">{cnt}H", data[cov_off + 4 : cov_off + 4 + 2 * cnt]))
    if fmt == 2:
        cnt = struct.unpack(">H", data[cov_off + 2 : cov_off + 4])[0]
        gids: list[int] = []
        for idx in range(cnt):
            start_g, end_g, _ = struct.unpack(
                ">HHH", data[cov_off + 4 + idx * 6 : cov_off + 10 + idx * 6]
            )
            gids.extend(range(start_g, end_g + 1))
        return gids
    return []


def _parse_emoji_font_tables(
    font_path: Path,
) -> tuple[dict[int, int], dict[int, int], dict[tuple[int, ...], int], bool]:
    """从 TTF 提取 cmap（码点→GID、GID→PUA）与 GSUB Type 4 连字映射。"""
    data = font_path.read_bytes()
    if len(data) < 12:
        return {}, {}, {}, False
    num_tables = struct.unpack(">H", data[4:6])[0]
    tables: dict[str, tuple[int, int]] = {}
    for idx in range(num_tables):
        base = 12 + idx * 16
        if base + 16 > len(data):
            break
        tag = data[base : base + 4].decode("latin-1")
        off, ln = struct.unpack(">II", data[base + 8 : base + 16])
        tables[tag] = (off, ln)

    is_cbdt = "CBDT" in tables
    cp_to_gid: dict[int, int] = {}
    gid_to_pua: dict[int, int] = {}

    if "cmap" in tables:
        cmap_off, _ = tables["cmap"]
        num_sub = struct.unpack(">H", data[cmap_off + 2 : cmap_off + 4])[0]
        for idx in range(num_sub):
            sub_rec = cmap_off + 4 + idx * 8
            _, _, rel_off = struct.unpack(">HHI", data[sub_rec : sub_rec + 8])
            so = cmap_off + rel_off
            fmt = struct.unpack(">H", data[so : so + 2])[0]
            if fmt == 12:
                ngrp = struct.unpack(">I", data[so + 12 : so + 16])[0]
                for g in range(ngrp):
                    sc, ec, sg = struct.unpack(
                        ">III", data[so + 16 + g * 12 : so + 28 + g * 12]
                    )
                    for cp in range(sc, ec + 1):
                        gid = sg + (cp - sc)
                        cp_to_gid[cp] = gid
                        if 0xE000 <= cp <= 0xF8FF or cp >= 0xF0000:
                            gid_to_pua.setdefault(gid, cp)
            elif fmt == 4 and not cp_to_gid:
                seg_cnt = struct.unpack(">H", data[so + 6 : so + 8])[0] // 2
                ends = struct.unpack(f">{seg_cnt}H", data[so + 14 : so + 14 + 2 * seg_cnt])
                starts_off = so + 16 + 2 * seg_cnt
                starts = struct.unpack(
                    f">{seg_cnt}H", data[starts_off : starts_off + 2 * seg_cnt]
                )
                deltas_off = starts_off + 2 * seg_cnt
                deltas = struct.unpack(
                    f">{seg_cnt}h", data[deltas_off : deltas_off + 2 * seg_cnt]
                )
                ranges_off = deltas_off + 2 * seg_cnt
                ranges = struct.unpack(
                    f">{seg_cnt}H", data[ranges_off : ranges_off + 2 * seg_cnt]
                )
                for seg in range(seg_cnt):
                    sc, ec, delta, roff = starts[seg], ends[seg], deltas[seg], ranges[seg]
                    if sc == 0xFFFF and ec == 0xFFFF:
                        continue
                    for cp in range(sc, ec + 1):
                        if roff == 0:
                            gid = (cp + delta) & 0xFFFF
                        else:
                            idx_off = ranges_off + 2 * seg + roff + 2 * (cp - sc)
                            gid = struct.unpack(">H", data[idx_off : idx_off + 2])[0]
                            if gid != 0:
                                gid = (gid + delta) & 0xFFFF
                        if gid != 0:
                            cp_to_gid[cp] = gid

    lig_map: dict[tuple[int, ...], int] = {}
    if "GSUB" in tables and gid_to_pua:
        gsub_off, _ = tables["GSUB"]
        lookup_list_off = gsub_off + struct.unpack(">H", data[gsub_off + 8 : gsub_off + 10])[0]
        lookup_cnt = struct.unpack(">H", data[lookup_list_off : lookup_list_off + 2])[0]
        for li in range(lookup_cnt):
            lk_off = lookup_list_off + struct.unpack(
                ">H", data[lookup_list_off + 2 + li * 2 : lookup_list_off + 4 + li * 2]
            )[0]
            lk_type, _flag, sub_cnt = struct.unpack(">HHH", data[lk_off : lk_off + 6])
            for si in range(sub_cnt):
                sub_off = lk_off + struct.unpack(
                    ">H", data[lk_off + 6 + si * 2 : lk_off + 8 + si * 2]
                )[0]
                actual_type = lk_type
                if lk_type == 7:
                    ext_fmt, ext_type, ext_rel = struct.unpack(">HHI", data[sub_off : sub_off + 8])
                    if ext_fmt != 1:
                        continue
                    actual_type = ext_type
                    sub_off = sub_off + ext_rel
                if actual_type != 4:
                    continue
                fmt, cov_rel, _lig_set_cnt = struct.unpack(">HHH", data[sub_off : sub_off + 6])
                if fmt != 1:
                    continue
                first_gids = _read_coverage_gids(data, sub_off + cov_rel)
                for fi, first_gid in enumerate(first_gids):
                    ls_off = sub_off + struct.unpack(
                        ">H", data[sub_off + 6 + fi * 2 : sub_off + 8 + fi * 2]
                    )[0]
                    lig_cnt = struct.unpack(">H", data[ls_off : ls_off + 2])[0]
                    for j in range(lig_cnt):
                        lig_off = ls_off + struct.unpack(
                            ">H", data[ls_off + 2 + j * 2 : ls_off + 4 + j * 2]
                        )[0]
                        lig_gid, comp_cnt = struct.unpack(">HH", data[lig_off : lig_off + 4])
                        if comp_cnt < 2:
                            continue
                        comps = struct.unpack(
                            f">{comp_cnt - 1}H",
                            data[lig_off + 4 : lig_off + 4 + 2 * (comp_cnt - 1)],
                        )
                        lig_map.setdefault((first_gid,) + comps, lig_gid)

    return cp_to_gid, gid_to_pua, lig_map, is_cbdt


def _load_emoji_pil_font(font_path: Path) -> ImageFont.FreeTypeFont:
    """加载 Emoji 字体；CBDT 位图字体仅接受固定 strike（109px），按序列兜底探测。"""
    for strike in (109, 128, 96, 64, 40):
        try:
            return ImageFont.truetype(str(font_path), strike)
        except OSError:
            continue
    return ImageFont.truetype(str(font_path), 109)


class _EmojiFont:
    """支持彩色矢量/位图 Emoji 解析与多字号缩放缓存（兼容无 libraqm 环境）。"""

    def __init__(self, font_path: Path) -> None:
        self.path = font_path
        self._pil_font = _load_emoji_pil_font(font_path)
        self._cp_to_gid, self._gid_to_pua, self._lig_map, self._is_cbdt = (
            _parse_emoji_font_tables(font_path)
        )
        self._probe = self._draw_raw("\ue000")
        self._tile_cache: dict[tuple[str, int], Image.Image | None] = {}
        self._resolve_cache: dict[str, list[str]] = {}

    def _draw_raw(self, glyph_str: str) -> bytes:
        im = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
        ImageDraw.Draw(im).text(
            (20, 20), glyph_str, font=self._pil_font, fill=(255, 255, 255, 255), embedded_color=True
        )
        return im.tobytes()

    def _can_render_single(self, ch: str) -> bool:
        if not ch or len(ch) != 1:
            return False
        if self._cp_to_gid and ord(ch) not in self._cp_to_gid:
            return False
        im = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
        ImageDraw.Draw(im).text(
            (20, 20), ch, font=self._pil_font, fill=(255, 255, 255, 255), embedded_color=True
        )
        return im.getbbox() is not None and im.tobytes() != self._probe

    def _resolve_ligature(self, seq: str) -> str | None:
        if not self._lig_map or not self._gid_to_pua:
            return None
        for cand in (seq, seq.replace("\ufe0f", "").replace("\ufe0e", "")):
            if len(cand) < 2:
                continue
            gids = tuple(self._cp_to_gid.get(ord(c), 0) for c in cand)
            if all(gids) and gids in self._lig_map:
                pua = self._gid_to_pua.get(self._lig_map[gids])
                if pua:
                    return chr(pua)
        return None

    def resolve(self, cluster: str) -> list[str]:
        """将 Emoji 簇解析为可直接由 Pillow 单字绘制的字符列表；不支持则返回 []。"""
        cached = self._resolve_cache.get(cluster)
        if cached is not None:
            return cached

        res: list[str] = []
        lig = self._resolve_ligature(cluster)
        if lig and self._can_render_single(lig):
            res = [lig]
        else:
            stripped_tone = "".join(c for c in cluster if not (0x1F3FB <= ord(c) <= 0x1F3FF))
            if stripped_tone != cluster:
                lig2 = self._resolve_ligature(stripped_tone)
                if lig2 and self._can_render_single(lig2):
                    res = [lig2]

            if not res:
                clean = cluster.replace("\ufe0f", "").replace("\ufe0e", "")
                if len(clean) == 1 and self._can_render_single(clean):
                    res = [clean]
                elif "\u200d" in cluster or len(clean) > 1:
                    # 未命中连字的复合序列：逐段尝试解析其有效部件，避免豆腐块
                    parts: list[str] = []
                    for piece in stripped_tone.split("\u200d"):
                        piece_clean = piece.replace("\ufe0f", "").replace("\ufe0e", "")
                        if not piece_clean:
                            continue
                        piece_lig = self._resolve_ligature(piece)
                        if piece_lig and self._can_render_single(piece_lig):
                            parts.append(piece_lig)
                        else:
                            for ch in piece_clean:
                                if (
                                    ord(ch) >= 128
                                    and ord(ch) != 0x20E3
                                    and self._can_render_single(ch)
                                ):
                                    parts.append(ch)
                    res = parts

        self._resolve_cache[cluster] = res
        return res

    def render_tile(self, glyph_char: str, target_px: int) -> Image.Image | None:
        """按目标字号渲染单枚 Emoji 并做紧致裁切与等比缩放。"""
        key = (glyph_char, int(target_px))
        if key in self._tile_cache:
            return self._tile_cache[key]

        canvas = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text(
            (20, 20),
            glyph_char,
            font=self._pil_font,
            fill=(255, 255, 255, 255),
            embedded_color=True,
        )
        bbox = canvas.getbbox()
        if bbox is None:
            self._tile_cache[key] = None
            return None

        cropped = canvas.crop(bbox)
        max_dim = max(10, int(round(target_px * 1.06)))
        scale = min(max_dim / max(1, cropped.width), max_dim / max(1, cropped.height))
        new_w = max(1, int(round(cropped.width * scale)))
        new_h = max(1, int(round(cropped.height * scale)))
        if new_w != cropped.width or new_h != cropped.height:
            tile = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)
        else:
            tile = cropped

        if len(self._tile_cache) >= 512:
            self._tile_cache.clear()
        self._tile_cache[key] = tile
        return tile


def _resolve_emoji_font(
    primary_font_path: Path,
    explicit_emoji_path: Path | str | None = None,
) -> _EmojiFont | None:
    """按优先级定位并加载 Emoji 字体：显式入参 → 主字体同目录 NotoColorEmoji.ttf → 系统字体。"""
    candidates: list[Path] = []
    if explicit_emoji_path:
        candidates.append(Path(explicit_emoji_path))
    candidates.append(primary_font_path.parent / "NotoColorEmoji.ttf")
    candidates.extend(_SYSTEM_EMOJI_FONT_CANDIDATES)

    for cand in candidates:
        try:
            if not cand.is_file():
                continue
            key = str(cand.resolve())
            efont = _EMOJI_FONT_CACHE.get(key)
            if efont is None:
                efont = _EmojiFont(cand)
                _EMOJI_FONT_CACHE[key] = efont
            return efont
        except Exception:
            continue
    return None


def _is_regional_indicator(cp: int) -> bool:
    return 0x1F1E6 <= cp <= 0x1F1FF


def _is_skin_tone(cp: int) -> bool:
    return 0x1F3FB <= cp <= 0x1F3FF


def _is_tag_char(cp: int) -> bool:
    return 0xE0020 <= cp <= 0xE007F


def _split_clusters(text: str) -> list[str]:
    """将文本拆分为视觉簇（合并国旗双字符、VS16、肤色修饰、键帽、Tag 与 ZWJ 序列）。"""
    clusters: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        cp = ord(ch)
        if _is_regional_indicator(cp) and i + 1 < n and _is_regional_indicator(ord(text[i + 1])):
            clusters.append(text[i : i + 2])
            i += 2
            continue
        buf = [ch]
        i += 1
        while i < n:
            nxt = text[i]
            ncp = ord(nxt)
            if ncp in (0xFE0E, 0xFE0F, 0x20E3) or _is_skin_tone(ncp) or _is_tag_char(ncp):
                buf.append(nxt)
                i += 1
                continue
            if ncp == 0x200D and i + 1 < n:
                buf.append(nxt)
                i += 1
                buf.append(text[i])
                i += 1
                continue
            break
        clusters.append("".join(buf))
    return clusters


def _cluster_prefers_emoji(
    cluster: str,
    primary_checker: _PrimaryFontChecker,
    emoji_font: _EmojiFont | None,
) -> list[str]:
    """判断单个簇是否应交由 Emoji 字体渲染，并返回解析后的 Emoji 字符列表。"""
    if emoji_font is None or not cluster:
        return []
    if len(cluster) == 1 and (ord(cluster) < 128 or cluster.isspace()):
        return []

    explicit_emoji = (
        "\ufe0f" in cluster
        or "\u20e3" in cluster
        or "\u200d" in cluster
        or any(_is_skin_tone(ord(c)) or _is_regional_indicator(ord(c)) for c in cluster)
    )
    if explicit_emoji:
        resolved = emoji_font.resolve(cluster)
        if resolved:
            return resolved

    if len(cluster) == 1 and primary_checker.has_glyph(cluster):
        return []

    return emoji_font.resolve(cluster)


def _layout_line_runs(
    line: str,
    primary_font: ImageFont.FreeTypeFont,
    primary_checker: _PrimaryFontChecker,
    emoji_font: _EmojiFont | None,
) -> list[tuple[str, object, float]]:
    """将一行文本切分为合并后的 (kind, payload, advance_width) 序列。"""
    if not line:
        return []
    runs: list[tuple[str, object, float]] = []
    text_buf: list[str] = []
    pad_x = max(2, int(round(primary_font.size * 0.14)))

    def _flush_text() -> None:
        if text_buf:
            seg = "".join(text_buf)
            runs.append(("text", seg, float(primary_font.getlength(seg))))
            text_buf.clear()

    for cluster in _split_clusters(line):
        emoji_chars = _cluster_prefers_emoji(cluster, primary_checker, emoji_font)
        if emoji_chars and emoji_font is not None:
            rendered_any = False
            for ech in emoji_chars:
                tile = emoji_font.render_tile(ech, primary_font.size)
                if tile is not None:
                    _flush_text()
                    runs.append(("emoji", tile, float(tile.width + pad_x)))
                    rendered_any = True
            if rendered_any:
                continue

        # 未命中 Emoji 字体时，剥离控制字符免出豆腐块
        cleaned = (
            cluster.replace("\ufe0f", "")
            .replace("\ufe0e", "")
            .replace("\u200d", "")
            .replace("\u20e3", "")
        )
        if cleaned:
            text_buf.append(cleaned)

    _flush_text()
    return runs


def _measure_mixed_width(
    text: str,
    primary_font: ImageFont.FreeTypeFont,
    primary_checker: _PrimaryFontChecker,
    emoji_font: _EmojiFont | None,
) -> float:
    """精确测算含 Emoji 混排文本的实际渲染像素宽度。"""
    if not text:
        return 0.0
    if text.isascii():
        return float(primary_font.getlength(text))
    return sum(w for _, _, w in _layout_line_runs(text, primary_font, primary_checker, emoji_font))


def _pick_first_char(nickname: str) -> str:
    """从昵称提取兜底头像中心单字（跳过空白和标点符号优先取首字）。"""
    cleaned = (nickname or "").strip()
    for cluster in _split_clusters(cleaned):
        if len(cluster) == 1 and (cluster.isalnum() or "\u4e00" <= cluster <= "\u9fff"):
            return cluster.upper() if cluster.isascii() else cluster
    clusters = _split_clusters(cleaned)
    return clusters[0] if clusters else "语"


def _make_fallback_avatar(
    side: int,
    nickname: str,
    font_path: Path | str,
    grayscale: bool,
    emoji_font: _EmojiFont | None = None,
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

    # 叠加柔和光环与昵称首字（兼容纯 Emoji 昵称）
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
    primary_checker = _get_primary_checker(font_path)
    target_px = int(side * 0.34)
    emoji_chars = _cluster_prefers_emoji(ch, primary_checker, emoji_font)
    drawn_emoji = False
    if emoji_chars and emoji_font is not None:
        tile = emoji_font.render_tile(emoji_chars[0], target_px)
        if tile is not None:
            faded = tile.copy()
            alpha = faded.getchannel("A").point(lambda a: int(a * 0.28))
            faded.putalpha(alpha)
            overlay.alpha_composite(
                faded, dest=(cx - faded.width // 2, cy - faded.height // 2)
            )
            drawn_emoji = True
    if not drawn_emoji:
        glyph_font = _load_font(font_path, target_px, variation="SemiBold")
        odraw.text((cx, cy), ch, font=glyph_font, fill=(235, 236, 242, 68), anchor="mm")

    merged = Image.alpha_composite(base.convert("RGBA"), overlay)
    return merged.convert("RGB")


def _prepare_avatar_layer(
    avatar_bytes: bytes | None,
    side: int,
    nickname: str,
    font_path: Path | str,
    grayscale: bool,
    emoji_font: _EmojiFont | None = None,
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
        avatar_rgb = _make_fallback_avatar(
            side, nickname, font_path, grayscale, emoji_font=emoji_font
        )

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
    """把段落拆分为“英文词块 + Emoji 簇 + 单字”序列，避免英文单词和复合 Emoji 被拆断。"""
    tokens: list[str] = []
    ascii_buf: list[str] = []
    for cluster in _split_clusters(paragraph):
        if len(cluster) == 1 and _ASCII_WORD_CHAR_RE.fullmatch(cluster):
            ascii_buf.append(cluster)
        else:
            if ascii_buf:
                tokens.append("".join(ascii_buf))
                ascii_buf.clear()
            tokens.append(cluster)
    if ascii_buf:
        tokens.append("".join(ascii_buf))
    return tokens


def _wrap_paragraph_tokens(
    tokens: list[str],
    font: ImageFont.FreeTypeFont,
    max_width: float,
    primary_checker: _PrimaryFontChecker,
    emoji_font: _EmojiFont | None,
) -> list[str]:
    """将单个非空段落折行，严格避免行首出现闭标点，并尽量避免极短孤行。"""
    lines: list[str] = []
    current_tokens: list[str] = []

    def _cur_str() -> str:
        return "".join(current_tokens)

    def _width(s: str) -> float:
        return _measure_mixed_width(s, font, primary_checker, emoji_font)

    for tok in tokens:
        if not current_tokens:
            if tok.isspace():
                continue
            if _width(tok) <= max_width or len(_split_clusters(tok)) <= 1:
                current_tokens = [tok]
                continue
            buf = ""
            for ch in tok:
                if not buf or _width(buf + ch) <= max_width:
                    buf += ch
                else:
                    lines.append(buf)
                    buf = ch
            if buf:
                current_tokens = [buf]
            continue

        candidate = _cur_str() + tok
        if _width(candidate) <= max_width:
            current_tokens.append(tok)
            continue

        if tok in _NO_LINE_START:
            if _width(candidate) <= max_width + font.size * 0.75:
                current_tokens.append(tok)
                lines.append("".join(current_tokens).rstrip())
                current_tokens = []
                continue
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
        elif _width(tok) <= max_width or len(_split_clusters(tok)) <= 1:
            current_tokens = [tok]
        else:
            current_tokens = []
            buf = ""
            for ch in tok:
                if not buf or _width(buf + ch) <= max_width:
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
    primary_checker: _PrimaryFontChecker,
    emoji_font: _EmojiFont | None,
) -> list[str]:
    """按像素宽度将支持显式换行的中英混排与 Emoji 文本折行。"""
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
        lines.extend(
            _wrap_paragraph_tokens(tokens, font, max_width, primary_checker, emoji_font)
        )

    while lines and lines[-1] == "":
        lines.pop()
    return lines or ["……"]


def _truncate_line(
    line: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
    primary_checker: _PrimaryFontChecker,
    emoji_font: _EmojiFont | None,
) -> str:
    """将单行文本按视觉簇截断至不超过 max_width 并追加省略号（绝不切碎 Emoji 序列）。"""
    ellipsis = "…"
    if _measure_mixed_width(line, font, primary_checker, emoji_font) <= max_width:
        return line
    clusters = _split_clusters(line.rstrip())
    while (
        clusters
        and _measure_mixed_width("".join(clusters) + ellipsis, font, primary_checker, emoji_font)
        > max_width
    ):
        clusters.pop()
    return ("".join(clusters) + ellipsis) if clusters else ellipsis


def _has_short_orphan(
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    max_width: float,
    primary_checker: _PrimaryFontChecker,
    emoji_font: _EmojiFont | None,
) -> bool:
    """判断多行文本末行是否为仅有 1~2 个有效字/标点的孤行。"""
    non_empty = [ln for ln in lines if ln.strip()]
    if len(non_empty) <= 1:
        return False
    last = non_empty[-1].strip()
    core_clusters = [
        cl for cl in _split_clusters(last) if cl not in _NO_LINE_START and not cl.isspace()
    ]
    if len(core_clusters) <= 2:
        return True
    return _measure_mixed_width(last, font, primary_checker, emoji_font) < min(
        max_width * 0.24, font.size * 2.6
    )


def _fit_quote_layout(
    text: str,
    font_path: Path | str,
    max_width: float,
    max_height: float,
    *,
    primary_checker: _PrimaryFontChecker,
    emoji_font: _EmojiFont | None,
    max_size: int = 54,
    min_size: int = 18,
    max_lines: int = 10,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """在字号区间内搜索能舒适容纳正文的最大字号与折行结果（兼顾避孤行）。"""
    candidates: list[tuple[ImageFont.FreeTypeFont, list[str], int]] = []
    for size in range(max_size, min_size - 1, -2):
        font = _load_font(font_path, size, variation="Medium")
        lines = _wrap_text_to_width(text, font, max_width, primary_checker, emoji_font)
        line_step = max(size + 8, int(round(size * 1.42)))
        total_h = len(lines) * line_step - (line_step - size)
        if len(lines) <= max_lines and total_h <= max_height:
            candidates.append((font, lines, line_step))
            if not _has_short_orphan(lines, font, max_width, primary_checker, emoji_font):
                if len(candidates) == 1:
                    return font, lines, line_step
                break

    if candidates:
        best_font, best_lines, best_step = candidates[0]
        if _has_short_orphan(best_lines, best_font, max_width, primary_checker, emoji_font):
            for f_c, l_c, s_c in candidates[1:]:
                if best_font.size - f_c.size <= 14 and not _has_short_orphan(
                    l_c, f_c, max_width, primary_checker, emoji_font
                ):
                    return f_c, l_c, s_c
        return best_font, best_lines, best_step

    # 最坏情况：使用最小字号并对超出行数做省略号截断
    font = _load_font(font_path, min_size, variation="Medium")
    line_step = max(min_size + 8, int(round(min_size * 1.42)))
    fit_lines = max(1, min(max_lines, int((max_height + (line_step - min_size)) // line_step)))
    lines = _wrap_text_to_width(text, font, max_width, primary_checker, emoji_font)
    if len(lines) > fit_lines:
        lines = lines[:fit_lines]
        while lines and lines[-1] == "":
            lines.pop()
        if lines:
            lines[-1] = _truncate_line(
                lines[-1], font, max_width * 0.94, primary_checker, emoji_font
            )
        else:
            lines = ["……"]
    return font, lines, line_step


def _fit_nickname_layout(
    nickname: str,
    font_path: Path | str,
    max_width: float,
    *,
    primary_checker: _PrimaryFontChecker | None = None,
    emoji_font: _EmojiFont | None = None,
    max_size: int = 27,
    min_size: int = 18,
    max_lines: int = 3,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """自适应排版群友昵称：优先 1~2 行大字号，超长自动缩号并换行完整显示。"""
    if primary_checker is None:
        primary_checker = _get_primary_checker(font_path)
    if emoji_font is None:
        emoji_font = _resolve_emoji_font(Path(font_path))
    clean_nick = (nickname or "").strip() or "匿名群友"
    full_text = f"— {clean_nick}"

    for line_budget in (2, max_lines):
        for size in range(max_size, min_size - 1, -2):
            font = _load_font(font_path, size, variation="Medium")
            lines = _wrap_text_to_width(
                full_text, font, max_width, primary_checker, emoji_font
            )
            if len(lines) <= line_budget:
                line_step = max(size + 6, int(round(size * 1.32)))
                return font, lines, line_step

    font = _load_font(font_path, min_size, variation="Medium")
    line_step = max(min_size + 6, int(round(min_size * 1.32)))
    lines = _wrap_text_to_width(
        full_text, font, max_width, primary_checker, emoji_font
    )[:max_lines]
    if lines:
        lines[-1] = _truncate_line(
            lines[-1], font, max_width * 0.94, primary_checker, emoji_font
        )
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


def _composite_emoji_shadow(
    shadow_layer: Image.Image,
    tile: Image.Image,
    dest_x: int,
    dest_y: int,
    shadow_alpha: int,
) -> None:
    """用 Emoji Alpha 通道投影到阴影图层。"""
    alpha_mask = tile.getchannel("A")
    if shadow_alpha < 255:
        alpha_mask = alpha_mask.point(lambda a: (a * shadow_alpha) // 255)
    sil = Image.new("RGBA", tile.size, (0, 0, 0, 255))
    sil.putalpha(alpha_mask)
    shadow_layer.alpha_composite(sil, dest=(dest_x, dest_y))


def _draw_mixed_centered_line(
    layer: Image.Image,
    shadow_layer: Image.Image | None,
    cx: float,
    cy: float,
    line: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    primary_checker: _PrimaryFontChecker,
    emoji_font: _EmojiFont | None,
    *,
    shadow_offset: tuple[int, int] = (0, 2),
    shadow_alpha: int = 165,
) -> None:
    """在指定中心点水平居中绘制中英与 Emoji 混排文本（附带可选阴影层）。"""
    runs = _layout_line_runs(line, font, primary_checker, emoji_font)
    if not runs:
        return
    total_w = sum(w for _, _, w in runs)
    cur_x = cx - total_w / 2.0
    pad_x = max(2, int(round(font.size * 0.14)))
    draw = ImageDraw.Draw(layer)
    sdraw = ImageDraw.Draw(shadow_layer) if shadow_layer is not None else None

    for kind, payload, run_w in runs:
        if kind == "text":
            text_seg = str(payload)
            if sdraw is not None:
                sdraw.text(
                    (cur_x + shadow_offset[0], cy + shadow_offset[1]),
                    text_seg,
                    font=font,
                    fill=(0, 0, 0, shadow_alpha),
                    anchor="lm",
                )
            draw.text((cur_x, cy), text_seg, font=font, fill=fill, anchor="lm")
        elif isinstance(payload, Image.Image):
            dest_x = int(round(cur_x + pad_x / 2.0))
            dest_y = int(round(cy - payload.height / 2.0))
            if shadow_layer is not None:
                _composite_emoji_shadow(
                    shadow_layer,
                    payload,
                    dest_x + shadow_offset[0],
                    dest_y + shadow_offset[1],
                    shadow_alpha,
                )
            layer.alpha_composite(payload, dest=(dest_x, dest_y))
        cur_x += run_w


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
    """在 RGBA 图层上绘制带柔和深色投影的纯文本。"""
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
    emoji_font_path: Path | str | None = None,
    grayscale: bool = True,
    width: int = 1200,
    height: int = 630,
    watermark: str = "",
) -> bytes:
    """渲染文字版群友语录图片，返回 PNG 字节流。"""
    width = max(640, int(width))
    height = max(360, int(height))
    font_path = Path(font_path)
    primary_checker = _get_primary_checker(font_path)
    emoji_font = _resolve_emoji_font(font_path, emoji_font_path)

    canvas = Image.new("RGBA", (width, height), (*BG_COLOR, 255))

    # 1. 左侧头像层（高度撑满的正方形）
    avatar_side = min(height, int(width * 0.56))
    avatar_layer = _prepare_avatar_layer(
        avatar_bytes=avatar_bytes,
        side=avatar_side,
        nickname=nickname,
        font_path=font_path,
        grayscale=grayscale,
        emoji_font=emoji_font,
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
        primary_checker=primary_checker,
        emoji_font=emoji_font,
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
        primary_checker=primary_checker,
        emoji_font=emoji_font,
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
    max_line_w = max(
        (
            _measure_mixed_width(line, body_font, primary_checker, emoji_font)
            for line in lines
            if line
        ),
        default=120.0,
    )
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

    # 5. 绘制语录正文（逐行水平居中，含软投影与 Emoji）
    shadow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    fg_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for idx, line in enumerate(lines):
        if not line:
            continue
        ly = block_top + idx * line_step + body_font_size / 2.0
        _draw_mixed_centered_line(
            fg_layer,
            shadow_layer,
            content_cx,
            ly,
            line,
            body_font,
            (*TEXT_COLOR, 255),
            primary_checker,
            emoji_font,
            shadow_offset=(0, 2),
            shadow_alpha=175,
        )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=2.5))
    text_layer = Image.alpha_composite(text_layer, shadow_layer)
    text_layer = Image.alpha_composite(text_layer, fg_layer)

    # 6. 绘制分割线、群友昵称（支持多行与 Emoji）与日期
    tdraw = ImageDraw.Draw(text_layer)
    div_y = int(round(body_bottom + gap_body_div))
    div_half_w = 28
    tdraw.rounded_rectangle(
        [content_cx - div_half_w, div_y, content_cx + div_half_w, div_y + divider_h],
        radius=1,
        fill=DIVIDER_COLOR,
    )

    nick_top = div_y + divider_h + gap_div_nick
    nick_shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    nick_fg = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for idx, nline in enumerate(nick_lines):
        if not nline:
            continue
        nick_cy = nick_top + idx * nick_step + nick_font_size / 2.0
        _draw_mixed_centered_line(
            nick_fg,
            nick_shadow,
            content_cx,
            nick_cy,
            nline,
            nick_font,
            (*NICK_COLOR, 255),
            primary_checker,
            emoji_font,
            shadow_offset=(0, 1),
            shadow_alpha=145,
        )
    text_layer = Image.alpha_composite(text_layer, nick_shadow)
    text_layer = Image.alpha_composite(text_layer, nick_fg)

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
        ImageDraw.Draw(text_layer).text(
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
