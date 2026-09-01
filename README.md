# Persona Presence

Persona Presence 是面向 AstrBot 的群聊与私聊消息增强插件。它让当前 Persona 基于兴趣、关系、上下文和当下意愿选择是否参与；媒体整理、Smart 批处理和正式回复仍沿用 AstrBot 的正常链路。

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/Sihnbaobao/astrbot_plugin_persona_presence)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.11.0-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![Plugin Pages](https://img.shields.io/badge/Plugin%20Pages-v4.25.3%2B-purple.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-AGPL--3.0-orange.svg)](LICENSE)

> 当前版本：1.0.0。插件标识已更新为 astrbot_plugin_persona_presence；插件元数据兼容 AstrBot >= 4.11.0，插件页管理控制台建议使用支持 Plugin Pages 的 AstrBot 版本（4.25.3+）。

## 功能概览

- 群聊参与判断：默认观察普通群聊，但开放话题不是默认插话入口；模型需要判断当前 Persona 是否有具体、自然的个人切入点，强兴趣可以展开，较弱但明确的补充也可以只说一句。
- 群聊安全边界：只对无正文的他人定向消息、纯媒体和明显低信息短句提前过滤；有正文的他人对话仍交给模型判断是否适合旁观补充。
- 私聊独立策略：普通私聊默认可以直接回应，不继承群聊的安静人格规则。
- Smart 连续消息：短时间连续发送的多条消息可以合并为一轮输入，只生成一条综合回复。
- 图片处理：图片转文字、图片描述缓存、多模态直传，以及私聊纯图片独立策略。
- 表情包处理：纯表情包可忽略、交给参与判断或直接处理；重复表情包可折叠。
- 人格切换：正式回复每次解析当前会话最终人格，支持会话强制人格、会话选择人格和默认人格。
- 上下文与历史：使用 AstrBot 官方历史链路，支持时间、发送者和媒体信息整理。
- 关键词、黑名单、指令过滤、回复去重、内容过滤、转发消息解析、戳一戳等辅助功能。
- AstrBot 插件页管理控制台：从插件页直接查看和修改 schema 中的配置项。

## 回复边界

插件不替换 AstrBot 当前人格，也不把旧版的情绪、注意力、主动对话等内部状态重新注入系统提示。DecisionAI 先输出受校验的参与结果，再决定是否继续正式回复流程；它的完整 JSON 和分析过程不会传给正式回复模型。正式请求使用当前人格、消息上下文，以及涉及其他群友时的最小参与边界提示。reply_ai_extra_prompt 只影响正式回复生成，不会被保存为用户历史正文。

正式回复的人格选择顺序由 AstrBot 会话机制决定：

1. 会话强制人格。
2. 当前会话选择的人格。
3. 提供商默认人格。

因此，切换 Persona 后，下一次正式回复会重新解析当前会话人格。插件不会把会话对象重复传给 request_llm，以避免和插件现有的官方历史保存路径重复写入。

## 群聊行为

群聊默认开启，`group_reply_scope=ambient` 时普通群消息可以进入参与判断。开放性群消息默认克制，但是否开口交给当前 Persona 的整体意愿；有强烈兴趣时可以展开，只有轻微但自然的想法时也可以低打扰地插一句。明确回复其他用户的消息仍需人格自己的独立补充，不能替对方作答或接管话题。@、点名和关键词只提高注意力，不保证回复。纯图片/贴纸和低信息短句仍会按明显噪声处理。未被接受的消息会标记为 observation-only，不会自动制造对话目标；open/side 通过结果还受 45 秒、10 分钟、4 次的默认预算限制。

将 `group_reply_scope` 改为 `addressed` 后，未明确指向机器人的群消息在参与判断前静默。明确指向包括 @机器人、当前文本可靠点名、结构化回复引用机器人的消息、戳机器人或触发关键词；候选消息仍由 Persona 判断，任何一种 signal 都不保证回复。这个模式适合需要更安静的群聊。

concurrent_mode 有两种模式：

- legacy：按消息逐条处理。
- smart：短时间内的连续消息组成一个批次，由较早到达的消息作为 anchor，后续消息作为批次上下文参与一次回复。

群聊 Smart 主要解决并发上下文组织，不会把不相关用户的消息强行改写成同一个人的一句话。

## 私聊行为

私聊默认关闭，以保持升级兼容。开启 enable_private_chat 后，enabled_private_users 留空表示处理所有私聊；填写用户 ID 后只处理指定用户。

### 普通私聊

private_reply_mode 控制普通私聊文本：

- direct：直接进入正式回复流程，适合一对一聊天，也是当前推荐模式。
- decide：使用私聊专用参与判断。问候、问题、请求和连续对话通常倾向回应；明显拒绝、发错对象、重复垃圾或无意义内容可能被跳过。

takeover_private_reply 控制插件明确判断“不回复”时是否阻止 AstrBot 默认兜底。参与判断发生异常时会放行核心链路，不会因为判断服务失败而静默吞掉普通消息。

### 私聊 Smart

推荐配置：

- private_concurrent_mode = smart
- private_batch_wait_ms = 4500
- private_batch_max_size = 10

Smart 的含义是“短时间连发合并”，不是“只要机器人还没回复就无限等待”。例如：

    a在吗
    刚才那个问题你看到了吗
    我再补充一句

如果这些消息在约 4500ms 的短窗口内到达，会被组织成一轮输入并只生成一条综合回复。关键词或 @ 只影响是否触发回复，不会绕过这个私聊 Smart 等待窗口。相同文本重复发送时，模型会收到重复次数提示，并按当前 Persona 对啰嗦和催促的态度自然回应；不会为同一批消息逐条调用正式回复。

相隔几秒的消息属于不同轮次。窗口外的后续消息不会再额外等待前一个模型请求十秒，而是快速进入自己的处理流程。因此，增大窗口可以合并更慢的连发，但也会增加首条消息的等待时间，建议在 3000-6000ms 范围内调整。

## 图片与表情包

图片和表情包不是同一种消息，插件分别处理：

| 配置 | 可选值 | 默认值 | 作用 |
|---|---|---:|---|
| private_image_mode | ignore / decide / always | decide | 私聊纯图片的处理策略 |
| private_emoji_mode | ignore / decide / always | ignore | 私聊纯表情包的处理策略 |
| private_collapse_duplicate_emoji | bool | true | 短时间或同一批次内重复表情包只保留一份 |
| private_duplicate_emoji_window_ms | int | 1500 | 重复表情包折叠时间窗口 |
| enable_image_processing | bool | false | 是否将图片转换为文字描述 |
| image_to_text_provider_id | string | 空 | 图片转文字提供商；留空时按多模态链路处理 |

含文字的图文消息按普通消息处理，不会因为附带图片而自动套用“纯图片”策略。图片描述缓存可以减少重复图片的处理成本。livingmemory 记忆注入是可选能力，需要安装并正确配置对应记忆插件。

## 常用配置

完整字段和默认值以 _conf_schema.json 与 [配置参考](docs/CONFIG_REFERENCE.md) 为准。下面列出最常用的配置。表格中的值是 schema 默认值，实际运行配置可能位于 AstrBot 的 data/config 目录并与之不同：

| 配置 | 默认值 | 说明 |
|---|---:|---|
| enable_group_chat | true | 群聊总开关 |
| enabled_groups | [] | 留空处理所有群，否则只处理指定群 |
| takeover_group_reply | true | 是否由插件接管群聊静默结果；接管时参与判断失败也保持静默 |
| group_reply_scope | ambient | ambient 允许普通群消息进入参与判断；addressed 只让明确 signal 进入候选，@和关键词仍不保证回复 |
| enable_private_chat | false | 私聊总开关 |
| enabled_private_users | [] | 留空处理所有私聊用户，否则只处理指定用户 |
| private_reply_mode | direct | 普通私聊使用直接回复或私聊参与判断 |
| takeover_private_reply | true | 是否阻止私聊“不回复”时的核心兜底 |
| concurrent_mode | legacy | 群聊逐条或 Smart 批处理 |
| private_concurrent_mode | smart | 私聊逐条或短连发合并 |
| private_batch_wait_ms | 4500 | 私聊短连发等待窗口，单位毫秒 |
| private_batch_max_size | 10 | 单个私聊批次最多合并的消息数 |
| decision_ai_provider_id | 空 | 参与判断使用的提供商；留空跟随会话默认提供商 |
| decision_ai_include_persona | true | 参与判断是否携带当前人格 |
| ambient_reply_min_interval_seconds | 45.0 | open/side 主动参与的最小间隔（秒） |
| ambient_reply_window_seconds | 600.0 | open/side 参与统计窗口（秒） |
| ambient_reply_max_per_window | 4 | 单个群在窗口内最多 open/side 参与次数 |
| trigger_keywords | [] | 命中后提高注意力并进入统一参与判断，不直接保证回复 |
| keyword_smart_mode | true | 兼容旧配置；现在无论开关状态都不会让关键词绕过参与判断 |
| collapse_reply_newlines | false | 是否收敛普通纯文本回复中的主动换行 |
| enable_memory_injection | false | 是否启用 livingmemory 记忆注入 |
| enable_duplicate_filter | true | 是否过滤重复回复 |

配置页面中的分组为：基础、参与判断、触发、回复、管理、并发、扩展；配置项以 _conf_schema.json 为准。

## 安装与启用

如果从旧版 astrbot_plugin_chat_plus_lite 迁移，请先停止 AstrBot，并将旧插件目录、配置文件和 plugin_data 目录分别改名为 astrbot_plugin_persona_presence；只保留一个插件目录，避免重复处理消息。详细迁移步骤见 [配置参考](docs/CONFIG_REFERENCE.md#从旧版本迁移)。

1. 将插件目录放入 AstrBot 的 data/plugins/astrbot_plugin_persona_presence。
2. 启动或重启 AstrBot，在插件管理中启用 astrbot_plugin_persona_presence。
3. 在 AstrBot 配置页或插件页管理控制台修改配置。
4. 修改配置后按 AstrBot 的提示重新加载插件；修改 Python 代码后需要重启服务。

插件页管理控制台不需要单独端口。图片、戳一戳和 OneBot 相关能力仍取决于当前平台适配器是否提供对应事件和接口。

## 推荐起步配置

群聊只想让机器人偶尔插话时：

- enable_group_chat = true
- concurrent_mode = smart
- keyword_smart_mode = true
- group_reply_scope = ambient
- ambient_reply_min_interval_seconds = 45
- ambient_reply_window_seconds = 600
- ambient_reply_max_per_window = 4
- 保持 takeover_group_reply = true

希望机器人稳定回应私聊时：

- enable_private_chat = true
- private_reply_mode = direct
- private_concurrent_mode = smart
- private_batch_wait_ms = 4500
- private_emoji_mode = ignore
- 根据需要设置 enabled_private_users

如果同时启用了 AstrBot 或其他插件的主动回复功能，只保留一套主动回复逻辑，避免重复回复。

## 常见问题

### 如何清理聊天历史？

使用 AstrBot 或当前平台提供的 `/reset`。Persona Presence 不再注册旧的 `gcp_reset` 和 `gcp_reset_here` 指令；`gcp_clear_image_cache` 只清理图片描述缓存，不影响聊天历史。

### 被 @ 了为什么没有回复？

@、点名、戳和关键词只提高参与判断的注意力，不是强制命令。当前 Persona 仍可能因为无聊、重复、冒犯、话题已结束、只是在等其他人回答，或当下没有具体兴趣而保持安静；这是接管模式下的预期行为。

### 没有 @ 为什么偶尔会回复？

ambient 模式允许普通群消息进入判断。Persona 通常会先观察，但是否开口主要由当下的性格、兴趣、情绪和聊天氛围决定；interest、reason 等字段用于表达和诊断，不再额外制造强度门槛。open/side 回复仍受参与预算限制，side 只能补充自己的内容。

### 上午的旧话题会被误认为下午的续话吗？

不会仅凭旧历史认定 continuation。DecisionAI 会结合当前消息、近期机器人回复和中间的群聊内容判断；群聊中还会由代码核对当前发送者是否确实是最近机器人回复对应的发送者，避免把别人的消息接到旧话题上。如果 B 只是短暂且无关的插话，不自动认为话题结束，如果后续聊天已经实质接管或明显转向，也不应只因主题相似就继续上午的话题。下午的新消息仍可以被 Persona 当成一个全新的 open 话题来判断；明确 @ 机器人则照常按当前消息回应，但不会携带未经核实的旧续话标记。单纯经过一段时间、期间没有其他消息时，不会被时间阈值强行切断。

### 连续发消息为什么还是逐条回复？

先检查消息间隔是否超过 private_batch_wait_ms。默认窗口是 4500ms，相隔 5 秒或 8 秒的消息不属于同一批。Smart 不是“等待机器人回复结束后再合并全部消息”的模式；要使用更长的合并范围，需要增大窗口，同时接受首条消息会更晚回复。

### 私聊回复为什么仍然慢？

每条私聊 Smart 消息最多增加配置窗口的等待时间；图片描述、记忆检索和模型生成也会增加耗时。当前版本已经移除了旧的“同会话最多等待十秒”私聊保护。如果更重视响应速度，可以将 private_batch_wait_ms 调到 3000；同时分别检查图片处理、记忆注入和模型本身的耗时。

### 表情包为什么不回复？

纯表情包默认是 ignore，这是为了避免把水消息和单纯情绪表达都交给模型。需要判断时改为 decide，需要始终处理时改为 always。含文字的图文消息不受这个纯表情包策略影响。

### 为什么回复里有多余换行？

开启 collapse_reply_newlines 会收敛普通纯文本中的主动换行；代码块、Markdown 列表和其他结构化输出会保留格式。

### Persona 切换后为什么要看下一条回复？

人格是在正式回复请求开始时解析的。切换后已经发出的请求不会回溯重生成，下一次正式回复才会使用新的会话人格。

## 开发与测试

在插件目录执行：

    uv run python -m pytest tests -q
    uv run python -m py_compile main.py utils/reply_handler.py utils/decision_ai.py
    uv run ruff format main.py utils tests
    uv run ruff check --select E9,F821,F823 main.py utils tests

当前回归测试覆盖：

- 回复请求的人格解析和提示词边界。
- 私聊图片、表情包和换行策略。
- Smart 批次大小、到达顺序和后续消息吸收。
- 配置 schema 与本地运行配置的一致性。

## 项目结构

    astrbot_plugin_persona_presence/
    ├── main.py                         # 插件入口和消息处理主流程
    ├── _conf_schema.json               # 插件页配置 schema
    ├── metadata.yaml                   # 插件元数据和版本
    ├── utils/
    │   ├── decision_ai.py              # 群聊/私聊参与判断
    │   ├── reply_handler.py            # 正式回复请求和人格解析
    │   ├── smart_concurrent_manager.py # Smart 批次协调
    │   ├── context_manager.py          # 历史与上下文整理
    │   ├── image_handler.py            # 图片处理
    │   ├── memory_injector.py          # livingmemory 集成
    │   └── ...
    ├── pages/control/                  # AstrBot 插件页管理控制台
    ├── tests/                          # 回归测试
    └── docs/                           # 配置和设计文档

## 相关文档

- [配置参考](docs/CONFIG_REFERENCE.md)
- [重构设计说明](docs/REFACTOR_DESIGN.md)
- [更新日志](CHANGELOG.md)
- [插件仓库](https://github.com/Sihnbaobao/astrbot_plugin_persona_presence)

## 许可证

本项目使用 AGPL-3.0，详见 [LICENSE](LICENSE)。
