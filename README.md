# 群聊增强插件 (Chat Plus) — 精简重构版

---

<div align="center">

[![Version](https://img.shields.io/badge/version-V2.1.0--lite-blue.svg)](https://github.com/Sihnbaobao/astrbot_plugin_chat_plus_lite)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A5v4.11.0-green.svg)](https://github.com/AstrBotDevs/AstrBot)<!-- 插件页需 v4.25.3+ -->
[![Plugin Pages](https://img.shields.io/badge/Plugin%20Pages-v4.25.3%2B-purple.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-AGPL--3.0-orange.svg)](LICENSE)

一个以 **AI读空气** 为核心的群聊增强插件，让你的Bot更懂氛围、更自然地参与群聊互动

</div>

---

## 🎯 重构核心理念（V2.5.0-lite）

> **插件只决定"要不要回复"，不决定"说什么"。**
> 回复内容完全交给 AstrBot 原始链路（用户设定的人格 + 平台默认 prompt）。

旧版本在每次群聊回复时都会注入约 100 行系统行为指令（SYSTEM_REPLY_PROMPT）以及情绪提示、
主动对话标记等文本，导致**群聊中 bot 的人格表现与私聊明显不同**（说话更短、更直接、少解释性语言）。

本次重构删除了所有注入到 LLM 请求的行为指令：
- 群聊回复请求的 system_prompt **只含人格设定**（persona_manager 原样输出）
- prompt **只含纯上下文**（历史消息 + [时间] 昵称(ID): 消息 发送者标注）
- 群聊里 AI 看到的指令与私聊几乎相同，只多"谁在说话"的必要信息

## ✅ 保留功能

| 功能 | 说明 |
|---|---|
| AI 读空气 | 独立 LLM 调用判断"要不要回复"，只输出 yes/no，不影响回复人格 |
| 概率筛选 | 非@消息按概率回复，回复后概率提升 |
| 关键词触发 | 命中关键词必回（可开智能模式：跳过概率但保留读空气判断） |
| @机器人必回 | @消息跳过所有判断直接回复 |
| 图片识别 | 图片转文字（可配独立提供商）/ 多模态直传，平台图片描述提取与缓存（省钱） |
| 转发消息解析 | QQ/OneBot 合并转发消息自动展开为纯文本 |
| 黑名单 | 用户 ID 黑名单 + 关键词黑名单 |
| 时间戳/发送者标注 | 历史与当前消息标注 [时间] 昵称(ID) |
| 记忆注入 | livingmemory 集成（v1/v2 自动兼容，会话+人格隔离） |
| 插件页管理控制台 | AstrBot Dashboard 内嵌插件页：卡片式流程可视化 + 一键配置 + 提示词预览（无需单独端口/密码） |
| 戳一戳 | 回复后戳 / 收到戳后反戳 / 戳过追踪提示 / 群白名单 |
| Smart 并发 | 同群同期消息智能合并为批次统一回复，支持批次上下文提示 |
| 其他 | 指令过滤、@全体成员/@他人过滤、回复去重、内容过滤（输出/保存）、新成员入群解析、表情包标记、官方历史同步 |

## ❌ 已删除功能（迁移指南）

以下功能与配置项在 V2.5.0-lite 中已移除，升级后相关配置自动失效（保留在旧配置文件中也无效）：

| 已删除 | 影响 | 替代方案 |
|---|---|---|
| 私聊处理（enable_private_chat 及全部 private_* 配置） | 私聊完全交给 AstrBot 默认链路 | 无需替代，这正是重构目标 |
| 情绪系统（enable_mood_system 及 mood_*） | 不再注入情绪参考提示 | 无 |
| 注意力机制（enable_attention_mechanism 及 attention_*、cooldown_*、pending_cooldown_*） | 概率调整回到传统模式 | 概率参数（保留） |
| 主动对话（enable_proactive_chat 及 proactive_*、score_*、complaint_*） | bot 不再主动发起话题 | 平台自带的主动回复/主动对话功能 |
| 群聊等待窗口（enable_group_wait_window 及 group_wait_window_*） | 消息不再批量等待 | Smart 并发（保留） |
| 对话疲劳（enable_conversation_fatigue 及 fatigue_*） | 不再按疲劳度调整回复 | 无 |
| 错字生成 / 打字模拟 / 拟人模式（enable_typo_generator、enable_typing_simulator、enable_humanize_mode 及关联配置） | 不再模拟真人打字/错字 | 无 |
| 频率调整（enable_frequency_adjuster 及 frequency_*） | 不再按发言频率调概率 | 无 |
| 消息质量评分 / 回复密度（enable_message_quality_scoring、enable_reply_density_limit 及关联配置） | 概率不再受消息质量/密度影响 | 无 |
| 动态时间段概率（enable_dynamic_reply_probability 及 reply_time_*） | 概率不再按时段调整 | 无 |
| 工具提醒文本注入（enable_tools_reminder） | 不再向 system_prompt 注入工具列表文本 | 工具调用本身不受影响 |
| 单独无信息@消息强化上下文（single_at_message_*） | 空@消息按默认占位符处理 | 无 |
| 独立 Web 面板（enable_web_panel 及全部 web_panel_* 配置，含访问日志/安全防护） | 不再单独开端口，无访问日志 | AstrBot 插件页「管理控制台」（v4.25.3+） |

## 🚀 快速开始

1. 将插件放入 AstrBot 的插件目录并启用
2. 基础配置（AstrBot 插件配置页，或插件页「管理控制台」）：
   - enable_group_chat：群聊总开关
   - enabled_groups：留空 = 全部群启用；填群号 = 仅指定群
   - initial_probability：初始读空气概率（0~1）
   - trigger_keywords：触发关键词列表
3. 可选配置：
   - enable_image_processing + image_to_text_provider_id：图片转文字（推荐）
   - enable_memory_injection：livingmemory 记忆注入（需安装 astrbot_plugin_livingmemory）
   - enable_poke_after_reply：回复后戳一戳（仅 QQ + aiocqhttp）
   - concurrent_mode = "smart"：Smart 并发合并
4. 可视化管理：AstrBot Dashboard → 插件 → 本插件 → 打开「管理控制台」页面
   （v4.26.0+ 也可从侧边栏插件 WebUI 入口进入），卡片式流程与一键配置无需单独端口

## 📋 平台建议

- **必须开启 AstrBot 平台的"群聊上下文感知"**（group_chat_context），否则插件拿到的群聊历史不完整
- 如同时使用平台主动回复功能，请关闭其一，避免重复回复
- 如需「分段回复」功能，请保持「仅对 LLM 结果分段」开启

## 🧪 开发与测试

本机无 AstrBot 运行时的语法/回归检查：

    python -m py_compile main.py utils/*.py
    python -m pytest tests -q

测试覆盖（tests/）：
- test_image_handler.py：引用消息中的图片识别（原有）
- test_refactor_lite.py：重构核心保证——回复请求不含行为指令、system_prompt 只含人格、
  决策提示词无已删功能引用、缓存过期过滤、关键词/黑名单匹配

## 📁 项目结构

    astrbot_plugin_chat_plus_lite/
    ├── main.py                  # 主入口（精简版）
    ├── _conf_schema.json        # 配置项 78 项（14 个功能分组，卡片分栏展示）
    ├── metadata.yaml
    ├── utils/
    │   ├── reply_handler.py     # 回复构建：人格 + 纯上下文（无行为指令）
    │   ├── decision_ai.py       # 读空气判断（yes/no）
    │   ├── probability_manager.py / keyword_checker.py / message_cleaner.py
    │   ├── message_processor.py / context_manager.py / message_cache_manager.py
    │   ├── image_handler.py / image_description_cache.py / platform_ltm_helper.py
    │   ├── forward_message_parser.py / welcome_message_parser.py / emoji_detector.py
    │   ├── memory_injector.py   # livingmemory 集成
    │   ├── smart_concurrent_manager.py
    │   └── ai_response_filter.py / ai_error_formatter.py / content_filter.py
    ├── pages/control/           # AstrBot 插件页管理控制台（卡片式）
    └── tests/                   # 回归测试

## 📄 更多文档

- [重构设计文档](docs/REFACTOR_DESIGN.md) — 本次重构的完整设计与删除/保留清单
- [架构深度指南](docs/ARCHITECTURE.md) — 插件工作原理（部分章节描述旧版功能，仅供参考）
- [配置项参考](docs/CONFIG_REFERENCE.md) — 完整配置说明（部分已删配置不再生效）
