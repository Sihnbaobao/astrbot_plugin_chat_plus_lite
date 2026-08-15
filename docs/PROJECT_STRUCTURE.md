# 项目结构说明

> ⚠️ 本文档描述的是旧版（V1.2.x）结构。当前分支为 refactor-lite（V2.4.2-lite）精简重构版：
> 已删除 private_chat/ 目录及 utils/ 下的 attention_manager、cooldown_manager、mood_tracker、
> proactive_chat_manager、typo_generator、typing_simulator、humanize_mode、frequency_adjuster、
> message_quality_scorer、reply_density_manager、time_period_manager、system_prompt_rewriter、
> tools_reminder 等模块。当前模块清单见 [README 项目结构](../README.md)。
> V2.4.2-lite 起，独立 Web 面板（web/ 目录）已整体移除，管理界面迁入 pages/control/ 插件页。
>
> 本文档详细描述了群聊增强插件的完整文件结构及每个文件的职责。

[← 返回 README](../README.md) | [深度指南与常见问题](ARCHITECTURE.md) | [消息工作流程](MESSAGE_WORKFLOW.md) | [配置项参考](CONFIG_REFERENCE.md) | [桌面端兼容](DESKTOP_COMPATIBILITY.md) | [重构设计](REFACTOR_DESIGN.md)

---

## 目录结构总览

```
astrbot_plugin_chat_plus_lite/
│
├── main.py                     # 插件主入口
├── metadata.yaml               # 插件元数据
├── _conf_schema.json           # 配置项定义（JSON Schema）
├── requirements.txt            # Python 依赖
├── README.md                   # 项目说明
├── CHANGELOG.md                # 更新日志
├── LICENSE                     # AGPL-3.0 许可证
│
├── docs/                       # 📖 文档目录
│   ├── MESSAGE_WORKFLOW.md     # 消息工作流程详解
│   ├── CONFIG_REFERENCE.md     # 配置项完整参考
│   ├── DESKTOP_COMPATIBILITY.md # AstrBot 桌面端兼容说明
│   └── PROJECT_STRUCTURE.md    # 本文件
│
├── pages/                     # 🖥️ AstrBot 插件页（V2.4.2-lite 起）
│   └── control/                # 管理控制台（卡片式/胶囊式）
│       ├── index.html          # 页面骨架
│       ├── app.js              # 交互逻辑（bridge 调用后端 API）
│       └── style.css           # 样式（CSS 变量双主题）
│
├── utils/                      # 🧩 群聊工具模块
│   ├── __init__.py             # 模块导出
│   ├── probability_manager.py  # 概率管理器
│   ├── decision_ai.py          # AI 决策（读空气）
│   ├── reply_handler.py        # AI 回复生成
│   ├── message_processor.py    # 消息元数据注入
│   ├── context_manager.py      # 上下文管理器
│   ├── image_handler.py        # 多媒体处理（图片/视频/语音/文件）
│   ├── image_description_cache.py # 图片描述缓存
│   ├── keyword_checker.py      # 关键词检测
│   ├── message_cleaner.py      # 历史消息清洗
│   ├── attention_manager.py    # 注意力机制
│   ├── mood_tracker.py         # 情绪追踪
│   ├── proactive_chat_manager.py # 主动对话
│   ├── humanize_mode.py        # 拟人模式
│   ├── emoji_detector.py       # 表情检测
│   ├── frequency_adjuster.py   # 频率调整
│   ├── typing_simulator.py     # 打字延迟模拟
│   ├── typo_generator.py       # 打字错误生成
│   ├── time_period_manager.py  # 时段概率管理
│   ├── forward_message_parser.py # 公共转发消息解析内核
│   ├── welcome_message_parser.py # 欢迎消息解析
│   ├── memory_injector.py      # 长期记忆注入
│   ├── tools_reminder.py       # 工具提示
│   ├── system_prompt_rewriter.py # system_prompt 兼容增强与保守回退
│   ├── platform_ltm_helper.py  # 平台图片说明提取
│   ├── cooldown_manager.py     # 注意力冷却
│   ├── message_cache_manager.py# 待处理消息缓存
│   ├── content_filter.py       # 内容过滤器
│   ├── ai_response_filter.py   # AI 回复验证
│   ├── ai_error_formatter.py   # 🆕 AI 错误格式化（识别服务商故障/网络问题/HTML错误页）
│   ├── message_quality_scorer.py # 消息质量预判
│   ├── reply_density_manager.py# 回复密度限制
│   └── _session_guard.py       # 会话安全守卫
│
└── private_chat/               # ⚠️ 私聊模块（开发测试中，非正式版本）
    ├── __init__.py
    ├── private_chat_main.py    # 私聊主处理器
    └── private_chat_utils/     # 私聊工具模块
        ├── __init__.py
        └── ... (14 个模块)    # 群聊工具的私聊版本
```

---

## 根目录文件

### main.py — 插件主入口

插件的核心文件（约 8400+ 行），包含：

- **插件类定义** — 继承 AstrBot 插件基类，注册事件处理器
- **配置读取** — 从 `_conf_schema.json` 读取并初始化所有配置项
- **模块初始化** — 创建并管理所有 `utils/` 中的工具模块实例
- **事件处理器**：
  - `on_group_message()` — 群聊消息入口，执行 Phase 1-3
  - `_process_message()` — 消息主处理管线，执行 Phase 4-9
  - `on_llm_request()` — LLM 请求钩子（优先级 -1），负责上下文注入、system_prompt 兼容重写、第三方长期提示词吸收与历史处理
  - `on_llm_response()` — LLM 响应钩子（优先级 -1），设置 Agent 完成标志（`_agent_done_flags`），在 Agent 无最终文本时触发兜底保存
  - `on_decorating_result()` — 结果装饰钩子，负责多轮工具调用中累积 AI 中间回复文本（`_pending_bot_replies`）、内容过滤、重复检测
  - `after_message_sent()` — 消息发送后处理，合并累积的中间文本与工具调用记录（`_build_interleaved_tool_reply()`），保存到双轨存储；异常终止时通过异常检测（AI 错误标记 / 非 LLM 终端响应）强制保存
- **主动对话** — 定时任务，独立于消息流程运行
- **Web 面板启动** — 初始化 Web 服务器

### metadata.yaml — 插件元数据

定义插件名称、版本号（V1.2.3.hotfix.1）、作者、描述、AstrBot 最低版本要求等。AstrBot 平台通过此文件识别和管理插件。

### _conf_schema.json — 配置定义

约 94KB 的 JSON Schema 文件，定义了 100+ 个配置项的：
- 字段名与数据类型
- 默认值
- 描述文本（显示在 AstrBot 配置面板中）
- 枚举选项（如 `image_to_text_scope` 的可选值）

### requirements.txt — 依赖


> `aiohttp` 为 AstrBot 平台自带依赖，通常无需手动安装。

---

## pages/control/ — AstrBot 插件页管理控制台（V2.4.2-lite 起）

> 原独立 Web 面板（web/ 目录）已于 V2.4.2-lite 整体移除，管理界面改为 AstrBot 插件页。
> 需要 AstrBot v4.25.3+（Plugin Pages 机制自动发现 pages/ 目录并挂载到 Dashboard）。

### index.html — 页面骨架

卡片式/胶囊式布局：头部状态条（版本/总开关/倾向/并发模式）、
消息处理流水线（5 个胶囊：概率筛选 → 指令&关键词 → @必回 → 读空气AI判断 → 回复生成）、
功能卡片网格（图片识别/转发解析/黑名单/记忆注入/表情包降权/戳一戳/防复读/Smart并发/内容过滤）、
提示词预览区。

### app.js — 交互逻辑

- 通过 window.AstrBotPluginPage bridge 调用后端 API（iframe 内嵌，复用 Dashboard 登录态）
- 渲染胶囊/卡片/编辑表单（switch / number / select 按字段类型生成）
- 保存时收集面板内全部字段 → POST config/save（后端白名单 45 键）

### style.css — 样式

CSS 变量双主题（跟随 Dashboard data-theme），响应式网格，状态徽章（绿=启用/灰=关闭）。

### 后端 API（main.py 中 register_web_api 注册）

| 路由 | 方法 | 说明 |
|------|------|------|
| /astrbot_plugin_chat_plus_lite/status | GET | 状态总览：版本、45 项配置当前值、运行时统计（概率会话/Smart快照/处理中） |
| /astrbot_plugin_chat_plus_lite/config/save | POST | 保存白名单配置，写入 AstrBot 配置并同步实例属性与 Smart 类级参数 |
| /astrbot_plugin_chat_plus_lite/prompts | GET | 提示词预览（读空气判断/回复生成，与真实拼接逻辑一致） |


## utils/ — 群聊工具模块

> 每个模块负责一个独立功能，由 `main.py` 统一创建和管理实例。

### 核心决策模块

| 文件 | 类 | 说明 |
|------|-----|------|
| `probability_manager.py` | `ProbabilityManager` | 管理动态概率计算，整合回复后提升、时段调整等因素 |
| `decision_ai.py` | `DecisionAI` | 核心"读空气"逻辑。构建提示词 → 解析判断型AI人格（默认跟随当前会话，也可按配置关闭或指定人格）→ 调用 AI → 解析 yes/no 决策结果 |
| `reply_handler.py` | `ReplyHandler` | AI 回复生成。构建完整上下文 → 采集工具快照与提醒元信息 → 以短消息/占位 prompt 调用 `event.request_llm()`，再由 `on_llm_request` 恢复完整上下文，并为后续第三方长期提示吸收保留短消息基线 |
| `system_prompt_rewriter.py` | `SystemPromptRewriter` | system_prompt 兼容增强器。优先复用旧版精确命中路径，在平台 persona/LTM 包装轻微变化时做轻量识别；若仍失败，则进入保守回退模式，优先保证回复链不断，并对疑似重复片段做轻量压缩 |

### 消息处理模块

| 文件 | 类 | 说明 |
|------|-----|------|
| `message_processor.py` | `MessageProcessor` | 为消息注入元数据（时间戳、发送者信息、`[戳一戳事件]` 持久化文本、系统提示词等），统一拼接在冒号 `:` 之前作为系统元数据区；冒号之后为用户消息内容（含 @ 内联解析 `[At:ID\|解析结果]`）。`[戳一戳提示]` **不由此模块注入**，而是由主流程在上下文拼接阶段追加到分隔符之外 |
| `context_manager.py` | `ContextManager` | 管理自定义消息存储 + 同步平台官方历史记录。处理历史截止时间戳。`format_context_for_ai` 负责拼接完整上下文，支持将 `[戳一戳提示]` 追加在分隔符 `=====` 之外 |
| `message_cleaner.py` | `MessageCleaner` | 清洗历史消息中的运行时内容（分隔线、`[戳一戳提示]`、背景信息块等）；提取原始消息链中的 At / AtAll / Image / Video / Record / File / Reply 结构并生成文本标记。引用消息格式为 `[引用 >>> 发送者(ID): 消息内容]`，使用 `>>>` 明确分隔引用标记与内容。若被引用消息发送者为 AI 自身，标注 `(你)`；内容无法提取时标注 `(无法获取引用内容)`。提供空@消息双模式判定（`contains_ai` / `only_ai`） |
| `image_handler.py` | `ImageHandler` | 多媒体文件处理核心：图片（转文字/多模态直传）、视频/语音/文件路径提取与内联标记注入、媒体标记占位符生成、缓存剥离前的标记富化。引用组件解析同 `message_cleaner.py` 的 `>>>` 格式 |
| `image_description_cache.py` | `ImageDescriptionCache` | 本地缓存图片描述结果，避免重复 API 调用；当前主缓存文件为 `image_cache/descriptions.jsonl` |
| `forward_message_parser.py` | `ForwardMessageParser` | 群聊与私聊共用的公共转发解析内核，面向 QQ / OneBot 合并转发，支持在深度限制内展开嵌套转发，并将结果折叠为单条可读文本继续下传 |
| `welcome_message_parser.py` | `WelcomeMessageParser` | 检测新成员入群消息 |
| `keyword_checker.py` | `KeywordChecker` | 匹配触发关键词和黑名单关键词 |
| `emoji_detector.py` | `EmojiDetector` | 检测消息是否为纯表情/贴图 |
| `message_quality_scorer.py` | `MessageQualityScorer` | 判断消息质量（疑问句加权、水聊降权） |
| `content_filter.py` | `ContentFilter` | 按规则过滤 AI 输出内容 |
| `ai_response_filter.py` | `AIResponseFilter` | 验证 AI 回复的有效性 |
| `ai_error_formatter.py` | `format_ai_error()` | 🆕 AI 错误格式化器：识别 HTTP 状态码/HTML 网关错误页/上游模型空输出/网络异常，输出清晰可读的错误信息（区分「服务商故障」和「代码问题」） |
| `platform_ltm_helper.py` | `PlatformLTMHelper` | 提取平台消息中的图片说明（caption） |

### 行为模拟模块

| 文件 | 类 | 说明 |
|------|-----|------|
| `attention_manager.py` | `AttentionManager` | 多用户注意力追踪（0-1连续值），指数衰减，情绪检测，溢出效应 |
| `mood_tracker.py` | `MoodTracker` | 情绪状态追踪和检测 |
| `humanize_mode.py` | `HumanizeMode` | 拟人模式状态机（沉默→关注→参与），动态消息阈值 |
| `proactive_chat_manager.py` | `ProactiveChatManager` | 主动对话管理，沉默检测，时机判断；其中主动对话预判断AI也支持独立的人格开关与指定人格 |
| `typing_simulator.py` | `TypingSimulator` | 根据文本长度计算打字延迟 |
| `typo_generator.py` | `TypoGenerator` | 基于拼音相似性生成自然错别字 |
| `frequency_adjuster.py` | `FrequencyAdjuster` | 分析群聊消息频率，动态调整回复频率 |
| `time_period_manager.py` | `TimePeriodManager` | 按时段调整概率，支持平滑过渡（正弦曲线） |
| `cooldown_manager.py` | `CooldownManager` | 注意力冷却机制 |

### 辅助模块

| 文件 | 类 | 说明 |
|------|-----|------|
| `reply_density_manager.py` | `ReplyDensityManager` | 滑动窗口统计回复频率，实现软/硬限制 |
| `message_cache_manager.py` | `MessageCacheManager` | 管理待处理消息池（缓存+转正机制） |
| `memory_injector.py` | `MemoryInjector` | 集成长期记忆插件（LivingMemory / Legacy 模式） |
| `tools_reminder.py` | `ToolsReminder` | 基于当前会话最终工具集构建工具提醒文本；支持会话插件集过滤、可选的人格过滤，并会在 `skills_like` 模式下自动降级为仅展示工具名/描述，`full` 或旧版配置下保持名称/描述/参数的完整展示；仅作用于提醒层 |
| `_session_guard.py` | `SessionGuard` | 会话安全机制，防止并发冲突 |

---

## private_chat/ — 私聊模块

> **⚠️ 开发测试阶段，非正式版本。私聊部分的文件目前处于开发中，代码结构可能不稳定，内容可能混乱，请勿参考其实现细节。**

### 概述

私聊模块是群聊功能的简化版本，主要区别：
- **无概率筛选** — 私聊总是回复（不做"读空气"判断）
- **消息聚合** — 支持等待并批量合并多条消息
- **简化架构** — 较少的功能模块和配置项
- **回复链路对齐群聊** — 私信回复生成同样使用 `event.request_llm()` + `on_llm_request` 恢复完整上下文；私信主动对话使用 `ProviderRequest + OnLLMRequestEvent` 兼容链路

### 文件结构

```
private_chat/
├── __init__.py
├── private_chat_main.py              # 私聊主处理器（PrivateChatMain 类）
└── private_chat_utils/               # 私聊版工具模块
    ├── __init__.py
    ├── private_chat_image_handler.py          # 图片处理
    ├── private_chat_image_description_cache.py # 图片描述缓存
    ├── private_chat_message_processor.py       # 消息元数据注入
    ├── private_chat_context_manager.py         # 上下文管理（仅自定义存储）
    ├── private_chat_emoji_detector.py          # 表情检测
    ├── private_chat_forward_message_parser.py  # 转发消息解析（兼容导出，复用公共实现）
    ├── private_chat_keyword_checker.py         # 关键词检测
    ├── private_chat_memory_injector.py         # 记忆注入
    ├── private_chat_message_cleaner.py         # 消息清洗
    ├── private_chat_mood_tracker.py            # 情绪追踪
    ├── private_chat_proactive_chat_manager.py  # 主动对话
    ├── private_chat_reply_handler.py           # 回复生成
    ├── private_chat_session_guard.py           # 会话安全
    ├── private_chat_time_period_manager.py     # 时段管理
    ├── private_chat_tools_reminder.py          # 工具提示
    ├── private_chat_typing_simulator.py        # 打字模拟
    ├── private_chat_typo_generator.py          # 打字错误
    └── private_chat_content_filter.py          # 内容过滤
```

> 大多数文件基本对应 `utils/` 中同名模块的私聊适配版本；其中 `private_chat_forward_message_parser.py` 已收敛为兼容导出层，直接复用 `utils/forward_message_parser.py` 的公共转发解析实现。

---

## 数据文件（运行时生成）

以下文件在插件运行过程中自动创建，位于 AstrBot 的 `data/` 目录中：

| 文件 | 说明 |
|------|------|
| `history_cutoff.json` | 历史截止时间戳，记录 `gcp_reset` / `gcp_reset_here` 设置的截止点，用于过滤旧的 `platform_message_history` 历史 |
| `image_cache/descriptions.jsonl` | 图片描述缓存主文件。Web 面板和指令清理图片缓存时优先处理此文件；如检测到旧版 `image_description_cache.json` 残留路径，也会兼容清理 |

---

## 模块关系图

```
                         main.py
                     (插件主入口)
                    ┌──────┼──────┐
                    ↓      ↓      ↓
               pages/   utils/    private_chat/
            (插件页控制台) (群聊工具) (旧版模块 ⚠️)
                    ↓
        pages/control/ + main.py 注册的 Web API
        (index.html / app.js / style.css)
        (status · config/save · prompts)
```

```
main.py 中的消息处理调用链：

on_group_message()
  ├→ keyword_checker        (关键词检测)
  ├→ welcome_message_parser (入群消息)
  ├→ forward_message_parser (转发消息)
  │
  └→ _process_message()
      ├→ probability_manager   (概率计算)
      │   ├→ time_period_manager  (时段调整)
      │   ├→ frequency_adjuster   (频率调整)
      │   └→ humanize_mode        (拟人调整)
      │
      ├→ message_processor     (元数据注入)
      ├→ image_handler         (图片处理)
      │   └→ image_description_cache (缓存)
      ├→ emoji_detector        (表情检测)
      ├→ message_quality_scorer(质量预判)
      │
      ├→ message_cache_manager (等待窗口)
      │
      ├→ reply_density_manager (密度检查)
      ├→ decision_ai           (AI决策 "读空气")
      │   ├→ attention_manager    (注意力状态)
      │   ├→ mood_tracker         (情绪状态)
      │   └→ memory_injector      (pre_decision 记忆)
      │
      ├→ reply_handler         (AI回复生成)
      │   ├→ context_manager      (历史上下文)
      │   ├→ memory_injector      (post_decision 记忆)
      │   ├→ tools_reminder       (工具提示)
      │   └→ content_filter       (输出过滤)
      │
      └→ 回复后处理
          ├→ typing_simulator     (打字延迟)
          ├→ typo_generator       (打字错误)
          ├→ cooldown_manager     (注意力冷却)
          └→ proactive_chat_manager (状态更新)
```

---

[← 返回 README](../README.md) | [深度指南与常见问题](ARCHITECTURE.md) | [消息工作流程 →](MESSAGE_WORKFLOW.md) | [配置项参考 →](CONFIG_REFERENCE.md) | [桌面端兼容 →](DESKTOP_COMPATIBILITY.md)
