"""离线验证脚本：不启动 MaiBot，对本插件做结构自检。

检查项：
 1. stub SDK 下 plugin.py 可导入，组件声明完整（8 命令 + 4 工具）且名称唯一；
 2. 命令正则按 MaiBot re.search 语义的行为（命中/不命中样例）；
 3. 配置模型默认值（含 1.2.3 硬性要求的 plugin.config_version）；
 4. manifest 结构校验（字段、ID/版本正则、能力名、依赖）；
 5. 存储层：food 增删持久化、早晚安记录与统计逻辑；
 6. 渲染层：真实渲染喜报/悲报/锦旗并用 PIL 复检；
 7. 锦旗领域逻辑：分段、分列、日期写法、默认值补全与越界报错；
 8. 一言接口连通性（尽力而为，失败记 SKIP 不算失败）。

用法：python tests/verify.py
"""

from __future__ import annotations

import asyncio
import datetime
import json
import re
import sys
import tempfile
import traceback
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR / "tests"))
sys.path.insert(0, str(PLUGIN_DIR))

import stub_maibot_sdk as stub  # noqa: E402

# 注入 stub SDK（必须在导入 plugin 之前）
sys.modules["maibot_sdk"] = stub
types_mod = type(sys)("maibot_sdk.types")
for attr in ("ToolParamType", "ToolParameterInfo", "CONFIG_RELOAD_SCOPE_SELF", "HookMode", "ErrorPolicy"):
    setattr(types_mod, attr, getattr(stub, attr))
types_mod.__path__ = []
sys.modules["maibot_sdk.types"] = types_mod

import plugin  # noqa: E402

from essential_jinqi import (  # noqa: E402
    JinqiError,
    build_spec,
    chinese_date,
    format_date,
    split_thanks,
)
from essential_passive_eat import (  # noqa: E402
    FoodImageIndex,
    PassiveRateLimiter,
    PassiveResponder,
    sniff_image_ext,
)
from essential_render_card import render_report_card  # noqa: E402
from essential_render_jinqi import FontSet, render_jinqi  # noqa: E402
from essential_services import fetch_hitokoto  # noqa: E402
from essential_storage import FoodStore, GoodMorningStore, strip_bracket_placeholders  # noqa: E402

ASSETS = PLUGIN_DIR / "assets"
PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    mark = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))


def main() -> int:
    # ---- 1. 组件声明 ------------------------------------------------------
    errors = []
    try:
        inst = plugin.EssentialPlugin()
        comps = inst.get_components()
    except Exception:
        errors.append("插件实例化/组件收集失败:\n" + traceback.format_exc())
        comps = []
    check("plugin.py 可导入并实例化", not errors, "; ".join(errors))

    commands = {c["name"]: c for c in comps if c["kind"] == "command"}
    tools = {c["name"]: c for c in comps if c["kind"] == "tool"}
    hooks = [c for c in comps if c["kind"] == "hook_handler"]
    check("命令组件共 8 个", len(commands) == 8, f"实际: {sorted(commands)}")
    check("工具组件共 4 个", len(tools) == 4, f"实际: {sorted(tools)}")
    check("被动触发 Hook 存在",
          len(hooks) == 1 and hooks[0]["name"] == "passive_what_to_eat"
          and hooks[0]["hook"] == "chat.receive.after_process",
          f"实际: {[(c['name'], c['hook']) for c in hooks]}")
    names = [c["name"] for c in comps]
    check("组件名无重复", len(names) == len(set(names)))

    # ---- 2. 命令正则（re.search 语义） ------------------------------------
    cases = [
        # (命令, 消息文本, 期望命中, 期望分组)
        # 除早晚安外，命令必须带 / 前缀才生效
        ("tool_list", "/工具列表", True, None),
        ("tool_list", "发一下 /工具列表", True, None),
        ("tool_list", "工具列表", False, None),
        ("tool_list", "/工具列表吧", False, None),
        ("happy_report", "/喜报 张三考上了大学", True, {"text": "张三考上了大学"}),
        ("happy_report", "看这个 /喜报 测试", True, {"text": "测试"}),
        ("happy_report", "喜报 张三考上了大学", False, None),
        ("happy_report", "今天我们聊聊喜报的话题", False, None),
        ("happy_report", "喜报吧", False, None),
        ("happy_report", "喜报", False, None),
        ("happy_report", "/悲报 项目又延期了", False, None),
        ("sad_report", "/悲报 项目又延期了", True, {"text": "项目又延期了"}),
        ("sad_report", "悲报 项目又延期了", False, None),
        ("sad_report", "这个悲报真好看", False, None),
        ("jinqi", "/锦旗 助人为乐 情暖人心", True, {"text": "助人为乐 情暖人心"}),
        ("jinqi", "/锦旗 助人为乐 情暖人心 | 赠：麦麦 | 全体群友", True,
         {"text": "助人为乐 情暖人心 | 赠：麦麦 | 全体群友"}),
        ("jinqi", "看这个 /锦旗 赛博菩萨", True, {"text": "赛博菩萨"}),
        ("jinqi", "/锦旗", True, {"text": None}),
        ("jinqi", "锦旗 助人为乐", False, None),
        ("jinqi", "聊聊锦旗怎么做", False, None),
        ("jinqi", "/锦旗吧", False, None),
        ("jinqi", "/锦旗 助人为乐\n [图片：一张图片]", True, {"text": "助人为乐"}),
        ("answer_book", "今天能否起飞 翻看答案", True, {"question": "今天能否起飞"}),
        ("answer_book", "明天会下雨吗 翻看答案", True, {"question": "明天会下雨吗"}),
        ("answer_book", "翻看答案", True, {"question": None}),
        ("answer_book", "/翻看答案", False, None),
        ("answer_book", "翻看答案吧", False, None),
        ("answer_book", "我想翻看答案", False, None),
        ("hitokoto", "一言", True, {"extra": None}),
        ("hitokoto", "/一言", True, {"extra": None}),
        ("hitokoto", "/一言 今天能否起飞", True, {"extra": "今天能否起飞"}),
        ("hitokoto", "一言以蔽之", False, None),
        ("hitokoto", "我来说一言", False, None),
        ("what_to_eat", "/今天吃什么", True, {"action": None, "items": None}),
        ("what_to_eat", "/今天吃什么 添加 宫保鸡丁 红烧肉", True,
         {"action": "添加", "items": "宫保鸡丁 红烧肉"}),
        ("what_to_eat", "/今天吃什么 删除 宫保鸡丁", True, {"action": "删除", "items": "宫保鸡丁"}),
        ("what_to_eat", "/今天吃什么 添加", True, {"action": "添加", "items": None}),
        ("what_to_eat", "今天吃什么", False, None),
        ("what_to_eat", "今天吃什么 添加 宫保鸡丁", False, None),
        ("what_to_eat", "/今天吃什么删除红烧肉", False, None),
        ("what_to_eat", "聊聊今天吃什么好", False, None),
        # 早晚安不需要 /
        ("good_morning", "早安", True, {"kind": "早安"}),
        ("good_morning", "晚安", True, {"kind": "晚安"}),
        ("good_morning", "晚安啦~", True, {"kind": "晚安"}),
        ("good_morning", "早安呀！", True, {"kind": "早安"}),
        ("good_morning", "/晚安 喵", True, {"kind": "晚安"}),
        ("good_morning", "晚安故事", False, None),
        ("good_morning", "我来说早安", False, None),
        ("good_morning", "早安晚安都行", False, None),
        # 带图消息：占位符在换行之后，命令必须容忍该尾巴（占位符不进参数）
        ("what_to_eat", "/今天吃什么 添加 锅包肉\n [图片：这是一张测试图片]", True,
         {"action": "添加", "items": "锅包肉"}),
        ("what_to_eat", "/今天吃什么 添加 今天不许吃改为请血之意志吃\n [图片：这张图片展示了QQ资料页面]",
         True, {"action": "添加", "items": "今天不许吃改为请血之意志吃"}),
        ("what_to_eat", "/今天吃什么\n [图片：一张图片]", True,
         {"action": None, "items": None}),
        ("happy_report", "/喜报 张三考上了大学\n [图片：一张图片]", True,
         {"text": "张三考上了大学"}),
        ("hitokoto", "/一言 今天能否起飞\n [图片：一张图片]", True,
         {"extra": "今天能否起飞"}),
        ("tool_list", "/工具列表\n [图片：一张图片]", True, None),
        ("tool_list", "/工具列表\n[图片：一张图片]", True, None),
    ]
    for name, text, expected_hit, expected_groups in cases:
        pattern = commands[name]["pattern"]
        m = re.search(pattern, text)
        hit = m is not None
        if hit != expected_hit:
            check(f"正则 {name} ← {text!r}", False, f"期望命中={expected_hit}, 实际={hit}")
            continue
        if hit and expected_groups is not None:
            got = m.groupdict()
            got_norm = {k: (v.strip() if isinstance(v, str) else v) for k, v in got.items()}
            exp_norm = {k: (v.strip() if isinstance(v, str) else v) for k, v in expected_groups.items()}
            if got_norm != exp_norm:
                check(f"正则 {name} ← {text!r}", False, f"分组期望={exp_norm}, 实际={got_norm}")
                continue
        check(f"正则 {name} ← {text!r}", True)

    # ---- 3. 配置模型默认值 ------------------------------------------------
    cfg = plugin.EssentialConfig()
    check("config_version 默认值存在", cfg.plugin.config_version == "1.4.0",
          f"实际: {cfg.plugin.config_version!r}")
    check("report.font_size 默认 65", cfg.report.font_size == 65)
    check("good_morning.cooldown_minutes 默认 30", cfg.good_morning.cooldown_minutes == 30)
    check("good_morning.forward_to_mai 默认 True", cfg.good_morning.forward_to_mai is True)
    check("hitokoto.request_timeout_sec 默认 10", cfg.hitokoto.request_timeout_sec == 10)
    check("what_to_eat.enabled 默认 True", cfg.what_to_eat.enabled is True)
    check("what_to_eat.trigger_keywords 默认 [吃什么]", cfg.what_to_eat.trigger_keywords == ["吃什么"])
    check("what_to_eat.recommend_probability 默认 0.3", cfg.what_to_eat.recommend_probability == 0.3)
    check("what_to_eat.intercept_message 默认 True", cfg.what_to_eat.intercept_message is True)
    check("jinqi.enabled 默认 True", cfg.jinqi.enabled is True)
    check("jinqi.big_font_size 默认 110", cfg.jinqi.big_font_size == 110)
    check("jinqi.small_font_size 默认 42", cfg.jinqi.small_font_size == 42)
    check("jinqi.date_style 默认 chinese", cfg.jinqi.date_style == "chinese")
    check("jinqi.default_signer 默认空", cfg.jinqi.default_signer == "")

    # ---- 4. manifest 校验 -------------------------------------------------
    manifest = json.loads((PLUGIN_DIR / "_manifest.json").read_text(encoding="utf-8"))
    allowed_keys = {
        "manifest_version", "id", "version", "name", "description", "author", "license",
        "urls", "host_application", "sdk", "capabilities", "i18n", "dependencies",
        "plugin_type", "llm_providers", "display", "changelog",
    }
    check("manifest 无 schema 外字段", set(manifest) <= allowed_keys,
          f"多余字段: {set(manifest) - allowed_keys}")
    check("manifest 必填字段齐全",
          {"manifest_version", "id", "version", "name", "description", "author", "license",
           "urls", "host_application", "sdk", "capabilities", "i18n"} <= set(manifest))
    check("manifest_version == 2", manifest["manifest_version"] == 2)
    check("id 格式合法（含分隔符）",
          bool(re.fullmatch(r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)+", manifest["id"])),
          manifest["id"])
    check("version 三段式", bool(re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])))
    check("manifest.version 与 SUPPORTED_CONFIG_VERSION 同步",
          manifest["version"] == plugin.SUPPORTED_CONFIG_VERSION,
          f"{manifest['version']} vs {plugin.SUPPORTED_CONFIG_VERSION}")
    check("host_application 区间合法",
          manifest["host_application"]["min_version"] <= manifest["host_application"]["max_version"])
    known_caps = {
        "send.text", "send.image", "send.hybrid", "maisaka.context.append",
        "chat.get_stream_by_group_id", "chat.get_stream_by_user_id",
    }
    check("capabilities 全部为已知能力名", set(manifest["capabilities"]) <= known_caps,
          f"未知: {set(manifest['capabilities']) - known_caps}")
    dep_names = [d.get("name") for d in manifest.get("dependencies", [])]
    check("依赖含 aiohttp 与 Pillow",
          {"aiohttp", "pillow"} <= {n.lower() for n in dep_names},
          f"实际: {dep_names}")

    # ---- 5. 存储层 --------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        food = FoodStore(tmp / "food.json", ASSETS / "food.json")
        food.load()
        initial = len(food.items)
        check("food 初始清单已从 assets 复制加载", initial > 50, f"{initial} 项")
        food.add(["宫保鸡丁", "测试菜A", "测试菜A"])
        check("food.add 去重", food.items.count("测试菜A") == 1)
        food.remove(["不存在的菜"])
        food.save()
        food2 = FoodStore(tmp / "food.json")
        food2.load()
        check("food 持久化 roundtrip", food2.items == food.items)

        gm = GoodMorningStore(tmp / "good_morning.json")
        gm.load()
        rec = gm.user_record("stream-1", "10001")
        rec["daily"]["night_time"] = "2026-09-10 23:00:00"
        rec2 = gm.user_record("stream-1", "10002")
        rec2["daily"]["night_time"] = "2026-09-10 23:30:00"
        rec2["daily"]["morning_time"] = "2026-09-11 07:00:00"
        # 10001 只晚安未早安 → 在睡觉；10002 已早安 → 不算
        check("count_sleeping_today 统计正确", gm.count_sleeping_today("stream-1", 10) == 1,
              f"实际: {gm.count_sleeping_today('stream-1', 10)}")
        gm.save()
        gm2 = GoodMorningStore(tmp / "good_morning.json")
        gm2.load()
        check("早晚安记录 roundtrip（含 good_morning 包装层）",
              gm2.data == gm.data and "good_morning" in
              json.loads((tmp / "good_morning.json").read_text(encoding="utf-8")))

        # 原版"裸 dict 历史文件"兼容
        (tmp / "legacy.json").write_text(
            json.dumps({"stream-x": {"u1": {"daily": {"morning_time": "a", "night_time": "b"}}}}),
            encoding="utf-8")
        gm3 = GoodMorningStore(tmp / "legacy.json")
        gm3.load()
        check("兼容旧版裸 dict 文件", "stream-x" in gm3.data)

    # ---- 答案之书词条库 ----------------------------------------------------
    book = plugin.AnswerBook(PLUGIN_DIR / "assets" / "answer_book.json")
    book.load()
    check("答案之书词条库已加载（900 条且无重复）",
          len(book.answers) == 900 and len(set(book.answers)) == 900,
          f"实际: {len(book.answers)} 条 / 去重 {len(set(book.answers))} 条")
    import random as _random
    _random.seed(42)
    picks = {book.choice() for _ in range(50)}
    check("答案之书随机抽取正常", len(picks) >= 10, f"50 次抽到 {len(picks)} 种")

    # ---- 被动触发（吃什么）模块 --------------------------------------------
    limiter = PassiveRateLimiter(max_responses=2, window_seconds=60,
                                 echo_cooldown_enabled=True, echo_cooldown_seconds=15)
    forces = [limiter.check_and_record("g1")[1] for _ in range(3)]
    check("限流器：窗口内超限强制推荐", forces == [False, False, True], f"实际: {forces}")
    limiter.record_echo("g1")
    check("限流器：复读后进入冷却", limiter.is_in_echo_cooldown("g1"))
    limiter_off = PassiveRateLimiter(echo_cooldown_enabled=False)
    limiter_off.record_echo("g2")
    check("限流器：冷却开关关闭时不冷却", not limiter_off.is_in_echo_cooldown("g2"))

    responder = PassiveResponder(probability=1.0)
    check("回复器：概率 1.0 必然推荐", all(responder.should_recommend() for _ in range(20)))
    responder0 = PassiveResponder(probability=0.0)
    check("回复器：概率 0.0 必然复读", not any(responder0.should_recommend() for _ in range(20)))
    check("回复器：推荐文案包含食物名", "黄焖鸡" in responder.get_food_response("黄焖鸡"))
    check("回复器：无食物走兜底文案",
          responder.get_food_response(None) == PassiveResponder.FALLBACK_RESPONSE)
    check("回复器：复读文案固定", responder.get_echo_response() == "是啊，吃什么")

    with tempfile.TemporaryDirectory() as td_img:
        img_dir = Path(td_img)
        (img_dir / "黄焖鸡米饭.jpg").write_bytes(b"x")
        (img_dir / "黄焖鸡米饭_1.png").write_bytes(b"y")
        (img_dir / "螺蛳粉.GIF").write_bytes(b"z")
        (img_dir / "说明.txt").write_bytes(b"n")
        index = FoodImageIndex(img_dir)
        got = {Path(index.get_random_image("黄焖鸡米饭")).name for _ in range(20)}
        check("图片索引：按文件名绑定（含序号变体）",
              got == {"黄焖鸡米饭.jpg", "黄焖鸡米饭_1.png"}, f"抽到 {got}")
        check("图片索引：扩展名大小写不敏感", index.get_random_image("螺蛳粉") is not None)
        check("图片索引：无匹配返回 None", index.get_random_image("不存在的菜") is None)

        # 附图绑定：保存 / 去重 / 多图命名 / 路径净化
        s1 = index.save_image("锅包肉", b"\xff\xd8\xff\xe0" + b"A" * 200)   # 锅包肉.jpg
        s2 = index.save_image("锅包肉", b"\xff\xd8\xff\xe0" + b"A" * 200)  # 同内容 → 去重
        s3 = index.save_image("锅包肉", b"\x89PNG\r\n\x1a\n" + b"B" * 200)  # 异扩展名，不冲突
        s4 = index.save_image("锅包肉", b"\xff\xd8\xff\xe0" + b"D" * 200)   # 同扩展名第二张 → _1
        food_files = sorted(p.name for p in img_dir.iterdir() if p.name.startswith("锅包肉"))
        check("图片绑定：保存/去重/多图命名",
              (s1, s2, s3, s4) == (1, 0, 1, 1)
              and food_files == ["锅包肉.jpg", "锅包肉.png", "锅包肉_1.jpg"],
              f"saved={(s1, s2, s3, s4)} files={food_files}")
        check("图片绑定：保存后立即可用", index.get_random_image("锅包肉") is not None)
        check("图片魔数：JPEG/PNG/GIF/WEBP",
              sniff_image_ext(b"\xff\xd8\xff" + b"\x00" * 50) == ".jpg"
              and sniff_image_ext(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50) == ".png"
              and sniff_image_ext(b"GIF89a" + b"\x00" * 50) == ".gif"
              and sniff_image_ext(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 20) == ".webp")
        traversal = index.save_image("../evil", b"\xff\xd8\xff" + b"C" * 200)
        check("图片绑定：路径穿越被净化",
              traversal == 1 and (img_dir / "..evil.jpg").exists()
              and not (img_dir.parent / "evil.jpg").exists())

    food_for_passive = FoodStore(ASSETS / "food.json")
    food_for_passive.load()
    check("FoodStore.choice_or_none 正常",
          food_for_passive.choice_or_none() in food_for_passive.items)
    empty_store = FoodStore(Path(tempfile.gettempdir()) / "definitely_missing_food.json")
    check("FoodStore.choice_or_none 空清单返回 None", empty_store.choice_or_none() is None)

    # ---- 占位符清理（带图消息的 [图片：AI 描述] 尾巴） -----------------------
    dirty = "烤鸭 [图片：这张图片展示了一桌丰盛的北京烤鸭。烤鸭被切成薄片，色泽金黄诱人。]"
    cleaned = strip_bracket_placeholders(dirty).split()
    check("占位符清理：图片描述被剥离", cleaned == ["烤鸭"], f"实际: {cleaned}")
    leftovers = [n for n in strip_bracket_placeholders("烤鸭 [没写完的").split()
                 if "[" not in n and "]" not in n]
    check("占位符清理：残留括号会被名字过滤兜底", leftovers == ["烤鸭"], f"实际: {leftovers}")

    # ---- 锦旗领域逻辑 ------------------------------------------------------
    check("分列：空白恰好两段 → 两列", split_thanks("助人为乐 情暖人心") == ("助人为乐", "情暖人心"))
    check("分列：显式分隔符 → 两列",
          split_thanks("妙语连珠、群友之光") == ("妙语连珠", "群友之光")
          and split_thanks("妙语连珠/群友之光") == ("妙语连珠", "群友之光"))
    check("分列：四字保持单列", split_thanks("赛博菩萨") == ("赛博菩萨",))
    check("分列：八字节整句对半折行", split_thanks("助人为乐情暖人心") == ("助人为乐", "情暖人心"))
    check("分列：三段不被误切（去掉空白后对半折）",
          split_thanks("代码零 Bug 上线不炸服") == ("代码零Bug", "上线不炸服"))
    check("分列：六字以内不折", split_thanks("麦麦永远滴神") == ("麦麦永远滴神",))
    for bad, why in (("", "空"), ("助人为乐情暖人心恭喜发财啦再添一句", "超 16 字"), ("助人为乐情暖人心呀/好", "单列超 8 字")):
        try:
            split_thanks(bad)
            check(f"分列：{why}应报错", False, f"未报错: {bad!r}")
        except JinqiError:
            check(f"分列：{why}应报错", True)

    check("日期：中文写法", chinese_date(datetime.date(2026, 9, 27)) == "二〇二六年九月廿七",
          chinese_date(datetime.date(2026, 9, 27)))
    check("日期：中文写法边界（1/10/11/20/21/30/31）",
          [chinese_date(datetime.date(2026, 1, d)) for d in (1, 10, 11, 20, 21, 30, 31)]
          == ["二〇二六年一月初一", "二〇二六年一月初十", "二〇二六年一月十一",
              "二〇二六年一月二十", "二〇二六年一月廿一", "二〇二六年一月三十",
              "二〇二六年一月卅一"],
          str([chinese_date(datetime.date(2026, 1, d)) for d in (1, 10, 11, 20, 21, 30, 31)]))
    check("日期：十二月", chinese_date(datetime.date(2026, 12, 31)) == "二〇二六年十二月卅一")
    check("日期：numeric / none 两种写法",
          format_date(datetime.date(2026, 9, 27), "numeric") == "2026-09-27"
          and format_date(datetime.date(2026, 9, 27), "none") == "")

    today = datetime.date(2026, 9, 27)
    spec = build_spec("助人为乐 情暖人心 | 麦麦 | 全体群友", fallback_signer="路人甲", today=today)
    check("组装：三段完整解析",
          (list(spec.thanks_columns), spec.recipient, spec.signer, spec.date_text)
          == (["助人为乐", "情暖人心"], "赠：麦麦", "全体群友", "二〇二六年九月廿七"),
          str(spec))
    check("组装：赠予对象自动补「赠：」前缀且不重复补",
          build_spec("好 | 赠：麦麦", today=today).recipient == "赠：麦麦"
          and build_spec("好 | 敬赠麦麦", today=today).recipient == "敬赠麦麦")
    check("组装：落款缺省时用昵称 +「敬赠」",
          build_spec("好", fallback_signer="小明", today=today).signer == "小明 敬赠")
    check("组装：无昵称时落款留空",
          build_spec("好", today=today).signer == "")
    check("组装：显式落款优先于昵称",
          build_spec("好 | 麦麦 | 全体群友", fallback_signer="小明", today=today).signer == "全体群友")
    check("组装：赠予对象缺省时留空",
          build_spec("好 | | 全体群友", today=today).recipient == "")
    check("组装：date_style=none 不渲染日期",
          build_spec("好", date_style="none", today=today).date_text == "")
    check("组装：全角竖线也能分段",
          build_spec("好｜麦麦", today=today).recipient == "赠：麦麦")
    for bad, why in (("", "无感谢语"), ("好 | 这个赠予对象实在是太长了根本放不下", "赠予对象超长")):
        try:
            build_spec(bad, today=today)
            check(f"组装：{why}应报错", False, f"未报错: {bad!r}")
        except JinqiError:
            check(f"组装：{why}应报错", True)

    # ---- 6. 渲染层 --------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "card.jpg"
        render_report_card(ASSETS / "congrats.jpg", ASSETS / "NotoSansSC.ttf",
                           "恭喜张三同学成功上岸！！可喜可贺可喜可贺", 65, out,
                           (255, 0, 0), (255, 255, 0))
        ok = out.exists() and out.stat().st_size > 10_000
        check("喜报渲染输出", ok, f"{out.stat().st_size if out.exists() else 0} bytes")
        from PIL import Image
        with Image.open(out) as im:
            check("喜报图片可被 PIL 重新打开", im.size == (1280, 720) or im.size[0] > 0, f"size={im.size}")

        out2 = Path(td) / "uncard.jpg"
        render_report_card(ASSETS / "uncongrats.jpg", ASSETS / "NotoSansSC.ttf",
                           "悲报，今天什么都没发生", 65, out2, (0, 0, 0), (255, 255, 255))
        check("悲报渲染输出", out2.exists() and out2.stat().st_size > 10_000)

        # 锦旗：完整版 / 极简版 / 超长文案自动缩号
        from PIL import Image as _Image
        from essential_render_jinqi import BG_SIZE  # noqa: PLC0415

        with _Image.open(ASSETS / "jinqi_bg.png") as bg_im:
            check("锦旗底图尺寸与渲染常量一致", bg_im.size == BG_SIZE,
                  f"底图 {bg_im.size} vs BG_SIZE {BG_SIZE}")
        check("锦旗底图留白区是白的（说明素材底色正常）",
              _Image.open(ASSETS / "jinqi_bg.png").convert("RGB").getpixel((4, 4))[0] > 230)

        jq_cases = [
            ("完整版", build_spec("助人为乐 情暖人心 | 麦麦 | 全体群友", today=today)),
            ("极简版", build_spec("赛博菩萨", today=today)),
            ("两列长句", build_spec("代码零Bug 上线不炸服", fallback_signer="运维组", today=today)),
            ("拉丁混排", build_spec("代码零BUG 上线不炸服 | 赠：麦麦 | 测试", today=today)),
            ("数字日期", build_spec("好", date_style="numeric", today=today)),
            ("十六字满格", build_spec("恭喜发财红包拿来 身体健康万事如意", today=today)),
            ("最长组合", build_spec(
                "妙语连珠 群友之光 | 赠：麦麦小工具合集插件开发组 | 深夜潜水群全体", today=today)),
        ]
        for label, jq_spec in jq_cases:
            jq_out = Path(td) / f"jinqi_{label}.jpg"
            render_jinqi(ASSETS / "jinqi_bg.png", ASSETS / "MaShanZheng.ttf", jq_out, jq_spec,
                         fallback_font_path=ASSETS / "NotoSansSC.ttf")
            with _Image.open(jq_out) as im:
                got_size = im.size
            check(f"锦旗渲染输出（{label}）",
                  jq_out.exists() and jq_out.stat().st_size > 20_000 and got_size == BG_SIZE,
                  f"{jq_out.stat().st_size if jq_out.exists() else 0} bytes / size={got_size}")

        # 缺字回退：毛笔楷体缺生僻字时自动切到 Noto Sans SC，避免豆腐块
        fonts = FontSet(ASSETS / "MaShanZheng.ttf", ASSETS / "NotoSansSC.ttf", 60)
        check("锦旗缺字回退：常用字用主字体、生僻字切回退字体",
              fonts.pick("麦") is fonts.primary and fonts.pick("㸚") is not fonts.primary)
        check("锦旗缺字回退：无回退字体时仍返回主字体",
              FontSet(ASSETS / "MaShanZheng.ttf", None, 60).pick("㸚") is not None)

    # ---- 7. 一言连通性（尽力而为） -----------------------------------------
    try:
        data = asyncio.run(fetch_hitokoto(timeout=8))
        check("一言接口连通", bool(data.get("hitokoto")),
              f"示例: {data['hitokoto'][:20]}… —— {data.get('from')}")
    except Exception as e:  # noqa: BLE001
        print(f"[SKIP] 一言接口连通 —— 网络不可用: {e}")

    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
