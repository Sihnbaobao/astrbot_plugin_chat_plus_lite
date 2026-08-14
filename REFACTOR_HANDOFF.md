# 重构交接指令（新会话请完整阅读本文件）

> 本文件由上一会话调查完成后生成。新会话 AI 请以此文件为唯一上下文起点，直接开始重构工作。

## 一、任务背景

用户在使用 AstrBot 群聊自动回复插件 `astrbot_plugin_group_chat_plus`（作者 Him666233，V1.2.3.hotfix.2），发现 **bot 在群聊中的回复与私聊明显不同，人格表现被改变**。用户确认：私聊时插件不生效（`enable_private_chat` 默认 False），bot 走 AstrBot 默认链路，表现正常；群聊时插件完全接管回复生成，注入大量内容导致人格漂移。

用户决定**重构该插件**，核心诉求：

> **插件只决定"要不要回复"，不决定"说什么"。回复内容完全交给 AstrBot 原始链路（用户设定的人格 + 平台默认 prompt）。**

## 二、已确认的决策（用户拍板，不要更改）

### 保留
1. 概率筛选（非@消息按概率回复）
2. 关键词触发（特定词必回）
3. @机器人必回
4. AI 读空气判断（decision_ai，判断是否回复）
5. 图片识别 / 转发消息解析
6. 黑名单（用户/关键词）
7. 时间戳 / 发送者标注
8. **Web 管理面板**（用户明确要求保留）
9. **戳一戳**（用户明确要求保留）
10. **Smart 并发**（用户明确要求保留）

### 删除（影响人格或复杂机制）
- 私聊全套（`private_chat/` 目录、`on_private_message`、所有 `private_*` 配置）
- 情绪系统（MoodTracker + mood_hint 注入）
- 超长行为指令（`SYSTEM_REPLY_PROMPT`，约 100 行，**大幅精简或移除**）
- 注意力机制（AttentionManager 及其全部调用链）
- 主动对话（proactive_chat_manager，含吐槽系统）
- 等待窗口（group_wait_window）
- 对话疲劳（conversation_fatigue）
- 错字生成、打字模拟、人性化模式
- 消息质量评分、动态概率的复杂部分（可选保留简单时间段概率）
- 记忆注入（livingmemory 集成，用户未确认，默认删除或保留为可选）

### 重构原则
- 精简重构：目标代码量从 1.4 万行降到几千行
- 保持插件行为"透明"：不注入任何行为指令、情绪、注意力文本到 system_prompt / prompt

## 三、仓库与源码位置

- **插件仓库**：`D:\GithubProjects\astrbot_plugin_group_chat_plus`
  - `main.py`：707KB，约 1.4 万行，120 个方法（主体）
  - `utils/`：群聊功能模块（30+ 文件）
  - `private_chat/`：私聊模块（**待删除**）
  - `web/`：Web 面板（**待保留**）
  - `_conf_schema.json`：349 个配置项（重构后应大幅精简）
  - `metadata.yaml`、`requirements.txt`、`README.md`
- **AstrBot 源码（API 参考，已克隆）**：`D:\GithubProjects\astrbot-src`（官方仓库 Soulter/AstrBot，浅克隆）
- 用户实际运行的 AstrBot 部署在**手机上**，电脑上无法读取其配置；重构不要依赖读取用户配置

## 四、前期调查结论（已完成，直接采信）

### 4.1 人格漂移的根源（按影响程度排序）

1. **`SYSTEM_REPLY_PROMPT`（最大影响源）**——`utils/reply_handler.py` 60~167 行：
   - 约 100 行系统行为指令，每次群聊回复必注入，含【严禁元叙述】【严禁重复】【回复身份】等强制约束
   - 结果：群聊里 bot 说话更短、更直接、少解释性语言，与私聊自由风格差异大
   - 该指令通过 `PLUGIN_CUSTOM_STATIC_INSTRUCTIONS` extra 存储，在 `on_llm_request`（main.py 10976~10986 附近）追加到 `req.system_prompt`

2. **情绪系统（mood_hint）**——默认开启（`enable_mood_system` 默认 True，main.py 1956）：
   - `MoodTracker`（utils/mood_tracker.py）按关键词匹配情绪（哈哈→开心、？→疑惑、555→难过、...→无语）
   - 情绪非"平静"时，main.py 7771~7782 生成 `[系统信息-情绪参考: X（在你的人格基调上自然体现，不要偏离人格设定）]`
   - 在 `on_llm_request`（main.py 11070~11076）追加到 system_prompt
   - 隐患：情绪按整个群共享、关键词极宽泛，极易误判，群聊表现飘忽

3. **注意力机制**——默认关闭（`enable_attention_mechanism` 默认 False）：
   - 只调整回复概率，不注入 prompt 文本；但代码极其复杂（utils/attention_manager.py 400+ 行匹配），整体删除

4. **其他注入**：sender_emphasis（reply_handler 229~242）、对话疲劳提示（300~313）、pending cooldown 提示（251~264）、主动对话标记 `[🎯主动发起新话题]` 等

### 4.2 插件关键流程（已定位）

```
on_group_message (main.py 4057)
  → _process_message (main.py 9345)
    → _check_probability_before_processing (main.py 5424)
    → _check_ai_decision (main.py 6209，读空气AI判断)
    → _process_message_content (main.py 6667，图片/转发解析)
    → _generate_and_send_reply (main.py 7638)
      → ReplyHandler.generate_reply (utils/reply_handler.py 173)
        → 构建 full_prompt（历史+上下文+发送者标注+行为指令）
        → 从 persona_manager 获取人格作为 system_prompt
        → event.request_llm() 调用
on_llm_request (main.py 10675)  ← 插件标记请求，恢复自定义内容并追加注入
```

- 入口：`on_group_message`（4057），`on_private_message`（3953，**待删除**）
- 指令过滤：`command_filter_handler`（3880）
- 概率判断：`_check_probability`（14248）
- Smart 并发：`_maybe_intercept_for_wait_window`（8859）、`_run_group_wait_window`（9240）、`_should_enable_smart_batch_hint`（5908）
- 戳一戳：`_check_poke_message`（13930）、`_do_poke_after_reply`（8518）
- Web 面板：`web/server.py`，main.py 中 `_get_auth_token`（3846）、JWT（4344）

### 4.3 AstrBot API 关键事实（来自 astrbot-src，已核实）

1. **`event.request_llm()`**（`astrbot-src/astrbot/core/platform/astr_message_event.py` 420~474）：
   ```python
   event.request_llm(
       prompt=str,          # 提示词（插件传短消息即可，钩子会换回完整prompt）
       system_prompt=str,   # 系统提示词（人格）
       contexts=list,       # OpenAI 格式上下文
       image_urls=list, audio_urls=list,
       tool_set=ToolSet,    # 新版用 tool_set
       func_tool_manager=,  # 旧版兼容参数（<=4.13）
       conversation=Conversation,
   ) -> ProviderRequest
   ```
   返回 ProviderRequest，插件需 `return` 或 `yield` 给框架处理。

2. **ProviderRequest 字段**（`astrbot-src/astrbot/core/provider/entities.py` 90~117）：`prompt / session_id / image_urls / audio_urls / extra_user_content_parts / func_tool / contexts / system_prompt / conversation / model`

3. **框架默认链路**：`build_main_agent`（`astrbot-src/astrbot/core/astr_main_agent.py` 1412）会：
   - 若 `req.conversation` 存在，用其 history 作为 contexts
   - 调用 `_decorate_llm_request`（该文件 1016）注入人格 + 平台 LTM
   - 追加工具提示（TOOL_CALL_PROMPT）到 system_prompt
   - 即：**只要插件构造好 ProviderRequest 交给框架，人格会自动注入**，插件无需手动塞行为指令

4. **on_llm_request 钩子**：框架在 `internal.py` 269 行 `call_event_hook(event, EventType.OnLLMRequestEvent, req)`，插件钩子（priority 决定顺序）可修改 req 后 return True 表示已接管。其他插件（emotionai 等）会在此注入内容，重构后插件自己的 on_llm_request 应只做"恢复插件请求内容 + 保留第三方注入"，**不再追加行为指令/情绪**。

5. **人格获取**：`context.persona_manager.get_default_persona_v3(event.unified_msg_origin)` 返回 dict，`["prompt"]` 是人格文本（reply_handler.py 417~421 有用法示例）。

6. **事件常用方法**：`get_message_str() / get_sender_id() / get_sender_name() / get_group_id() / get_self_id() / get_platform_name() / get_platform_id() / is_private_chat() / get_extra(key, default) / set_extra(key, value) / plain_result(text) / request_llm(...)`。注意 `event.get_message_str()` 对"单独@无内容"消息返回 ""，需要占位符。

## 五、重构方案要点（新会话的执行大纲）

### 阶段 1：设计（先做，别急着写码）
1. 通读 `_process_message`（9345~9898）和 `_generate_and_send_reply`（7638~8518）的完整流程，画出保留功能的调用关系
2. 阅读 `utils/reply_handler.py` 全文（600 行左右），确定精简后的回复构建逻辑
3. 阅读 `utils/decision_ai.py`（读空气AI，短文件）确认判断链路
4. 阅读 `web/server.py` 和 main.py 中 Web 相关部分，确认 Web 面板依赖哪些配置
5. 阅读 Smart 并发相关（8859~9345）和戳一戳相关（8518~8836、13930~14104），确认保留逻辑

### 阶段 2：架构
推荐模块划分（新目录结构）：
```
astrbot_plugin_group_chat_plus/
├── main.py                 # 精简后主入口（目标 <3000 行）
├── metadata.yaml           # 更新描述
├── _conf_schema.json       # 精简配置（目标 <100 项）
├── requirements.txt
├── utils/
│   ├── reply_handler.py    # 精简：只构建最小上下文，不再注入行为指令
│   ├── decision_ai.py      # 读空气AI判断（保留）
│   ├── probability_manager.py / keyword_checker.py / blacklist 等触发判断
│   ├── message_processor.py / forward_message_parser.py / image_handler.py（图片转发解析，保留）
│   ├── smart_concurrent_manager.py（保留）
│   ├── poke 相关（保留）
│   └── ...（删除 mood_tracker / attention_manager / proactive_chat_manager / typo / typing / humanize / fatigue / wait_window 等）
├── web/                    # Web 面板（保留，精简配置）
└── tests/                  # 回归测试
```

### 阶段 3：实现要点
1. **回复构建（最关键）**：重构后 `generate_reply` 应只做：
   - 获取人格：`persona_manager.get_default_persona_v3()` → system_prompt（**不再叠加任何插件指令**）
   - 构建纯上下文 prompt：历史消息 + 发送者标注（`[时间] 昵称(ID): 消息`），不含行为指令
   - `event.request_llm()` 调用，标记 PLUGIN_REQUEST_MARKER
   - on_llm_request 钩子只恢复 req.prompt/contexts/system_prompt，**删除**：mood_hint 追加、SYSTEM_REPLY_PROMPT 追加、工具提醒追加（或保留为可配置项）
2. **读空气判断**：保留 decision_ai，但确认其调用时用的 prompt 是否干净（只判断"要不要回"）
3. **删除工作**：删 private_chat/ 目录；删 main.py 中私聊入口（3953~4055）、私聊配置、情绪（7771~7782、11070~11076）、注意力调用点（5687/6115/6187/6474/6618/7771/8230/10502/14288 等）、主动对话、等待窗口、疲劳等
4. **配置精简**：_conf_schema.json 从 349 项精简，删除私聊/情绪/注意力/主动对话/拟人化等所有相关项；main.py `__init__` 中同步删除对应 config.get
5. **Web 面板**：检查 web/server.py 依赖的配置项，保留必要项
6. **回归自测**：本机无 AstrBot 环境，用 `python -m py_compile` 做语法检查；写少量单元测试（utils 中纯逻辑模块）；README 中说明部署方式

### 阶段 4：验证清单
- [ ] 语法检查全部通过
- [ ] 无残留 import：mood/attention/proactive/private/typo/typing/humanize/fatigue/wait_window
- [ ] main.py 方法数从 120 降到 60 以内
- [ ] 配置项从 349 降到 100 以内
- [ ] system_prompt 只含人格 + 平台内容（用 on_llm_request 的 debug 日志验证）
- [ ] 保留功能清单逐项核对（概率/关键词/@/读空气/图片/转发/黑名单/Web/戳一戳/Smart）

## 六、重要提醒

1. **这是用户的真实生产插件**，重构要保守、可回退：建议在 git 分支 `refactor-lite` 上工作，保留 master 原版
2. **不要破坏 AstrBot 兼容**：`astrbot_version: ">=4.11.0"`，注意新旧 API 兼容写法（func_tool_manager vs tool_set 已示范）
3. **重构后群聊与私聊的人格一致性是验收标准**：群聊里 AI 看到的指令应与私聊几乎相同，只多"谁在说话"的必要信息
4. 重构完成后，交付说明文档（README 更新 + 迁移指南：哪些配置项被删除，用户需在新版里重新配置什么）
5. 本机环境：Windows，无 AstrBot 运行时，无法真机测试；但 `astrbot-src` 源码可用来核对 API 签名
