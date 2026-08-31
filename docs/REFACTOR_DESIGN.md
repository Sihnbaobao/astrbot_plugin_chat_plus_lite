# Persona Presence 重构设计

> 本文是当前实现的行为契约和维护入口。代码细节可以变化，但这里定义的群聊社交边界、数据流和失败策略不能被无意改回旧行为。

## 1. 目标

Persona Presence 的职责是帮助 AstrBot 在群聊中像一个真实群成员一样选择发言时机，同时保留 AstrBot 的人格、历史、媒体和正式回复链路。

目标不是让机器人尽可能多地回答，而是让每次开口都像人格自己的选择：

- 大多数群消息只被看见，不产生回复。
- @、点名、戳一戳、关键词和结构化回复会提高注意力，但都不是回复保证。
- 没有 @ 的公开话题，如果当前 Persona 有强烈、具体、立刻能说出的个人连接，仍然可以自然参与。
- “我知道答案”“我能帮忙”或“模型可以回答”不等于人格想发言。
- 明确无聊、重复、冒犯、打扰、已经结束、无信息或只等待别人回答的消息通常保持安静。

本次重构只改变参与决策和必要的上下文边界，不改变 AstrBot 正式回复模型的人格来源。

## 2. 不可违反的行为契约

### 2.1 三类参与姿态

每条候选群消息都要先确定说话姿态：

| participation | 含义 | 允许条件 |
| --- | --- | --- |
| direct | 消息在和机器人说，或是唯一明确的机器人续话 | 仍需人格愿意；被 @ 也可以拒绝 |
| side | 消息直接面向其他用户，但正文是公共话题 | 必须有强烈且具体的个人连接，且只能补充自己的内容 |
| open | 没有特定对象的公共发言入口 | 默认克制；强烈、具体、自然的个人连接可以展开，较弱但明确的第一人称补充也可以只说一句 |
| none | 没有可靠的自然发言入口 | 立即静默 |

side 不能替被 @ 的用户作答、替对方承诺、抢走对方的对话，也不能把一句泛泛知识答案包装成个人参与。

### 2.2 兴趣强度

- strong：当前内容明显击中 Persona，Persona 现在就想展开说自己的具体经历、观点或情绪。
- weak：没有强烈冲动，但有具体的第一人称补充，适合低打扰地只说一句；只是相关、可以回答、略有兴趣或知道一些背景，仍然不足以发言。open 可以使用带有效个人理由的 weak，side 不可以。
- none：不感兴趣、讨厌、疲惫、重复、冒犯、打扰、话题已结束或没有自然切入点。

open 有 strong 或具体个人补充的 weak 才能通过硬策略，side 仍只有 strong 才能通过。direct 也必须有真实意愿，直接地址不是强制命令。

### 2.3 信息级别

- noise：纯媒体、贴纸、刷屏或没有内容的流水账。
- reaction：简单附和、单独主题词或对上一句的短反应。
- substantive：具体事实、观点、问题、请求、经历、社交邀请或可以展开的内容。

短消息不必然是 noise；有效短问题、明确邀请和唯一指代的续问仍可进入判断。反过来，长句也不自动值得回复。

## 3. 运行时数据流

1. 事件入口执行平台重复过滤、黑名单、指令、欢迎消息、@全体和 @他人策略等硬边界。
2. 提取当前发送者、原文、平台目标信号、回复目标、媒体和戳一戳信息。平台 signal 是事实输入，不替模型决定社交意愿。
3. 处理图片、转发、表情和媒体描述；lazy 图片只在确实需要时继续识别。
4. Smart 模式由最早到达的消息担任 anchor，后续 follower 保留自己的发送者和顺序，并作为同一批上下文交给决策与正式回复。
5. DecisionAI 对每条仍可处理的消息做一次参与判断。
6. 结构化结果经过本地 normalizer 的硬规则校验。模型不能通过未知枚举、模糊目标或无效意愿绕过边界。
7. open/side 的通过结果进入按群维护的 in-memory participation throttle；direct/private 不消耗这个预算。
8. 通过后才调用 ReplyHandler 生成正式回复。正式回复使用 AstrBot 当前会话最终 Persona，只收到最小的参与 handoff，不收到决策模型的推理过程。
9. 未通过的当前消息和 Smart follower 可以保留为 observation-only 缓存，但 observation 不会成为下一次的“未回复问题”、不会制造 continuation、也不会提供图片候选。
10. 正式回复经过现有内容过滤、重复检测、保存和发送流程；该部分仍由 AstrBot/插件既有链路负责。

### 3.1 group_reply_scope

- ambient：普通群消息可以进入统一参与判断；明显纯媒体、低信息反应和只等待其他人的无正文消息可在模型前快速过滤。开放话题不是默认插话，但强烈的 Persona 连接或具体的低打扰个人补充仍可通过。
- addressed：未明确指向机器人的群消息在决策前静默。明确指向包括平台 @/戳/回复信号、文本中可靠的机器人称呼和触发关键词；这些信号只让消息进入候选，仍不保证模型返回 yes。


takeover_group_reply=true 时，插件会阻止被判定为静默的消息落入 AstrBot 默认兜底；DecisionAI 出错也静默，避免服务故障反而导致全量回复。关闭接管时，静默结果交还核心链路，这是显式兼容选择。

at_all_message_mode=skip_all、欢迎消息 skip_all 等现有显式强制配置是管理者覆盖，不代表普通 @ 行为。除这些明确的 force 分支外，@、关键词和点名都不能绕过参与决策。

## 4. DecisionAI 契约

DecisionAI 的 system prompt 是判断协议，不是正式回复提示。群聊版本要求一个 JSON 对象，字段为：

- reply：yes 或 no。
- target：bot、other、open 或 unclear。
- information：noise、reaction 或 substantive。
- continuation：yes 或 no。
- participation：direct、side、open 或 none。
- interest：strong、weak 或 none。
- reason_code：direct_request、shared_interest、personal_experience、emotional_reaction、continuation 或 none。
- confidence：high、medium 或 low。
- topic_key：长度受限的诊断标签，不用于生成回复目标。

normalize_decision_payload 是最终边界：

- target、participation、information、interest、reason_code、confidence 必须属于已知枚举。
- unclear、none、noise 和 reaction 按规则收敛为静默，只有有效 continuation 可以例外进入后续意愿判断。
- other 消息没有独立公共补充时必须静默。
- open 没有 strong interest，也没有具体 weak 个人补充，或 side 没有 strong interest 和有效个人理由时必须静默。
- reply=no 不能被后续代码重新解释为“可以回答”。

旧 provider 仍可能只返回 yes/no。纯旧格式继续被兼容为一个受限的 direct/open 决策；新代码不得把这个兼容层扩展成新的旁路。看起来像 JSON 但无法解析的响应按失败处理，不用宽松的 yes/no 前缀猜测。

### 4.1 发送者与上下文信任

当前消息发送者永远来自 event 元数据。历史消息、长期记忆、未回复缓存和 Smart follower 只能帮助理解，不能替当前消息指定对象，也不能把别人的话归给当前发送者。

平台没有检测到 @ 只表示平台 signal 缺失，不表示文本一定没有点名机器人；模型可以根据当前正文判断文本目标，但不能凭旧历史臆造目标。

## 5. 正式回复 handoff

DecisionAI 只把以下最小信息交给 ReplyHandler：允许的 participation 姿态和一个固定 reason_code 对应的短提示。handoff 用于提醒正式模型保持正确对象边界，不是新的行为人格。

正式模型不会收到：

- DecisionAI 的完整 JSON 诊断；
- 隐藏推理或 chain-of-thought；
- “模型应该怎样分析”的过程指令；
- 关键词命中本身作为回复理由。

正式模型会收到当前会话 Persona、格式化的消息上下文、现有 Smart/媒体必要提示，以及必要时的最小参与 handoff。side 和 open 的 handoff 明确要求只说自己的相关内容，不要替其他用户作答。

## 6. 缓存与 Smart 规则

观察缓存的用途是保留事件痕迹和避免消息完全消失，不是堆积“机器人欠下的回答”。缓存读取接口会排除 decision_state=observed：

- 不进入 active regular context；
- 不进入 window continuation context；
- 不触发下一条消息的自动续话；
- 不参与 lazy 图片候选合并。

Smart anchor 被判定静默时，anchor 和 follower 都转为 observation-only。Smart anchor 通过时，follower 作为背景保留原发送者、顺序和媒体信息，不改变主要回复对象。

## 7. 开放参与节流

节流只作用于没有明确指向机器人的 open 和 side 通过结果：

- ambient_reply_min_interval_seconds 默认 45 秒；
- ambient_reply_window_seconds 默认 600 秒；
- ambient_reply_max_per_window 默认 4 次；
- direct 和 private 回复不消耗该预算；
- 每个群独立计数，插件重载时清空内存状态；
- 任意值设为 0 可关闭对应限制。

节流是第二道社交保护，不替代 DecisionAI 的兴趣判断。它不能用来提高 open 消息的通过率，也不能让 direct 消息变成 open 消息。

## 8. 失败策略

| 场景 | 行为 |
| --- | --- |
| provider 超时或异常 | 返回 error/silent；接管群聊时静默，非接管时交回核心链路 |
| JSON 不完整或枚举未知 | 本地校验失败，静默 |
| 旧版纯 yes/no | 受限兼容；不扩展到结构化旁观参与 |
| 正式回复生成失败 | 复用现有 AstrBot 错误、保存和事件清理流程 |
| Smart follower 被更早 anchor 吸收 | 不独立生成回复，按现有 Smart 状态清理 |
| 观察缓存过期 | 丢弃，不制造新任务 |

失败和静默都必须避免把未决策消息伪装成机器人回复或把它变成下一轮的直接目标。

## 9. 保留的既有能力

本次参与重构不应删除以下能力：

- AstrBot 官方历史、会话人格解析和 reset 指令；
- lazy/eager 图片处理、图片描述缓存、转发解析和媒体清理；
- 黑名单、指令过滤、重复过滤、内容过滤和戳一戳；
- Smart anchor/follower 到达顺序与批次上下文；
- livingmemory 可选注入；
- ReplyHandler 的 provider request、工具集和第三方 Hook 兼容边界；
- 插件页配置接口与既有配置迁移。

ProbabilityManager 仍承担会话 key、生命周期和兼容 reset/status 接口，但旧的 initial/after-reply 概率值不再是群聊回复闸门。统一参与判断是当前群聊的唯一回复选择层。

## 10. 配置与调参

推荐起点：

- takeover_group_reply=true；
- group_reply_scope=ambient；
- decision_ai_include_persona=true；
- decision_ai_reply_tendency=persona；
- keyword_smart_mode 保留旧配置即可，关键词不会绕过判断；
- 节流使用 45/600/4 默认值。

如果仍然太吵，先提高 DecisionAI Persona 的边界或降低节流上限；不要通过增加关键词把所有消息送进必回路径。如果太安静，先确认 DecisionAI 是否拿到了当前 Persona、当前发送者和真实正文，再调整 active 倾向或缩短节流间隔；不要删除 open/side 的个人切入点硬门槛。

## 11. 验收清单

行为测试至少覆盖：

- 直接相关 @ 消息可以通过；直接无聊、重复、讨厌或已经结束的 @ 消息必须可以拒绝；
- 无 @ 的强 Persona 相关公开话题可以通过；普通可回答问题保持安静；
- @ 或回复其他用户的物流/只等待对方消息保持安静；有强个人经历的公共补充可以通过；
- noise、reaction、ambiguous 和未知枚举静默；
- malformed JSON 静默，旧 yes/no 仍兼容；
- handoff 不泄露推理；观察缓存不回流 active context；
- open/side 节流验证 interval、window、cap，direct bypass；
- Smart anchor/follower 不改变主要对象；
- provider timeout/error 在接管模式下 fail closed。

代码验证：

    /home/ubuntu/AstrBot/.venv/bin/ruff format .
    /home/ubuntu/AstrBot/.venv/bin/ruff check .
    /home/ubuntu/AstrBot/.venv/bin/python -m compileall -q .
    /home/ubuntu/AstrBot/.venv/bin/pytest -q
    git diff --check

维护者在修改参与规则时，应同时更新 utils/participation.py、DecisionAI 协议、主流程缓存语义、配置参考和本文件，并补一个针对行为变化的回归测试。
