"""
回复处理器模块（精简版）
负责调用AI生成回复

作者: Him666233
版本: V2.0.3-lite（refactor-lite 重构版）

重构要点（REFACTOR_DESIGN.md）：
- 删除 SYSTEM_REPLY_PROMPT（约100行系统行为指令）—— 这是群聊人格漂移的最大来源
- 回复请求的 system_prompt 只含人格（persona_manager.get_default_persona_v3()）
- prompt 只含纯上下文（历史 + 发送者标注），不注入任何行为指令/情绪/注意力文本
- 保留标记机制：on_llm_request 钩子（priority=-1）据此恢复完整 prompt，
  同时保留其他插件（emotionai/livingmemory 等）对请求的注入
- 保留短消息占位机制：event.request_llm() 的 prompt 传当前消息短文本，
  供向量检索类插件（livingmemory）召回；本插件钩子再换回完整上下文
"""

from astrbot.api.all import *
from astrbot.api.event import AstrMessageEvent
from .ai_error_formatter import format_ai_error
from astrbot.core.provider.entities import ProviderRequest

# 详细日志开关（与 main.py 同款方式：单独用 if 控制）
DEBUG_MODE: bool = False

# 标记键名，用于标识请求来自本插件
PLUGIN_REQUEST_MARKER = "_group_chat_plus_request"
# 存储插件自定义上下文的键名（供 on_llm_request 恢复）
PLUGIN_CUSTOM_CONTEXTS = "_group_chat_plus_contexts"
# 存储插件自定义系统提示词（人格）的键名
PLUGIN_CUSTOM_SYSTEM_PROMPT = "_group_chat_plus_system_prompt"
# 存储插件自定义完整 prompt 的键名（供 on_llm_request 恢复）
PLUGIN_CUSTOM_PROMPT = "_group_chat_plus_prompt"
# 存储图片 URL 列表的键名
PLUGIN_IMAGE_URLS = "_group_chat_plus_image_urls"
# 存储插件自身工具集（ToolSet）的键名，用于在 on_llm_request 钩子中合并
PLUGIN_FUNC_TOOL = "_group_chat_plus_func_tool"
# 存储当前用户消息原文（短字符串），供向量检索类插件（livingmemory）的记忆召回
PLUGIN_CURRENT_MESSAGE = "_group_chat_plus_current_message"


class ReplyHandler:
    """
    回复处理器（精简版）

    主要功能：
    1. 构建回复提示词（纯上下文，不含行为指令）
    2. 调用AI生成回复（event.request_llm）
    3. 检测是否已被其他插件处理
    """

    # 上下文与回复之间的最小分隔（仅输出格式引导，非人格/行为指令）
    PROMPT_ENDING = "\n\n---\n以上是消息上下文，请直接输出你的回复。"

    @staticmethod
    async def generate_reply(
        event: AstrMessageEvent,
        context: Context,
        formatted_message: str,
        extra_prompt: str,
        prompt_mode: str = "append",
        image_urls: list = None,
        audio_urls: list = None,
        include_sender_info: bool = True,
        include_timestamp: bool = True,
        history_messages: list = None,
        smart_batch_reply_hint: str = "",
    ) -> ProviderRequest:
        """
        生成AI回复（精简版）

        系统提示词只含人格设定，prompt 只含纯上下文（历史消息+发送者标注），
        不再注入任何插件行为指令。

        Args:
            event: 消息事件
            context: Context对象
            formatted_message: 格式化后的完整上下文（历史+当前消息，含发送者标注）
            extra_prompt: 用户自定义补充提示词（可覆盖或追加）
            prompt_mode: 提示词模式，append=拼接，override=覆盖
            image_urls: 图片URL列表（用于多模态AI）
            audio_urls: 音频URL列表
            include_sender_info: 是否包含发送者信息
            include_timestamp: 是否包含时间戳
            history_messages: 历史消息列表（保留参数以兼容调用，构建contexts用）
            smart_batch_reply_hint: Smart并发批次提示（可选追加消息说明）

        Returns:
            ProviderRequest对象
        """
        if image_urls is None:
            image_urls = []
        if audio_urls is None:
            audio_urls = []
        if history_messages is None:
            history_messages = []

        # 群聊历史中所有非 bot 消息均为 role="user"，LLM 无法从结构区分发送者，
        # 因此 contexts 保持为空，全部上下文以文本形式包含在 prompt 中
        # （每条消息均已标注 [时间] 昵称(ID): 内容）
        contexts = []

        try:
            # 发送者标注（"谁在说话"的必要信息，非行为指令）
            sender_emphasis = ""
            sender_id = event.get_sender_id()
            sender_name = event.get_sender_name()
            if include_sender_info:
                if sender_name:
                    sender_emphasis = (
                        f"[系统信息-当前对话对象] {sender_name}（ID:{sender_id}）"
                    )
                else:
                    sender_emphasis = (
                        f"[系统信息-当前对话对象] 用户ID:{sender_id}"
                    )

            smart_hint_text = (smart_batch_reply_hint or "").strip()

            if prompt_mode == "override" and extra_prompt and extra_prompt.strip():
                # 覆盖模式：用户自定义提示词完全替代默认内容
                full_prompt = (
                    extra_prompt.strip()
                    + "\n\n"
                    + sender_emphasis
                    + "\n"
                    + formatted_message
                    + (("\n" + smart_hint_text) if smart_hint_text else "")
                    + ReplyHandler.PROMPT_ENDING
                )
            else:
                # 拼接模式（默认）：纯上下文
                full_prompt = (
                    sender_emphasis
                    + "\n"
                    + formatted_message
                    + (("\n" + smart_hint_text) if smart_hint_text else "")
                    + ReplyHandler.PROMPT_ENDING
                )

            logger.info(
                f"正在调用AI生成回复（当前发送者：{sender_name or '未知'}，ID:{sender_id}）..."
            )

            # 获取工具管理器并保存为 ToolSet（兼容新旧版本 AstrBot）
            func_tools_mgr = context.get_llm_tool_manager()
            plugin_tool_set = None
            try:
                if hasattr(func_tools_mgr, "get_full_tool_set"):
                    plugin_tool_set = func_tools_mgr.get_full_tool_set()
                else:
                    plugin_tool_set = func_tools_mgr
            except Exception:
                pass

            # 获取人格作为 system_prompt（不再叠加任何插件指令）
            system_prompt = ""
            begin_dialogs_text = ""
            try:
                default_persona = await context.persona_manager.get_default_persona_v3(
                    event.unified_msg_origin
                )
                system_prompt = default_persona.get("prompt", "") or ""

                begin_dialogs = default_persona.get("_begin_dialogs_processed", [])
                if begin_dialogs:
                    dialog_parts = []
                    for dialog in begin_dialogs:
                        role = dialog.get("role", "user")
                        content = dialog.get("content", "")
                        if role == "user":
                            dialog_parts.append(f"用户: {content}")
                        elif role == "assistant":
                            dialog_parts.append(f"AI: {content}")
                    if dialog_parts:
                        begin_dialogs_text = (
                            "\n=== 预设对话 ===\n"
                            + "\n".join(dialog_parts)
                            + "\n\n"
                        )
                if DEBUG_MODE:
                    logger.info(
                        f"✅ 已获取人格配置（persona_manager），长度: {len(system_prompt)} 字符"
                    )
            except Exception as e:
                logger.warning(f"获取人格设定失败: {e}，使用空人格")

            if begin_dialogs_text:
                full_prompt += begin_dialogs_text

            # 标记请求来源，供 on_llm_request 钩子识别
            event.set_extra(PLUGIN_REQUEST_MARKER, True)
            event.set_extra(PLUGIN_CUSTOM_CONTEXTS, contexts)
            event.set_extra(PLUGIN_CUSTOM_SYSTEM_PROMPT, system_prompt)
            event.set_extra(PLUGIN_CUSTOM_PROMPT, full_prompt)
            event.set_extra(PLUGIN_IMAGE_URLS, image_urls)
            event.set_extra("_plugin_audio_urls", audio_urls)
            event.set_extra(PLUGIN_FUNC_TOOL, plugin_tool_set)

            # 短消息占位：供向量检索类插件（livingmemory）作为召回查询词，
            # 本插件 on_llm_request 钩子（priority=-1）会把 req.prompt 换回完整上下文
            current_message_for_retrieval = event.get_message_str() or ""
            # 单独无信息@消息时 get_message_str() 返回 ""，用占位符避免空 prompt
            prompt_for_request = current_message_for_retrieval or "[空消息]"
            event.set_extra(PLUGIN_CURRENT_MESSAGE, current_message_for_retrieval)

            if DEBUG_MODE:
                logger.info("🔧 已设置插件标记，将通过 event.request_llm() 调用 AI")
                logger.info(f"  - system_prompt 长度: {len(system_prompt)}")
                logger.info(f"  - full_prompt 长度: {len(full_prompt)}")
                logger.info(f"  - image_urls 数量: {len(image_urls)}")
                logger.info(
                    f"  - 向量检索用短消息长度: {len(current_message_for_retrieval)}"
                )

            return event.request_llm(
                prompt=prompt_for_request,
                func_tool_manager=func_tools_mgr,
                tool_set=plugin_tool_set,
                session_id=event.session_id,
                image_urls=image_urls,
                audio_urls=audio_urls,
                contexts=contexts,
                system_prompt=system_prompt,
            )

        except Exception as e:
            logger.error(f"{format_ai_error(e, '生成AI回复')}")
            return event.plain_result(
                f"生成回复时发生错误: {format_ai_error(e, '生成AI回复')}"
            )

    @staticmethod
    def check_if_already_replied(event: AstrMessageEvent) -> bool:
        """
        检查消息是否已被其他插件处理

        通过 _has_send_oper 标记判断，该标记在 event.send() 被调用后永久置为 True，
        不受框架 clear_result() 影响。

        Args:
            event: 消息事件

        Returns:
            True=已有回复，False=尚未回复
        """
        return getattr(event, "_has_send_oper", False)
