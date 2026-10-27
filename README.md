<div align="center">
  <img src="https://raw.githubusercontent.com/NetaJuutilainen/Maibot_fun_pack_plugin/main/assets/icon.png" width="128" alt="麦麦小工具合集图标"/>
  <h1>麦麦小工具合集</h1>
  <p><b>麦爹的娱乐功能合集</b> —— 喜报 / 悲报 · 锦旗 · 一言 · 答案之书 · 今天吃什么 · 早晚安 · 今日宜忌 · 群友语录</p>
</div>

MaiBot（麦麦）娱乐功能插件合集。**部分功能移植自 AstrBot 插件
[astrbot_plugin_essential](https://github.com/Soulter/astrbot_plugin_essential)（Soulter / FateTrial）**，
全部代码均针对 MaiBot 插件体系重新设计实现。

功能：**喜报 / 悲报图片生成、锦旗图片生成、一言（不计入消息）、答案之书（翻看答案）、今天吃什么（命令 + 被动触发）、群早晚安作息记录、今日宜忌（每日黄历）、群友语录（投稿 + 随机回放）、指令菜单**，
并把这些能力同时注册为麦麦可自主调用的 LLM 工具。本插件以 **MIT** 协议开源，将持续更新。

## 效果预览

| 喜报 | 悲报 |
|:---:|:---:|
| ![喜报示例](https://raw.githubusercontent.com/NetaJuutilainen/Maibot_fun_pack_plugin/main/docs/images/congrats.jpg) | ![悲报示例](https://raw.githubusercontent.com/NetaJuutilainen/Maibot_fun_pack_plugin/main/docs/images/uncongrats.jpg) |
| `/喜报 麦麦小工具合集 v1.4.0 正式上线，新增锦旗图片生成！` | `/悲报 群主跑路，摸鱼大业无人主持` |

**锦旗** —— 竖排右起：右侧赠予对象 → 中间感谢语（自动分列）→ 左侧落款与日期

```
/锦旗 助人为乐 情暖人心 | 赠：麦麦 | 全体群友
```

![锦旗示例](https://raw.githubusercontent.com/NetaJuutilainen/Maibot_fun_pack_plugin/main/docs/images/jinqi.jpg)

**今日宜忌** —— 每日黄历：宜/忌清单、十二时辰吉凶、幸运签，附**真实的农历与冲煞**；
同一天全群同结果，第二天自动换新，运势满星还会盖一枚「百无禁忌」章

![今日宜忌示例](https://raw.githubusercontent.com/NetaJuutilainen/Maibot_fun_pack_plugin/main/docs/images/almanac.jpg)

<sub>以上样张均由插件自身渲染生成，未做手工修图。</sub>

## 功能与命令

> **除 `一言` 和 `早安`/`晚安` 外，其余命令必须以 `/` 开头才生效**（直接发"喜报 ..."不会触发）。

| 命令 | 说明 | 麦麦是否接话 |
|---|---|---|
| `/工具列表` | 显示本插件全部指令（菜单） | 否 |
| `/喜报 <内容>` | 把内容渲染成喜报图片（红字黄边）发送 | 否 |
| `/悲报 <内容>` | 把内容渲染成悲报图片（黑字白边）发送 | 否 |
| `/锦旗 <感谢语> \| <赠予对象> \| <落款对象>` | 生成传统红底金字**锦旗**图片，后两段可省，详见下节 | 否 |
| `一言 [文字]`（`/` 可省） | 发一条随机一言（数据源 v1.hitokoto.cn）。**命令与回复不计入消息**：不入库、不同步进麦麦上下文，麦麦也不会接话 | 否 |
| `<问题> 翻看答案` | **答案之书**：从本地词条库（900 条）随机抽一条答案，**引用回复**你的问题。例如：`今天能否起飞 翻看答案`。另可直接发 `翻看答案` 查看用法 | 否 |
| `/今天吃什么` | **立即推荐**今天吃什么（有绑定图则图文发送） | 否 |
| `/今天吃什么 添加 食物1 食物2 ...` | 向清单添加食物；**可随消息附带图片**，添加单个食物时自动绑定图片（食物已存在则只加图） | 否 |
| `/今天吃什么 删除 食物1 食物2 ...` | 从清单删除食物 | 否 |
| 聊天中提到“吃什么” | **被动触发**（非命令）：按概率（默认 30%）推荐美食或复读“是啊，吃什么”；60 秒内被动响应超 3 次强制推荐、复读后 15 秒冷却（防多 Bot 循环）；回复后默认拦截该消息 | 默认拦截 |
| 早安 / `晚安`（支持"晚安啦~"等常见后缀，`/` 可省） | 记录作息并回复统计（睡了多久 / 本群今天第 N 个睡觉的）；**之后放行消息，麦麦自行决定是否再回复** | 是 |
| `今日宜忌`（`/` 可省，别名 `今日黄历`） | 发一张**黄历风图片**：宜 4 条 / 忌 3 条 + 十二时辰吉凶格 + 吉利方位、幸运数字、幸运色、幸运物、运势星级（满运盖「百无禁忌」章）；附**真实农历**（月日/干支年/生肖/日干支/冲煞）。**宜忌与梗内容同一天全群同结果**（日期做种子），第二天自动换新 | 否 |
| `/投稿语录` | **群友语录投稿**：回复一张含图片的消息，把图片收进本群语录库（按图片内容哈希去重，每群上限默认 500 条） | 否 |
| `/群友语录`（`/uu语录`、`/群u语录` 亦可） | 随机发一张本群投稿的语录图片（数据按群隔离） | 否 |

## 锦旗

`/锦旗` 生成一面传统锦旗：红丝绒竖幅、金杆流苏、毛笔楷体金字，**竖排右起**排版——最右是赠予对象，中间是感谢语（一或两列），左侧是落款与日期。

```
/锦旗 助人为乐 情暖人心                        ← 最简：只有感谢语（落款默认用你的昵称）
/锦旗 助人为乐 情暖人心 | 赠：麦麦              ← 加赠予对象
/锦旗 助人为乐 情暖人心 | 赠：麦麦 | 全体群友    ← 完整三段
```

规则：

- **三段用 `|`（或全角 `｜`）分隔**，后两段可省略。
- **感谢语**必填，最多 16 字。想分成两列，就在中间空一格或用 `/`、`、` 隔开（如 `助人为乐 情暖人心`）；
  不分列而超过 6 字时，会自动对半折成两列。**字号自适应**：字少则放大填满版面，字多则自动缩号。
- **赠予对象**省略时不渲染该列；写了但没带敬语前缀（赠/敬赠/谢/感谢/授予/奖励…）会自动补 `赠：`。
- **落款**省略时用发送者昵称 +「敬赠」；也可在配置里设 `default_signer` 固定落款。
- **日期**默认中文写法（`二〇二六年九月廿七`），可在配置里改成 `2026-09-27` 或关闭。
- **拉丁字母与数字逐字占一格**（`代码零BUG` 就是 6 格），与中文竖排节奏一致；列变长时字号自动缩。
- 生僻字自动回退到 Noto Sans SC，不会出现豆腐块。

## 被动触发与食物图片

“今天吃什么”的命令和被动触发共用同一份食物清单、推荐文案与图片：

- **被动触发**：聊天消息包含配置的关键词（默认“吃什么”）时，按概率（默认 30%）推荐美食或复读“是啊，吃什么”。
- **防循环限流**：同一会话 60 秒内被动响应超过 3 次后强制推荐（不再复读）；复读后 15 秒冷却，冷却期内触发也强制推荐——避免多个机器人互相复读刷屏。
- **拦截说明**：默认回复后拦截该消息（该消息不入库、麦麦不再对其回复），与原插件行为一致；希望麦麦也参与接话的话，把 `[what_to_eat]` 的 `intercept_message` 改为 `false`。
- **食物图片**：把图片放进 `data/plugins/maibot.fun-pack/food_images/`，文件名包含食物名即自动绑定，如 `黄焖鸡米饭.jpg`、`黄焖鸡米饭_1.png`、`螺蛳粉-2.png`；推荐到该食物时随机附带一张。目录每 2 分钟自动重扫，不放图则纯文字推荐。
- **添加时附图**：发送 `/今天吃什么 添加 黄焖鸡米饭` 并随消息附带图片（可多张），图片会自动绑定到该食物（按图片魔数识别格式，同一张图不会重复保存）；食物已在清单中则只加图；一次添加多个食物时不绑定图片。

说明：

- 早晚安默认 30 分钟冷却（同一用户），可在配置中调整；冷却数据存内存，重启即清零。
- 早晚安记录、食物清单持久化在 `data/plugins/<插件ID>/` 下（`good_morning.json`、`food.json`），
  首次加载自动从插件自带清单初始化食物列表。原版插件存在重启丢早晚安数据的问题，本移植已修复。
- 麦麦接话的实现方式：命令返回 `intercept=False` + 通过 `maisaka.context.append` 把统计信息写入会话上下文，
  因此麦麦知道"刚记录了什么"，回复不会与统计内容冲突；可在配置中关闭（`good_morning.forward_to_mai`）。

## LLM 工具（麦麦自主调用）

以下工具注册在 deferred 池（默认不常驻），麦麦通过 `tool_search` 按需发现，仅在用户明确要求时调用：

| 工具 | 作用 |
|---|---|
| `get_hitokoto` | 取一条一言供麦麦组织进回复 |
| `random_food` | 从食物清单随机推荐"今天吃什么" |
| `report_card` | 生成并发送喜报/悲报图片（参数 `text`、`mood=happy/sad`） |
| `jinqi_banner` | 生成并发送锦旗图片（参数 `thanks`、`recipient`、`signer`） |
| `get_daily_almanac` | 取今日宜忌文字版（同一天结果固定；图片只在命令里发） |
| `random_quote` | 从本群语录库随机抽一张投稿图片发送（仅群聊） |

## 安装

1. 将本插件目录放入 MaiBot 的 `plugins/` 目录（目录名可自定义，建议与仓库名一致；
   OneKey 部署为 `<数据>\modules\MaiBot\plugins\`）。
2. 在 WebUI（http://127.0.0.1:8001）插件管理中加载插件（更新代码后点重载即可，无需重启）。
   依赖 `aiohttp`、`Pillow` 由插件系统按 manifest 声明自动安装。
3. 日志出现"麦麦小工具合集已加载"即可测试。

## 配置

运行时配置文件 `config.toml` 由 Runner 自动生成（勿提交），支持热重载。

**功能开关** —— 关掉后命令不再响应，对应的 LLM 工具会返回「已关闭」提示；
插件总开关 `[plugin].enabled` 关闭时全部失效：

| 配置节 | 字段 | 默认 | 控制范围 |
|---|---|---|---|
| `[report]` | `enabled` | true | `/喜报`、`/悲报` 命令 + 喜报/悲报工具 |
| `[good_morning]` | `enabled` | true | 早安 / 晚安 作息记录 |
| `[hitokoto]` | `enabled` | true | 一言 命令 + 一言工具 |
| `[what_to_eat]` | `enabled` | true | `/今天吃什么` 命令 + 推荐食物工具 |
| `[what_to_eat]` | `passive_enabled` | true | **仅**被动触发（聊天含关键词时概率推荐 / 复读） |
| `[jinqi]` | `enabled` | true | `/锦旗` 命令 + 锦旗工具 |
| `[answer_book]` | `enabled` | true | `<问题> 翻看答案` |
| `[almanac]` | `enabled` | true | `今日宜忌` 命令 + 宜忌工具 |
| `[quotes]` | `enabled` | true | `/投稿语录`、`/群友语录` 命令 + 语录工具 |

> 开关只做**入口拦截**，不会注销命令与工具：命令被静默吞掉，
> 工具返回一条「功能当前已关闭」给麦麦（它据此不再反复调用）。
> `/工具列表` 的菜单会随开关变化，已关闭的功能不再展示。

其余可调项：

| 配置节 | 字段 | 默认 | 说明 |
|---|---|---|---|
| `[report]` | `font_size` | 65 | 喜报/悲报字体大小（20~200） |
| `[jinqi]` | `big_font_size` | 110 | 感谢语字号上限（列太长自动缩小，列短按此放大） |
| `[jinqi]` | `small_font_size` | 42 | 赠予对象 / 落款字号 |
| `[jinqi]` | `date_style` | chinese | 日期写法：`chinese` / `numeric` / `none` |
| `[jinqi]` | `default_signer` | "" | 落款默认值，留空则用发送者昵称 +「敬赠」 |
| `[good_morning]` | `cooldown_minutes` | 30 | 同一用户两次早晚安的最小间隔（0 不限制） |
| `[good_morning]` | `forward_to_mai` | true | 记录后把统计信息交给麦麦供其发挥 |
| `[hitokoto]` | `request_timeout_sec` | 10 | 一言 API 请求超时（秒） |
| `[what_to_eat]` | `trigger_keywords` | ["吃什么"] | 被动触发关键词列表 |
| `[what_to_eat]` | `recommend_probability` | 0.3 | 推荐食物的概率（其余复读） |
| `[what_to_eat]` | `intercept_message` | true | 被动回复后是否拦截该消息 |
| `[what_to_eat]` | `rate_limit_enabled` / `rate_limit_max` / `rate_limit_window_seconds` | true / 3 / 60 | 频率限制（防多 Bot 循环） |
| `[what_to_eat]` | `echo_cooldown_enabled` / `echo_cooldown_seconds` | true / 15 | 复读冷却 |
| `[almanac]` | `custom_yi` / `custom_ji` | [] | 追加自定义宜/忌词条（与内置词条一起参与每日抽取） |
| `[quotes]` | `max_quotes_per_group` | 500 | 每群语录上限，超出自动清理最旧（含图片文件） |
| `[quotes]` | `migrate_legacy` | true | 首次加载时自动迁移 uumessage 旧语录数据（只读旧库，不删原数据） |

## 能力声明（capabilities）

`send.text`、`send.image`、`send.hybrid`、`maisaka.context.append`、`chat.get_stream_by_group_id`、`chat.get_stream_by_user_id`、`message.get_by_id`（/投稿语录 取被回复消息）。修改 manifest 中的能力声明后必须完整重启 MaiBot。

## 代码结构

同目录平铺的模块**互不 import**，只通过函数参数/属性传数据 —— 宿主 Runner 以文件路径逐个加载
同目录模块，兄弟模块之间无法用普通 `import` 互相引用，保持"只传数据"的边界对双方都更省事。

| 文件 | 职责 |
|---|---|
| `plugin.py` | 组件装配：命令 / LLM 工具 / Hook / 配置模型，以及发送逻辑 |
| `essential_services.py` | 外部 API 客户端（一言） |
| `essential_storage.py` | `data/plugins/<插件ID>/` 下的 JSON 持久化（食物清单、早晚安） |
| `essential_render_card.py` | 喜报 / 悲报渲染（PIL） |
| `essential_jinqi.py` | 锦旗**内容规格**：参数分段、感谢语分列、日期写法、默认值补全（纯逻辑，零 PIL 依赖） |
| `essential_render_jinqi.py` | 锦旗**渲染**：竖排版式、字号自适应、缺字回退（PIL） |
| `essential_passive_eat.py` | "今天吃什么"被动触发、复读与防循环限流 |
| `essential_almanac.py` | 今日宜忌**内容规格**：按日期种子抽取宜忌与幸运签（纯逻辑，零 PIL 依赖） |
| `essential_render_almanac.py` | 今日宜忌**渲染**：黄历版式、方形朱印、缺字回退（PIL） |
| `essential_quotes.py` | 群友语录存储（每群 JSON 索引 + 图片文件）与 uumessage 旧数据迁移 |

加新功能时的惯例：**能脱离 `maibot_sdk` 的逻辑就单独成模块**，`plugin.py` 只负责装配与发送。
这样领域逻辑能脱离宿主单独跑，改版式 / 改文案时不必启动整个机器人。

## 持续更新

本插件会持续更新：后续计划加入更多娱乐功能，并持续优化现有体验。
欢迎通过 Issue 反馈想玩的功能、报告问题，PR 也欢迎。

### 版本记录

完整更新日志见 [CHANGELOG.md](CHANGELOG.md)。

| 版本 | 日期 | 更新内容 |
|---|---|---|
| **1.6.4** | 2026-10-27 | **安全加固**（市场审核意见）：群友语录的 `group_id` 增加白名单校验与路径 containment 检查，索引 / 图片写入 / 随机读取 / 清理 / 旧数据迁移全部收口；**修复** `/群友语录` 命令因与 LLM 工具同名 `random_quote` 被宿主注册表覆盖而失效（命令组件改名 `random_group_quote`，命令文本与工具名不变） |
| **1.6.3** | 2026-10-26 | 修复徽章 emoji 居中不彻底：墨迹探测图逐枚重置，顶部锦旗徽章真正居中 |
| **1.6.2** | 2026-10-26 | 修复插件图标顶部「锦旗」徽章的 emoji 未对齐：按实际墨迹包围盒居中，8 枚徽章全部重排 |
| **1.6.1** | 2026-10-26 | 插件图标更新：功能徽章从 4 枚扩到 8 枚（新增锦旗 🎖️、今日宜忌 📜、群友语录 📸、一言 💬）；README 效果预览新增「今日宜忌」样张 |
| **1.6.0** | 2026-10-26 | 新增**今日宜忌**（每日黄历图片，日期种子全群同结果，满运盖「百无禁忌」章）与**群友语录**（/投稿语录 + /群友语录，参考 pan-ice plugins-uumessage 并支持旧数据自动迁移）；新增 `[almanac]` / `[quotes]` 配置节与 `get_daily_almanac` / `random_quote` 工具；新增 `message.get_by_id` 能力声明（需完整重启） |
| **1.5.0** | 2026-09-28 | 六个功能各自独立开关（`[report]` / `[good_morning]` / `[hitokoto]` / `[what_to_eat]` / `[jinqi]` / `[answer_book]`）；被动触发拆出 `passive_enabled` 独立开关；`/工具列表` 菜单随开关动态拼装 |
| **1.4.0** | 2026-09-27 | 新增**锦旗图片生成**：`/锦旗` 命令 + `jinqi_banner` 工具，毛笔楷书竖排、感谢语自动分列、字号自适应；新增 `[jinqi]` 配置节 |
| **1.3.2** | 2026-09-19 | 插件图标定稿（麦麦吉祥物红金版，四个功能 emoji 徽章）；插件更名为**麦麦小工具合集** |
| **1.3.1** | 2026-09-12 | 修复：命令正则容忍换行后的 `[图片：AI 描述]` 占位符尾巴，带图消息不再漏匹配 |
| **1.3.0** | 2026-09-12 | 附图绑定改为按图片哈希直接定位宿主图片库文件，绕开数据库会话旧快照 |
| **1.2.2** | 2026-09-12 | 修复：附图绑定 `get_by_id` 查询为空时短重试 |
| **1.2.1** | 2026-09-12 | 修复：统一剥离 `[图片：AI 描述]` 占位符 |
| **1.2.0** | 2026-09-12 | `/今天吃什么 添加` 支持随消息附图自动绑定 |
| **1.1.1** | 2026-09-12 | 修复：被动触发自动建 `food_images` 目录；`send.hybrid` 失败降级 |
| **1.1.0** | 2026-09-12 | 今天吃什么合并**被动触发**（概率推荐 / 复读 / 防循环限流）+ 食物图片自动配图 |
| **1.0.1** | 2026-09-12 | 同目录模块改 `importlib` 显式加载；喜报 / 悲报字体换 Noto Sans SC |
| **1.0.0** | 2026-09-12 | 首个公开版本：喜报 / 悲报、一言、答案之书、今天吃什么、群早晚安、指令菜单 |

## Credits

- 部分功能（喜报/悲报、一言、今天吃什么、早晚安）移植自
  [astrbot_plugin_essential](https://github.com/Soulter/astrbot_plugin_essential)（Soulter / FateTrial），MIT License
- 今天吃什么的被动触发/复读/限流设计移植自
  [astrbot_plugin_what_to_eat](https://github.com/Sisyphbaous-DT-Project/astrbot_plugin_what_to_eat)（C₂₂H₂₅NO₆），MIT License
- 群友语录玩法与投稿/随机回放设计参考自
  [plugins-uumessage](https://github.com/pan-ice/plugins-uumessage)（pan-ice），MIT License
  （v1.6.0 起合并入本插件重写实现，并支持从其旧库自动迁移数据）
- 一言数据源：[v1.hitokoto.cn](https://v1.hitokoto.cn/)
- 早晚安玩法灵感：[nonebot_plugin_morning](https://github.com/MinatoAquaCrews/nonebot_plugin_morning)
- 喜报/悲报字体：[Noto Sans SC](https://fonts.google.com/noto/specimen/Noto+Sans+SC)（Google，SIL Open Font License 1.1，
  许可文本见 `assets/OFL.txt`，允许随本项目再分发）
- 锦旗字体：[Ma Shan Zheng 马善政毛笔楷书](https://fonts.google.com/specimen/Ma+Shan+Zheng)（SIL Open Font License 1.1，
  许可文本见 `assets/OFL-MaShanZheng.txt`，允许随本项目再分发）
- 锦旗玩法参考：[锦旗制作](http://www.ssbbww.com/b/h5.aspx)
