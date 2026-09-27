"""把锦旗模板素材处理成运行时底图 assets/jinqi_bg.png。

素材 `tests/jinqi_bg_src.jpg` 是一张 338×450 的公开锦旗模板（红丝绒竖幅 +
银杆 + 金围边 + 金流苏，白色背景）。原图分辨率偏低，直接拿来渲染文字会显得
糊，所以这里统一放大到 2.4 倍并做一次轻量锐化，产出 811×1080 的底图。

底图只负责"锦旗本体"，文字由 essential_render_jinqi.py 在运行时叠加。

运行：python tests/make_jinqi_bg.py [源图] [输出路径]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageFilter

TESTS_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = TESTS_DIR.parent

SRC_DEFAULT = TESTS_DIR / "jinqi_bg_src.jpg"
OUT_DEFAULT = PLUGIN_DIR / "assets" / "jinqi_bg.png"

SCALE = 2.4                      # 放大倍数（源图偏小，放大后配文字才不糊）
UNSHARP_RADIUS = 2.2             # 锐化半径
UNSHARP_PERCENT = 68             # 锐化强度
UNSHARP_THRESHOLD = 3            # 锐化阈值（低对比度区域不锐化，避免噪点被放大）


def make(src: Path = SRC_DEFAULT, out: Path = OUT_DEFAULT) -> None:
    src, out = Path(src), Path(out)
    img = Image.open(src).convert("RGB")
    size = (round(img.width * SCALE), round(img.height * SCALE))
    img = img.resize(size, Image.LANCZOS)
    # 丝绒本身是软的，放大后略钝一点没关系；金围边/流苏需要一点锐度把细节拉回来
    img = img.filter(ImageFilter.UnsharpMask(
        radius=UNSHARP_RADIUS, percent=UNSHARP_PERCENT, threshold=UNSHARP_THRESHOLD
    ))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"锦旗底图已生成: {out} ({size[0]}×{size[1]}，源图 {src.name} ×{SCALE})")


if __name__ == "__main__":
    args = sys.argv[1:]
    make(
        Path(args[0]) if len(args) > 0 else SRC_DEFAULT,
        Path(args[1]) if len(args) > 1 else OUT_DEFAULT,
    )
