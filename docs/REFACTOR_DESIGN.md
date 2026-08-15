# 精简重构设计（refactor-lite）

> 依据 REFACTOR_HANDOFF.md 与用户补充确认（livingmemory 记忆注入保留）。
> 目标：main.py 从 14493 行降到 <3000 行；_conf_schema.json 从 349 项降到 <100 项；
> 群聊与私聊的 LLM 可见指令一致——只多"谁在说话"的必要信息。

## 一、保留 / 删除清单

### 保留（功能 + 配置）
1. 概率筛选（ProbabilityManager）
2. 关键词触发（KeywordChecker）
3. @机器人必回（is_at_message 跳过滤波）
4. AI 读空气判断（DecisionAI，保留 SYSTEM_DECISION_PROMPT，清理废弃钩子参数）
5. 图片识别（ImageHandler / ImageDescriptionCache / PlatformLTMHelper）+ 转发消息解析（ForwardMessageParser）
6. 黑名单（用户 ID + 关键词）
7. 时间戳/发送者标注（MessageProcessor.add_metadata_* / ContextManager.format_context_for_ai）
8. Web 面板（web/ 全目录，修补对已删模块的引用）
9. 戳一戳（回复后戳 / 反戳 / 戳过追踪 / 白名单）
10. Smart 并发（SmartConcurrentManager，含批次提示）
11. livingmemory 记忆注入（MemoryInjector）——用户拍板保留
12. 附带保留（小且无关人格）：消息缓存（MessageCacheManager，去除 ProactiveChatManager 依赖）、
    @全体成员过滤、@他人过滤、指令过滤、去重过滤、内容过滤（输出/保存）、
    入群欢迎解析、表情包标记、并发等待刷新、gcp 系列重置指令、冷群转正

### 删除（文件/模块）
- private_chat/ 整个目录
- utils/: attention_manager、mood_tracker、proactive_chat_manager、typo_generator、
  typing_simulator、humanize_mode、frequency_adjuster、message_quality_scorer、
  reply_density_manager、cooldown_manager、time_period_manager、message_cache_manager 保留但去依赖
- main.py: 私聊入口、情绪、注意力（含冷却/pending）、主动对话、等待窗口、疲劳、
  错字/打字模拟/拟人、质量评分/密度、频率调整、时间段动态概率、工具提醒文本注入、
  第三方差分重写（SystemPromptRewriter 机制 → 简化前缀/后缀保留）、逐插件追踪补丁（模块级 117~1036 行）

### 删除（配置键，不删 schema 中的 web 安全键）
private_*（约 18 键）、enable_attention_mechanism 及 attention_*/cooldown_*/pending_cooldown_*、
enable_mood_system 及 mood_*/negation_*、enable_conversation_fatigue 及 fatigue_*、
enable_humanize_mode 及 humanize_*、enable_typo_generator 及 typo_*、enable_typing_simulator 及 typing_*、
enable_frequency_adjuster 及 frequency_*、enable_proactive_chat 及 proactive_*/score_*/complaint_*/interaction_score_*、
enable_group_wait_window 及 group_wait_window_*、enable_dynamic_reply_probability 及 reply_time_*、
enable_dynamic_proactive_probability 及 proactive_time_*、enable_reply_density_limit 及 reply_density_*、
enable_message_quality_scoring 及 message_quality_*、single_at_message_reply_link_*、
enable_tools_reminder / tools_reminder_persona_filter、enable_smart_batch_reply_hint（并入 Smart 主开关？——保留为 6 键组）、
enable_emoji_filter 组（并入图片处理，默认开启语义）、reply_timeout_warning_threshold / reply_generation_timeout_warning（并入 debug 简单日志）

## 二、回复构建（核心变更）

`ReplyHandler.generate_reply` 重构后只做：
1. 人格：`persona_manager.get_default_persona_v3(event.unified_msg_origin)` → system_prompt（原样，不叠加任何插件指令）
2. 上下文：formatted_message（历史 + [时间] 昵称(ID): 消息，发送者标注），不加 SYSTEM_REPLY_PROMPT
3. 可保留最小结尾："请直接输出你的回复"（或完全去掉，仅保留上下文文本）——决定：去掉 SYSTEM_REPLY_PROMPT，
   保留 `\n\n---\n以上是消息上下文，请直接输出你的回复` 一句引导（非人格指令，仅输出形式）
4. event.request_llm(prompt=短消息占位, system_prompt=人格, contexts=[], image_urls, tool_set)
5. 标记 PLUGIN_REQUEST_MARKER 等 extras

`on_llm_request` 重构后只做：
- 检测标记；无标记直接返回
- req.prompt = 前缀(如 prompt_prefix) + 完整 full_prompt + 后缀(第三方注入)（用短消息在快照中 partition）
- req.contexts = 插件 contexts([]) + 第三方追加的 contexts（快照差分，简化版）
- req.system_prompt 不动（人格已在请求时传入，框架/第三方只追加，无需重写）
- 合并图片/音频 URL；合并插件工具集到 req.func_tool（保留框架工具）；注入 Skills 提示词（框架跳过 conversation 路径）
- 清理 extras
- **不再注入**：SYSTEM_REPLY_PROMPT、mood_hint、工具提醒文本、系统指令 extra

## 三、决策 AI（读空气）

`DecisionAI.should_reply` 参数精简：去掉 humanize/time_period/fatigue/reply_density/pending_cooldown/proactive 相关，
保留：provider_id/extra_prompt/timeout/prompt_mode/include_persona/persona_name/image_urls/keyword 标记/推理协议。
SYSTEM_DECISION_PROMPT 保留但删除引用已删功能的段落（判断记录/疲劳/时间活跃度/兴趣话题）。

## 四、main.py 新结构（目标 <3000 行）

- 模块头/导入（去逐插件追踪模块级代码）
- 常量（marker 键等）
- ChatPlus:
  - __init__（~100 键集中提取 + 8 个状态 + 管理器）
  - initialize/terminate/on_platform_loaded（Web 面板启动、Smart 参数同步）
  - restart_core/_get_auth_token/_generate_jwt_token
  - command_filter_handler / gcp_reset / gcp_reset_here / gcp_clear_image_cache
  - on_group_message（空消息过滤/去重/黑名单/欢迎/转发/@过滤/戳一戳→_process_message）
  - _process_message（初始检查→触发器→戳一戳→@提及→概率→表情→内容处理→Smart→决策AI→回复→戳）
  - _check_probability_before_processing / _check_probability（去注意力/疲劳/密度/质量/拟人）
  - _check_ai_decision（去 humanize/fatigue 注入，保留记忆 pre_decision 注入）
  - _process_message_content（图片/媒体/表情/元数据/历史/上下文）
  - _generate_and_send_reply（记忆 post_decision 注入→ReplyHandler→去重→yield→概率提升→戳一戳）
  - _do_poke_after_reply / _maybe_reverse_poke_on_poke / poke trace 助手
  - on_llm_request（简化恢复）/ on_llm_response / on_decorating_result（去错字/打字）/ after_message_sent（历史保存）
  - 辅助：_is_enabled/_is_user_blacklisted/_is_command_message/_is_at_all_message/
    _should_ignore_at_all/_should_ignore_at_others/_detect_at_from_raw_message/_check_mention_others/
    _resolve_group_member_name/_safe_sender_display/_check_poke_message/_build_source_event_id/
    _get_processing_id/_ensure_arrival_metadata/_get_message_id/_next_group_message_seq/
    _refresh_history_after_wait/_build_interleaved_tool_reply/_finalize_bot_reply_save/
    _save_user_messages_on_duplicate_block/_save_poke_assistant_event/_save_platform_descriptions_to_cache/
    _try_cache_fallback_for_images/_should_enable_smart_batch_hint/_summarize_smart_batch_messages/_build_smart_batch_reply_hint

## 五、实施顺序

1. 删除 private_chat/ 与 11 个废弃 utils 模块
2. 重写 utils/reply_handler.py（精简）
3. 精简 utils/decision_ai.py
4. 修补 utils/message_cache_manager.py（内联 filter_expired_cached_messages）
5. 重写 utils/__init__.py
6. 重写 main.py
7. 重写 _conf_schema.json + metadata.yaml
8. 修补 web/server.py（去 Attention/Cooldown/Proactive/ReplyDensity 引用）
9. 验证：py_compile、grep 残留、方法数、配置项数、单元测试
10. README 更新（迁移指南）

## 六、验收标准（来自交接文档）

- [x] py_compile 全通过
- [x] 无 mood/attention/proactive/private/typo/typing/humanize/fatigue/wait_window 残留 import
- [x] main.py 方法数 58（< 60）
- [x] 配置项 94（< 100）
- [x] 群聊 system_prompt 只含人格 + 平台内容（不含插件行为指令，单元测试断言）
- [x] 保留功能逐项核对

## 七、版本管理与发布规则（强制）

> ⚠️ **每次代码变更（修复/功能/文档）提交前，必须同步更新版本号**，否则拒绝提交。

1. **版本号三处必须同步更新**：
   - metadata.yaml 的 version 字段（AstrBot 安装/展示用）
   - main.py 的 @register(...) 装饰器版本参数（AstrBot 运行时注册用）
   - CHANGELOG.md 顶部新增对应版本条目（记录变更内容）
2. **版本号规则**（V主.次.补丁-lite）：
   - 修复 bug / 兼容性问题 → 补丁号 +1（如 V2.3.0-lite）
   - 新增功能 → 次版本号 +1（如 V2.3.0-lite）
   - 破坏性重构 / 重大变更 → 主版本号 +1（如 V3.0.0-lite）
3. **发布流程**：
   - 修改代码 → 本地验证（py_compile + pytest）→ 更新版本号三处 → 更新 CHANGELOG → 提交推送
   - 每次推送后，用户侧在 AstrBot 中更新插件即可获得新版本
4. **历史教训**（真实事故记录）：
   - V2.0.0-lite 发布后连续两次修复（EventMessageType 兼容、配置面板提供商选择器）均未升版本号，
     导致用户无法从版本号判断自己运行的是否为最新代码。自 V2.3.0-lite 起强制执行本规则。
