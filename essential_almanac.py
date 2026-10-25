"""今日宜忌内容规格（纯逻辑，零 PIL / 零 maibot_sdk / 零第三方依赖，可离线测试）。

玩法：每天从词条池按**日期做随机种子**抽取「宜 4 条 / 忌 3 条」与彩蛋栏 ——
同一天全群、跨群、重启后结果都一致，第二天自动换新；不落盘、零状态。

农历与干支（真实历法，非随机）：
    - 农历月日：内嵌 1900-2099 换算表（生成器 gen_lunar_table.py 以 lunardate
      为基准产出，1901-2098 逐日对拍 72319 天零差异；表格式见生成器 docstring）
    - 生肖：按农历年地支
    - 日干支 / 冲煞：干支纪日是纯儒略日算术，锚点取史载「1949-10-01 甲子日」，
      与「2000-01-01 戊午日」互证一致；冲 = 地支对冲（+6），煞方按三合局
      （寅午戌煞北 / 申子辰煞南 / 巳酉丑煞东 / 亥卯未煞西）
梗内容（按日期种子随机）：宜忌词条、时辰吉凶、幸运色、幸运物、运势星级。
词条池为作者手写的「梗黄历」风格，`[almanac].custom_yi / custom_ji` 可追加。

与 essential_render_almanac 的边界：本模块不 import 它，渲染模块只按属性
读取这里产出的 AlmanacDraw（协议约定见渲染模块），与锦旗两模块的分工一致。
"""

from __future__ import annotations

import base64
import random
import struct
from bisect import bisect_right
from datetime import date as Date
from pathlib import Path

GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"
ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
WEEKDAY = "一二三四五六日"
SHICHEN = ZHI  # 十二时辰以地支记

LUNAR_MONTH_CN = ["正月", "二月", "三月", "四月", "五月", "六月",
                  "七月", "八月", "九月", "十月", "冬月", "腊月"]
LUNAR_DAY_CN = ("初一 初二 初三 初四 初五 初六 初七 初八 初九 初十 "
                "十一 十二 十三 十四 十五 十六 十七 十八 十九 二十 "
                "廿一 廿二 廿三 廿四 廿五 廿六 廿七 廿八 廿九 三十").split()

YI_POOL = [
    "摸鱼", "提桶跑路", "装聋作哑", "已读不回", "点外卖", "睡回笼觉", "疯狂星期四",
    "薅羊毛", "摆烂", "看热闹", "吃瓜", "早睡早起", "断舍离", "退群保平安",
    "给麦麦投喂", "夸群主", "潜水", "发红包", "许愿", "立 flag", "开新坑", "清空购物车",
    "说走就走的旅行", "午睡两小时", "戒糖", "撸猫", "追更", "存钱", "背单词", "跑步",
    "早点下班", "跟老板对线", "换头像", "唱 K", "打游戏", "翻旧账", "装死", "胡说八道",
    "收闲置", "白嫖", "神游", "睡到自然醒", "多喝热水", "点奶茶", "发疯文学", "表扬自己",
    "称赞群友", "整理收藏夹", "拉黑广告", "重温老番", "抄近路", "正念发呆",
]
JI_POOL = [
    "上班", "交作业", "上课", "开会", "@全体成员", "开黑连跪", "熬夜",
    "剁手", "借钱", "相亲", "发朋友圈", "考试", "体检", "早起", "加班",
    "跟网友对线", "喝酒", "吃香菜", "戒宵夜", "表白", "跳槽", "买彩票", "挖坟",
    "查成绩", "称体重", "回前任消息", "贴秋膘", "更新系统", "重启服务器", "动数据库",
    "信网友的攻略", "拼多多砍一刀", "想太多", "emo", "抄作业", "请假", "面试",
    "立誓", "定小目标", "深夜点开购物车", "跟风冲消费", "半夜吃泡面", "翻旧聊天记录",
    "睡前刷短视频", "答应所有事", "场外支援", "透支下学期", "给差评", "删库跑路",
]

FORTUNE_DIRECTIONS = ["正东", "正南", "正西", "正北", "东南", "西南", "东北", "西北"]
LUCKY_THINGS = [
    "红色内裤", "一杯冰美式", "麦麦的祝福", "路边小猫", "旧耳机", "半价奶茶",
    "睡前消息", "Wi-Fi 满格", "工位绿植", "最后一集番剧", "食堂阿姨多打一勺", "准点的班车",
]
LUCKY_COLORS = ["红色", "金色", "青色", "绿色", "蓝色", "紫色", "白色", "黑色",
                "粉色", "橙色", "灰色", "米色"]

YI_COUNT = 4
JI_COUNT = 3

# ---------------------------------------------------------------------------
# 内嵌农历表（1900-2099；生成与校验见任务目录 gen_lunar_table.py）
# ---------------------------------------------------------------------------

_LUNAR_TABLE_B64 = (
    "AB4BgAvSCAFiB1IAAWMOpQABfwsqBQFiBksAAWMKmwABgBqmBAFiBWoAAWMLWQABgAuqAgFiB1IA"
    "AYANpQYBYgslAAFiCksAAYAaSwUBYgKtAAFjBWsAAYAFtQIBYw2pAAGAHpIHAWIOkgABYg0lAAGA"
    "DS0FAWIKVgABYgK2AAGBGtUEAWIG1AABYw6pAAGAD0oCAWIOkgABfwamBgFiBSsAAWMKVwABgAl2"
    "BQFjC1oAAWIG1AABgBdhAwFiB0kAAYAbEwcBYgqTAAFiBSsAAYAVGwYBYwqtAAFiBWoAAYEdpQQB"
    "YgukAAFiC0kAAYANSwIBYgqVAAGACq0HAWIFNgABYwqtAAGAGsoFAWIFsgABYwulAAGAHqIDAWIN"
    "SgABfwWVCAFjCpcAAWIFVgABgAV1BgFjCtUAAWIG0gABgAdVBAFjDqUAAWEGSgABgAZPAwFjCpsA"
    "AYAK2gcBYgVqAAFjC2kAAYALsgUBYgtSAAFiCyUAAYALKwQBYgpLAAGACqsIAWICrQABYwWtAAGA"
    "FakGAWMNqQABYg2SAAGADpUEAWINJQABgA5NCgFiClYAAWICtgABgAL1BgFjBtUAAWMOqQABgA9S"
    "BQFiDpIAAWINJgABfwUuAwFjClcAAYAK1ggBYgNaAAFjBtUAAYALaQUBYgdJAAFiBpMAAYAKmwQB"
    "YgUrAAFjClsAAYAKrgIBYgVqAAGBDdUHAWILpAABYgtJAAGADVMFAWIKlQABYgUtAAGABV0EAWMK"
    "tQABgAuqCQFiBdIAAWMNpQABgB6KBgFiDUoAAWIMlQABgAqeBAFiBVYAAWMKtQABgAraAgFiBtIA"
    "AYAHZQYBYgclAAFiBksAAYAGVwUBYwyrAAFiBVoAAYAFbgMBYwtpAAGAD1ILAWILUgABYgslAAGA"
    "HQsGAWIKSwABYgSrAAGAArsFAWMFrQABYwtqAAGADaoCAWINkgABgA6lBwFiDSUAAWIKVQABgBpN"
    "BQFiBLYAAWMFtQABgBbSAwFjDskAAYAPkggBYg6SAAFiDSYAAX8VFgYBYwpXAAFiBVYAAYATZQQB"
    "YwdVAAFiB0kAAYAHSwMBYgaTAAGACqsHAWIFKwABYwpbAAGACroFAWIFagABYwtlAAGAC6oEAWIL"
    "SgABgA2VCAFiCpUAAWIFLQABgAVtBgFjCrUAAWIFqgABgAXVBAFjDaUAAWINSgABgA5NAwFiDJYA"
    "AYAMzgcBYgVWAAFjCrUAAYAa0gUBYgbSAAFjDqUAAX8HKgQBYgaLAAGABpcIAWIEqwABYwVbAAGA"
    "FVYGAWMLagABYgdSAAGAC5UEAWILRQABYgqLAA=="
)
_LUNAR_YEAR_LO = 1900
_LUNAR_JIAZI_ANCHOR = Date(1949, 10, 1).toordinal()  # 史载甲子日
_SHA_BY_MOD4 = ["南", "东", "北", "西"]  # 子→南 丑→东 寅→北 卯→西（三合局）

_lunar_anchors: list[int] | None = None
_lunar_rows: list[tuple[int, int, int]] | None = None


def _lunar_init() -> None:
    global _lunar_anchors, _lunar_rows
    if _lunar_rows is not None:
        return
    blob = base64.b64decode(_LUNAR_TABLE_B64)
    base_off = struct.unpack(">H", blob[:2])[0]
    rows = [
        struct.unpack(">HHB", blob[2 + i * 5:2 + (i + 1) * 5])
        for i in range((len(blob) - 2) // 5)
    ]
    anchors = [Date(_LUNAR_YEAR_LO, 1, 1).toordinal() + base_off]
    for gap, _bits, _leap in rows:
        anchors.append(anchors[-1] + gap)
    _lunar_anchors, _lunar_rows = anchors, rows


def lunar_from_solar(day: Date) -> tuple[int, int, int, bool]:
    """公历 → (农历年, 月, 日, 是否闰月)。1901-2098 已逐日对拍零差异。"""
    _lunar_init()
    assert _lunar_anchors is not None and _lunar_rows is not None
    o = day.toordinal()
    yi = max(0, min(bisect_right(_lunar_anchors, o) - 1, len(_lunar_rows) - 1))
    year = _LUNAR_YEAR_LO + yi
    anchor, bits, leap = _lunar_anchors[yi], _lunar_rows[yi][1], _lunar_rows[yi][2]
    lengths: list[tuple[int, bool, int]] = [
        (m, False, 30 if bits & (1 << (m - 1)) else 29) for m in range(1, 13)
    ]
    if leap:
        lengths.insert(leap, (leap, True, 30 if bits & (1 << 12) else 29))
    days = o - anchor
    for m, is_leap, ln in lengths:
        if days < ln:
            return year, m, days + 1, is_leap
        days -= ln
    raise ValueError(f"农历解码越界: {day}")


def lunar_text(day: Date) -> str:
    """农历月日中文名，如「九月十六」「闰六月初三」。"""
    year, month, mday, is_leap = lunar_from_solar(day)
    leap_prefix = "闰" if is_leap else ""
    return f"{leap_prefix}{LUNAR_MONTH_CN[month - 1]}{LUNAR_DAY_CN[mday - 1]}"


def day_ganzhi(day: Date) -> str:
    """干支纪日（纯儒略日算术，锚点 1949-10-01 甲子日）。"""
    idx = (day.toordinal() - _LUNAR_JIAZI_ANCHOR) % 60
    return f"{GAN[idx % 10]}{ZHI[idx % 12]}"


def chong_sha(day: Date) -> tuple[str, str]:
    """今日冲煞：冲 = 日支对冲（+6）生肖；煞方按三合局。"""
    branch = (day.toordinal() - _LUNAR_JIAZI_ANCHOR) % 12
    chong = ZODIAC[(branch + 6) % 12]
    return chong, _SHA_BY_MOD4[branch % 4]


# ---------------------------------------------------------------------------
# 当日内容抽取
# ---------------------------------------------------------------------------

class AlmanacDraw:
    """一天份的宜忌内容（渲染模块按属性读取，不感知抽取逻辑）。"""

    def __init__(
        self,
        day: Date,
        yi: list[str],
        ji: list[str],
        direction: str,
        lucky_number: int,
        lucky_thing: str,
        stars: int,
        lucky_color: str,
        shichen: list[tuple[str, str]],
    ) -> None:
        self.day = day
        self.yi = yi
        self.ji = ji
        self.direction = direction
        self.lucky_number = lucky_number
        self.lucky_thing = lucky_thing
        self.stars = stars
        self.lucky_color = lucky_color
        self.shichen = shichen

    @property
    def ganzhi_year(self) -> str:
        return f"{GAN[(self.day.year - 4) % 10]}{ZHI[(self.day.year - 4) % 12]}年"

    @property
    def weekday_cn(self) -> str:
        return f"星期{WEEKDAY[self.day.weekday()]}"

    @property
    def lunar_text(self) -> str:
        return lunar_text(self.day)

    @property
    def zodiac(self) -> str:
        """生肖按农历年地支。"""
        year, _m, _d, _leap = lunar_from_solar(self.day)
        return ZODIAC[(year - 4) % 12]

    @property
    def day_ganzhi_cn(self) -> str:
        return day_ganzhi(self.day)

    @property
    def chong(self) -> str:
        return chong_sha(self.day)[0]

    @property
    def sha(self) -> str:
        return chong_sha(self.day)[1]


def build_draw(
    day: Date,
    custom_yi: list[str] | None = None,
    custom_ji: list[str] | None = None,
) -> AlmanacDraw:
    """按日期种子抽取当天宜忌与彩蛋；自定义词条并入池中（去重、过滤空值）。"""
    yi_pool = list(dict.fromkeys([*YI_POOL, *[s.strip() for s in (custom_yi or []) if s.strip()]]))
    ji_pool = list(dict.fromkeys([*JI_POOL, *[s.strip() for s in (custom_ji or []) if s.strip()]]))
    o = day.toordinal()
    rng = random.Random(o)
    shichen_rng = random.Random(o ^ 0x5A5A)
    shichen = [
        (ZHI[i], shichen_rng.choices(("吉", "中", "凶"), weights=(5, 4, 3))[0])
        for i in range(12)
    ]
    return AlmanacDraw(
        day=day,
        yi=rng.sample(yi_pool, min(YI_COUNT, len(yi_pool))),
        ji=rng.sample(ji_pool, min(JI_COUNT, len(ji_pool))),
        direction=rng.choice(FORTUNE_DIRECTIONS),
        lucky_number=rng.randint(1, 9),
        lucky_thing=rng.choice(LUCKY_THINGS),
        stars=rng.randint(1, 5),
        lucky_color=rng.choice(LUCKY_COLORS),
        shichen=shichen,
    )


def to_text(draw: AlmanacDraw) -> str:
    """文字版宜忌（LLM 工具返回值 / 图片发送失败时的降级文案）。"""
    stars = f"{'★' * draw.stars}{'☆' * (5 - draw.stars)}"
    shichen_line = " ".join(f"{name}{f}" for name, f in draw.shichen)
    return (
        f"【今日宜忌】{draw.day.year}年{draw.day.month}月{draw.day.day}日 "
        f"{draw.weekday_cn}\n"
        f"农历{draw.ganzhi_year}（{draw.zodiac}）{draw.lunar_text} · "
        f"{draw.day_ganzhi_cn}日 冲{draw.chong} 煞{draw.sha}\n"
        f"宜：{'、'.join(draw.yi)}\n"
        f"忌：{'、'.join(draw.ji)}\n"
        f"时辰吉凶：{shichen_line}\n"
        f"吉利方位：{draw.direction} · 幸运数字：{draw.lucky_number} · "
        f"幸运色：{draw.lucky_color} · 运势：{stars}\n"
        f"幸运物：{draw.lucky_thing}"
    )


def output_path(runtime_dir: Path, day: Date) -> Path:
    """渲染结果临时落盘位置（发完即删，防堆积）。"""
    return Path(runtime_dir) / f"almanac_{day.isoformat()}.png"
