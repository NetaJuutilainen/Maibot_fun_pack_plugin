"""生成插件图标 assets/icon.png（512×512，圆角方，红金喜庆风）。

运行：python tests/make_icon.py
"""

import math

from PIL import Image, ImageDraw, ImageFont

S = 512
CX = S // 2
GOLD = (245, 198, 60, 255)
GOLD_SOFT = (255, 224, 130, 235)


def rounded_mask(size: int, radius: int):
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def star(draw, x, y, r, color, k_ratio=0.22):
    k = k_ratio * r
    pts = [
        (x, y - r), (x + k, y - k), (x + r, y), (x + k, y + k),
        (x, y + r), (x - k, y + k), (x - r, y), (x - k, y - k),
    ]
    draw.polygon(pts, fill=color)


def make(path: str = "assets/icon.png") -> None:
    # 背景：径向渐变（中心暖红 → 边缘深红）
    grad = Image.radial_gradient("L").resize((S, S))
    edge = Image.new("RGB", (S, S), (158, 28, 19))
    center = Image.new("RGB", (S, S), (226, 84, 55))
    img = Image.composite(edge, center, grad)

    draw = ImageDraw.Draw(img, "RGBA")

    # 太阳光芒（喜报背景的放射线元素，低透明度），圆心与主字中心一致
    ray_cy = 208
    for i in range(28):
        angle = i * (2 * math.pi / 28)
        half = math.radians(3.5)
        r0, r1 = 66, 300
        pts = [
            (CX + r0 * math.cos(angle - half), ray_cy + r0 * math.sin(angle - half)),
            (CX + r1 * math.cos(angle), ray_cy + r1 * math.sin(angle)),
            (CX + r0 * math.cos(angle + half), ray_cy + r0 * math.sin(angle + half)),
        ]
        draw.polygon(pts, fill=(255, 210, 120, 12))

    # 金色内圈描边（徽章感）
    draw.rounded_rectangle(
        [15, 15, S - 16, S - 16], radius=104, outline=GOLD, width=9
    )

    # 主字：麦（白字金边，与喜报同款描边风格），中心约 (256, 208)
    font = ImageFont.truetype("assets/NotoSansSC.ttf", 205)
    try:
        font.set_variation_by_name("Bold")
    except Exception:
        pass
    bbox = draw.textbbox((0, 0), "麦", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    ty = 208
    draw.text(
        (CX - tw / 2 - bbox[0], ty - th / 2 - bbox[1]),
        "麦",
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=9,
        stroke_fill=GOLD,
    )

    # 点缀：四角星
    star(draw, 128, 96, 30, GOLD_SOFT)
    star(draw, 390, 108, 22, (255, 224, 130, 210))
    star(draw, 402, 322, 15, (255, 224, 130, 170))

    # 底部饭碗（碗体与碗沿相连）+ 碗口热气
    bowl_top = 428
    draw.chord(
        [CX - 84, bowl_top - 42, CX + 84, bowl_top + 42],
        0, 180, fill=(255, 250, 238, 255), outline=GOLD, width=6,
    )
    draw.line(
        [CX - 92, bowl_top, CX + 92, bowl_top], fill=GOLD, width=8
    )
    for dx in (-24, 0, 24):
        draw.arc(
            [CX + dx - 9, bowl_top - 40, CX + dx + 9, bowl_top - 10],
            190, 350, fill=(255, 245, 220, 220), width=5,
        )

    # 圆角裁切输出（带透明角）
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), rounded_mask(S, 118))
    out.save(path)
    print(f"图标已生成: {path}")


if __name__ == "__main__":
    make()
