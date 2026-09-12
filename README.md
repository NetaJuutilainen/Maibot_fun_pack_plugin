# 麦爹必备娱乐小插件合集

MaiBot（麦麦）娱乐功能插件合集。**部分功能移植自 AstrBot 插件
[astrbot_plugin_essential](https://github.com/Soulter/astrbot_plugin_essential)（Soulter / FateTrial）**，
全部代码均针对 MaiBot 插件体系重新设计实现。

功能：**喜报 / 悲报图片生成、一言（不计入消息）、答案之书（翻看答案）、今天吃什么（命令 + 被动触发）、群早晚安作息记录、指令菜单**，
并把这些能力同时注册为麦麦可自主调用的 LLM 工具。本插件以 **MIT** 协议开源，将持续更新。

## 功能与命令

> **除 `一言` 和 `早安`/`晚安` 外，其余命令必须以 `/` 开头才生效**（直接发"喜报 ..."不会触发）。

| 命令 | 说明 | 麦麦是否接话 |
|---|---|---|
| `/工具列表` | 显示本插件全部指令（菜单） | 否 |
| `/喜报 <内容>` | 把内容渲染成喜报图片（红字黄边）发送 | 否 |
| `/悲报 <内容>` | 把内容渲染成悲报图片（黑字白边）发送 | 否 |
| `一言 [文字]`（`/` 可省） | 发一条随机一言（数据源 v1.hitokoto.cn）。**命令与回复不计入消息**：不入库、不同步进麦麦上下文，麦麦也不会接话 | 否 |
| `<问题> 翻看答案` | **答案之书**：从本地词条库（900 条）随机抽一条答案，**引用回复**你的问题。例如：`今天能否起飞 翻看答案`。另可直接发 `翻看答案` 查看用法 | 否 |
| `/今天吃什么` | **立即推荐**今天吃什么（有绑定图则图文发送） | 否 |
| `/今天吃什么 添加 食物1 食物2 ...` | 向清单添加食物 | 否 |
| `/今天吃什么 删除 食物1 食物2 ...` | 从清单删除食物 | 否 |
| 聊天中提到“吃什么” | **被动触发**（非命令）：按概率（默认 30%）推荐美食或复读“是啊，吃什么”；60 秒内被动响应超 3 次强制推荐、复读后 15 秒冷却（防多 Bot 循环）；回复后默认拦截该消息 | 默认拦截 |
| 早安 / `晚安`（支持"晚安啦~"等常见后缀，`/` 可省） | 记录作息并回复统计（睡了多久 / 本群今天第 N 个睡觉的）；**之后放行消息，麦麦自行决定是否再回复** | 是 |

## 被动触发与食物图片

“今天吃什么”的命令和被动触发共用同一份食物清单、推荐文案与图片：

- **被动触发**：聊天消息包含配置的关键词（默认“吃什么”）时，按概率（默认 30%）推荐美食或复读“是啊，吃什么”。
- **防循环限流**：同一会话 60 秒内被动响应超过 3 次后强制推荐（不再复读）；复读后 15 秒冷却，冷却期内触发也强制推荐——避免多个机器人互相复读刷屏。
- **拦截说明**：默认回复后拦截该消息（该消息不入库、麦麦不再对其回复），与原插件行为一致；希望麦麦也参与接话的话，把 `[what_to_eat]` 的 `intercept_message` 改为 `false`。
- **食物图片**：把图片放进 `data/plugins/maibot.fun-pack/food_images/`，文件名包含食物名即自动绑定，如 `黄焖鸡米饭.jpg`、`黄焖鸡米饭_1.png`、`螺蛳粉-2.png`；推荐到该食物时随机附带一张。目录每 2 分钟自动重扫，不放图则纯文字推荐。

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

## 安装

1. 将本插件目录放入 MaiBot 的 `plugins/` 目录（目录名可自定义，建议与仓库名一致；
   OneKey 部署为 `<数据>\modules\MaiBot\plugins\`）。
2. 在 WebUI（http://127.0.0.1:8001）插件管理中加载插件（更新代码后点重载即可，无需重启）。
   依赖 `aiohttp`、`Pillow` 由插件系统按 manifest 声明自动安装。
3. 日志出现"麦爹必备娱乐小插件合集已加载"即可测试。

## 配置

运行时配置文件 `config.toml` 由 Runner 自动生成（勿提交），支持热重载，主要项：

| 配置节 | 字段 | 默认 | 说明 |
|---|---|---|---|
| `[report]` | `font_size` | 65 | 喜报/悲报字体大小（20~200） |
| `[good_morning]` | `cooldown_minutes` | 30 | 同一用户两次早晚安的最小间隔（0 不限制） |
| `[good_morning]` | `forward_to_mai` | true | 记录后把统计信息交给麦麦供其发挥 |
| `[hitokoto]` | `request_timeout_sec` | 10 | 一言 API 请求超时（秒） |
| `[what_to_eat]` | `enabled` | true | 启用被动触发 |
| `[what_to_eat]` | `trigger_keywords` | ["吃什么"] | 被动触发关键词列表 |
| `[what_to_eat]` | `recommend_probability` | 0.3 | 推荐食物的概率（其余复读） |
| `[what_to_eat]` | `intercept_message` | true | 被动回复后是否拦截该消息 |
| `[what_to_eat]` | `rate_limit_enabled` / `rate_limit_max` / `rate_limit_window_seconds` | true / 3 / 60 | 频率限制（防多 Bot 循环） |
| `[what_to_eat]` | `echo_cooldown_enabled` / `echo_cooldown_seconds` | true / 15 | 复读冷却 |

## 能力声明（capabilities）

`send.text`、`send.image`、`send.hybrid`、`maisaka.context.append`、`chat.get_stream_by_group_id`、`chat.get_stream_by_user_id`。修改 manifest 中的能力声明后必须完整重启 MaiBot。

## 持续更新

本插件会持续更新：后续计划加入更多娱乐功能，并持续优化现有体验。
欢迎通过 Issue 反馈想玩的功能、报告问题，PR 也欢迎。

## Credits

- 部分功能（喜报/悲报、一言、今天吃什么、早晚安）移植自
  [astrbot_plugin_essential](https://github.com/Soulter/astrbot_plugin_essential)（Soulter / FateTrial），MIT License
- 今天吃什么的被动触发/复读/限流设计移植自
  [astrbot_plugin_what_to_eat](https://github.com/Sisyphbaous-DT-Project/astrbot_plugin_what_to_eat)（C₂₂H₂₅NO₆），MIT License
- 一言数据源：[v1.hitokoto.cn](https://v1.hitokoto.cn/)
- 早晚安玩法灵感：[nonebot_plugin_morning](https://github.com/MinatoAquaCrews/nonebot_plugin_morning)
- 喜报/悲报字体：[Noto Sans SC](https://fonts.google.com/noto/specimen/Noto+Sans+SC)（Google，SIL Open Font License 1.1，
  许可文本见 `assets/OFL.txt`，允许随本项目再分发）
