"""锦旗样张预览：批量渲染几种典型入参，产物落在 tests/out/（已 gitignore）。

运行：python tests/preview_jinqi.py
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))

from essential_jinqi import JinqiError, build_spec  # noqa: E402
from essential_render_jinqi import render_jinqi  # noqa: E402

ASSETS = PLUGIN_DIR / "assets"
OUT = PLUGIN_DIR / "tests" / "out"

CASES = [
    ("01_简版", "助人为乐 情暖人心", "全体群友", datetime.date(2026, 9, 27)),
    ("02_完整版", "妙语连珠 群友之光 | 麦麦 | 深夜潜水群全体", "路人甲", datetime.date(2026, 9, 27)),
    ("03_不分列自动折行", "助人为乐情暖人心", "被治愈的群友", datetime.date(2026, 10, 1)),
    ("04_单列四字", "赛博菩萨", "摸鱼协会", datetime.date(2026, 9, 27)),
    ("05_长赠予对象", "有求必应 有问必答 | 赠：麦麦小工具合集插件开发组 | 全体群友", "小明", datetime.date(2026, 12, 31)),
    ("06_无赠予对象无落款", "永远滴神", "", datetime.date(2026, 9, 27)),
    ("07_阿拉伯数字日期", "代码零 Bug 上线不炸服", "运维组", datetime.date(2026, 9, 27)),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, payload, signer, today in CASES:
        date_style = "numeric" if "阿拉伯" in name else "chinese"
        try:
            spec = build_spec(payload, fallback_signer=signer, date_style=date_style, today=today)
        except JinqiError as e:
            print(f"[SKIP] {name}: {e}")
            continue
        path = OUT / f"{name}.jpg"
        render_jinqi(
            ASSETS / "jinqi_bg.png",
            ASSETS / "MaShanZheng.ttf",
            path,
            spec,
            fallback_font_path=ASSETS / "NotoSansSC.ttf",
        )
        print(f"[OK] {name}: 列={list(spec.thanks_columns)} 赠={spec.recipient!r} "
              f"落款={spec.signer!r} 日期={spec.date_text!r} → {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
