"""
指令 / 重置域（CommandMixin）。

从主插件类拆出的独立功能域：指令过滤器、gcp_* 管理指令、会话/插件重置。
装饰器（@filter.command / @filter.event_message_type）由 AstrBot 以
functools.partial(方法, 实例) 显式绑定，故迁移到 mixin 后注册与分发不受影响。
"""

import time

from astrbot.api import logger
from astrbot.api.all import *  # noqa: F403  （与 main.py 保持一致）
from astrbot.api.event import filter


class CommandMixin:
        async def command_filter_handler(self, event: AstrMessageEvent):
            """
            指令过滤处理器（超高优先级）

            检测到指令消息时标记该消息，让本插件的其他处理器跳过。
            """
            try:
                if self.enable_group_chat and not event.is_private_chat():
                    if not self._is_enabled(event):
                        return

                    current_time = time.time()
                    expired_ids = [
                        mid
                        for mid, timestamp in self.command_messages.items()
                        if current_time - timestamp > 10
                    ]
                    for mid in expired_ids:
                        del self.command_messages[mid]

                    if self._is_command_message(event):
                        msg_id = self._get_processing_id(event)
                        self.command_messages[msg_id] = current_time
                        return
            except Exception as e:
                logger.error(f"[指令过滤] 处理消息时发生错误: {e}", exc_info=True)
                return

        def _is_command_message(self, event: AstrMessageEvent) -> bool:
            """
            检测消息是否为指令消息（根据配置的指令前缀和完整指令列表）

            支持格式：
            1. /command 或 !command 等（直接以前缀开头）
            2. @机器人 /command（@ 机器人后跟指令）
            3. 完整指令字符串检测（全字符串匹配，去除@组件和空格）

            Returns:
                True=是指令消息（应跳过），False=不是指令消息
            """
            enable_filter = self.enable_command_filter
            if not enable_filter:
                return False

            command_prefixes = self.command_prefixes
            enable_full_cmd = self.enable_full_command_detection
            full_command_list = self.full_command_list
            enable_prefix_match = self.enable_command_prefix_match
            prefix_match_list = self.command_prefix_match_list

            has_prefix_filter = bool(command_prefixes)
            has_full_cmd = enable_full_cmd and bool(full_command_list)
            has_prefix_match = enable_prefix_match and bool(prefix_match_list)

            if not has_prefix_filter and not has_full_cmd and not has_prefix_match:
                return False

            try:
                original_messages = event.message_obj.message
                if not original_messages:
                    return False

                # 第一步：检查指令前缀
                if command_prefixes:
                    for component in original_messages:
                        if isinstance(component, Plain):
                            first_text = self._coerce_component_text(component.text).strip()
                            for prefix in command_prefixes:
                                if prefix and first_text.startswith(prefix):
                                    return True
                            break

                # 第二步：检查完整指令字符串
                if enable_full_cmd and full_command_list:
                    plain_texts = []
                    for component in original_messages:
                        if isinstance(component, Plain):
                            plain_texts.append(self._coerce_component_text(component.text))
                    combined_text = "".join(plain_texts)
                    cleaned_text = "".join(combined_text.split())
                    for cmd in full_command_list:
                        if not cmd:
                            continue
                        cleaned_cmd = "".join(str(cmd).split())
                        if cleaned_text == cleaned_cmd:
                            return True

                # 第三步：检查指令前缀匹配（避免误匹配如 'add' 匹配 'address'）
                if has_prefix_match:
                    plain_texts = []
                    for component in original_messages:
                        if isinstance(component, Plain):
                            plain_texts.append(self._coerce_component_text(component.text))
                    combined_text = "".join(plain_texts)
                    stripped_text = combined_text.lstrip()
                    for cmd in prefix_match_list:
                        if not cmd:
                            continue
                        cmd_str = str(cmd).strip()
                        if not cmd_str:
                            continue
                        if stripped_text.startswith(cmd_str):
                            remaining = stripped_text[len(cmd_str):]
                            if not remaining or remaining[0].isspace():
                                return True

                return False
            except Exception as e:
                logger.error(f"[指令检测] 发生错误: {e}", exc_info=True)
                return False

        @filter.command("gcp_reset")
        async def gcp_reset(self, event: AstrMessageEvent):
            """全局重置插件：清空所有会话的插件缓存与数据文件，设置历史截止点，然后重启 AstrBot。"""
            try:
                if not self.enable_group_chat or event.is_private_chat():
                    return
                if not self._is_enabled(event):
                    return
                if not hasattr(event, "message_obj") or not hasattr(event.message_obj, "message"):
                    return
                components = event.message_obj.message
                if not components:
                    return
                if not all(isinstance(c, (Plain, At, AtAll)) for c in components):
                    return
                whitelist = self.plugin_gcp_reset_allowed_user_ids
                allow_all = not whitelist or len(whitelist) == 0
                sender_id = str(event.get_sender_id())
                allowed = allow_all or (str(sender_id) in {str(x) for x in whitelist})
                if not allowed:
                    logger.info("【会话重置】用户 %s 未在白名单中，重置指令被忽略", sender_id)
                    return
                try:
                    await self._reset_plugin_data_and_reload()
                    try:
                        platform_name = event.get_platform_name()
                        chat_id = event.get_group_id()
                        session_str = f"{platform_name}:GroupMessage:{chat_id}"
                        notice = (
                            "【Group Chat Plus】插件全局重置：成功\n"
                            "\n"
                            "已执行以下操作：\n"
                            "1. 清空所有会话的插件缓存（待处理消息、回复记录、概率等状态）\n"
                            "2. 设置历史截止点（插件将忽略重置前的平台聊天记录）\n"
                            "\n"
                            "注意：本操作不会删除平台官方的对话历史和聊天记录，如需清除请使用平台的 /reset 指令。\n"
                            "即将重启 AstrBot..."
                        )
                        if self.is_desktop_mode:
                            notice += (
                                "\n\n⚠️ 桌面端提示：重启由 Tauri 托管进程管理，如重启后无响应，"
                                "请通过桌面端托盘菜单手动重启后端。"
                            )
                        yield event.plain_result(f"{notice}")
                        logger.info(f"{session_str}: {notice}")

                        self.config["platform_id"] = event.get_platform_id()
                        self.config["restart_umo"] = event.unified_msg_origin
                        self.config["restart_start_ts"] = time.time()
                        self.config.save_config()
                        try:
                            await self.restart_core()
                        except Exception as e:
                            yield event.plain_result(f"重启失败：{e}")
                            logger.error(f"重启失败：{e}")
                    except Exception:
                        pass
                except Exception:
                    try:
                        notice = "【Group Chat Plus】插件全局重置：失败\n执行重置时发生内部错误，请查看日志。"
                        yield event.plain_result(f"{notice}")
                        logger.info(f"{notice}")
                    except Exception:
                        pass
                return
            except Exception:
                return

        @filter.command("gcp_reset_here")
        async def gcp_reset_here(self, event: AstrMessageEvent):
            """重置当前会话：清空本会话的插件缓存，设置历史截止点，然后重启 AstrBot。"""
            try:
                if not self.enable_group_chat or event.is_private_chat():
                    return
                if not self._is_enabled(event):
                    return
                if not hasattr(event, "message_obj") or not hasattr(event.message_obj, "message"):
                    return
                components = event.message_obj.message
                if not components:
                    return
                if not all(isinstance(c, (Plain, At, AtAll)) for c in components):
                    return
                whitelist = self.plugin_gcp_reset_here_allowed_user_ids
                allow_all = not whitelist or len(whitelist) == 0
                sender_id = str(event.get_sender_id())
                allowed = allow_all or (str(sender_id) in {str(x) for x in whitelist})
                if not allowed:
                    logger.info("【会话重置】用户 %s 未在白名单中，重置指令被忽略", sender_id)
                    return
                try:
                    await self._reset_session_data(event)
                    try:
                        platform_name = event.get_platform_name()
                        chat_id = event.get_group_id()
                        session_str = f"{platform_name}:GroupMessage:{chat_id}"
                        notice = (
                            "【Group Chat Plus】当前会话重置：成功\n"
                            "\n"
                            "已执行以下操作：\n"
                            "1. 清空本会话的插件缓存（待处理消息、回复记录、概率等状态）\n"
                            "2. 设置历史截止点（插件将忽略重置前的平台聊天记录）\n"
                            "\n"
                            "注意：本操作不会删除平台官方的对话历史和聊天记录，如需清除请使用平台的 /reset 指令。\n"
                            "即将重启 AstrBot..."
                        )
                        if self.is_desktop_mode:
                            notice += (
                                "\n\n⚠️ 桌面端提示：重启由 Tauri 托管进程管理，如重启后无响应，"
                                "请通过桌面端托盘菜单手动重启后端。"
                            )
                        yield event.plain_result(f"{notice}")
                        logger.info(f"{session_str}: {notice}")

                        self.config["platform_id"] = event.get_platform_id()
                        self.config["restart_umo"] = event.unified_msg_origin
                        self.config["restart_start_ts"] = time.time()
                        self.config.save_config()
                        try:
                            await self.restart_core()
                        except Exception as e:
                            yield event.plain_result(f"重启失败：{e}")
                            logger.error(f"重启失败：{e}")
                    except Exception:
                        pass
                except Exception:
                    try:
                        notice = "【Group Chat Plus】当前会话重置：失败\n执行重置时发生内部错误，请查看日志。"
                        yield event.plain_result(f"{notice}")
                        logger.info(f"{notice}")
                    except Exception:
                        pass
                return
            except Exception:
                return

        @filter.command("gcp_clear_image_cache")
        async def gcp_clear_image_cache(self, event: AstrMessageEvent):
            """清除本地图片描述缓存并重启AstrBot。"""
            try:
                if event.is_private_chat():
                    return
                if not hasattr(event, "message_obj") or not hasattr(event.message_obj, "message"):
                    return
                components = event.message_obj.message
                if not components:
                    return
                if not all(isinstance(c, (Plain, At, AtAll)) for c in components):
                    return
                whitelist = self.gcp_clear_image_cache_allowed_user_ids
                allow_all = not whitelist or len(whitelist) == 0
                sender_id = str(event.get_sender_id())
                allowed = allow_all or (str(sender_id) in {str(x) for x in whitelist})
                if not allowed:
                    logger.info("【图片缓存清除】用户 %s 未在白名单中，指令被忽略", sender_id)
                    return
                try:
                    cleared = False
                    if self.image_description_cache:
                        cleared = self.image_description_cache.clear()
                    notice = (
                        "【Group Chat Plus】图片描述缓存清除："
                        + ("成功" if cleared else "完成（缓存未启用或无缓存）")
                        + "\n即将重启 AstrBot..."
                    )
                    yield event.plain_result(notice)
                    try:
                        await self.restart_core()
                    except Exception as e:
                        yield event.plain_result(f"重启失败：{e}")
                except Exception:
                    try:
                        yield event.plain_result("【Group Chat Plus】图片描述缓存清除：失败，请查看日志")
                    except Exception:
                        pass
            except Exception:
                return

        async def _reset_session_data(self, event: AstrMessageEvent) -> None:
            """清理"当前会话"的本插件缓存与派生状态，不触碰 AstrBot 官方对话历史。"""
            try:
                platform_name = event.get_platform_name()
                is_private = event.is_private_chat()
                chat_id = event.get_group_id() if not is_private else event.get_sender_id()

                logger.info(
                    "【会话重置】开始: platform=%s, 类型=%s, chat_id=%s",
                    platform_name,
                    "私聊" if is_private else "群聊",
                    chat_id,
                )

                # 待转存的消息缓存
                try:
                    if chat_id in self.pending_messages_cache:
                        cached_count = len(self.pending_messages_cache.get(chat_id, []))
                        del self.pending_messages_cache[chat_id]
                        logger.info("【会话重置】已清空待转存消息缓存 chat_id=%s, 清理条数=%s", chat_id, cached_count)
                except Exception:
                    logger.warning("【会话重置】清空待转存消息缓存失败", exc_info=True)

                # 处理中消息标记
                try:
                    async with self.concurrent_lock:
                        keys_to_remove = [
                            msg_id
                            for msg_id, cid in self.processing_sessions.items()
                            if cid == chat_id
                        ]
                        for msg_id in keys_to_remove:
                            del self.processing_sessions[msg_id]
                    if keys_to_remove:
                        logger.info("【会话重置】已移除处理中标记 chat_id=%s, 清理条数=%s", chat_id, len(keys_to_remove))
                except Exception:
                    logger.warning("【会话重置】移除处理中标记失败", exc_info=True)

                # 最近回复缓存
                try:
                    if chat_id in self.recent_replies_cache:
                        replies_cleared = len(self.recent_replies_cache.get(chat_id, []))
                        del self.recent_replies_cache[chat_id]
                        logger.info("【会话重置】已清空最近回复缓存 chat_id=%s, 清理条数=%s", chat_id, replies_cleared)
                except Exception:
                    logger.warning("【会话重置】清空最近回复缓存失败", exc_info=True)

                # 戳一戳追踪记录
                try:
                    k = str(chat_id)
                    if isinstance(self.poke_trace_records, dict) and k in self.poke_trace_records:
                        del self.poke_trace_records[k]
                        logger.info("【会话重置】已移除戳一戳追踪记录 chat_id=%s", chat_id)
                except Exception:
                    logger.warning("【会话重置】移除戳一戳追踪记录失败", exc_info=True)

                # 概率状态重置
                try:
                    await ProbabilityManager.reset_probability(platform_name, is_private, chat_id)
                    logger.info("【会话重置】概率状态重置完成 chat_id=%s", chat_id)
                except Exception:
                    logger.warning("【会话重置】重置概率状态失败", exc_info=True)

                # 设置历史截止点（忽略重置前的平台聊天记录）
                try:
                    ContextManager.set_history_cutoff(chat_id)
                    logger.info("【会话重置】已设置历史截止点 chat_id=%s", chat_id)
                except Exception:
                    logger.warning("【会话重置】设置历史截止点失败", exc_info=True)

                logger.info("【会话重置】完成: chat_id=%s", chat_id)
            except Exception as e:
                logger.error(f"【会话重置】发生错误: {e}", exc_info=True)

        async def _reset_plugin_data_and_reload(self) -> None:
            """清空本插件的本地缓存与派生数据，然后热重载插件。"""
            try:
                logger.info("【插件重置】开始: 清理全局缓存并热重载")

                # 收集所有已知 chat_id 用于设置历史截止点
                _all_chat_ids_for_cutoff = set()
                try:
                    _all_chat_ids_for_cutoff.update(self.pending_messages_cache.keys())
                    _all_chat_ids_for_cutoff.update(
                        getattr(ProbabilityManager, "_probability_status", {}).keys()
                    )
                    _all_chat_ids_for_cutoff.update(
                        ContextManager._history_cutoff_timestamps.keys()
                    )
                except Exception:
                    pass

                try:
                    self.pending_messages_cache.clear()
                    logger.info("【插件重置】已清空待转存消息缓存")
                except Exception:
                    logger.warning("【插件重置】清空待转存消息缓存失败", exc_info=True)
                try:
                    async with self.concurrent_lock:
                        self.processing_sessions.clear()
                    logger.info("【插件重置】已清空处理中标记")
                except Exception:
                    logger.warning("【插件重置】清空处理中标记失败", exc_info=True)
                try:
                    self.command_messages.clear()
                    self.recent_replies_cache.clear()
                    self.raw_reply_cache.clear()
                    self._pending_bot_replies.clear()
                    self._agent_done_flags.clear()
                    self._group_message_seq.clear()
                    self._saved_messages.clear()
                    self._seen_message_ids.clear()
                    self._duplicate_blocked_messages.clear()
                    self._smart_batch_snapshots.clear()
                    self._message_cache_snapshots.clear()
                    self._chat_flow_owners.clear()
                    self.poke_trace_records = {}
                    logger.info("【插件重置】已清空各类内存缓存")
                except Exception:
                    logger.warning("【插件重置】清空内存缓存失败", exc_info=True)
                try:
                    for cid in _all_chat_ids_for_cutoff:
                        try:
                            ContextManager.set_history_cutoff(cid)
                        except Exception:
                            pass
                    logger.info("【插件重置】已为 %s 个会话设置历史截止点", len(_all_chat_ids_for_cutoff))
                except Exception:
                    logger.warning("【插件重置】设置历史截止点失败", exc_info=True)
                try:
                    if self.image_description_cache:
                        self.image_description_cache.clear()
                except Exception:
                    pass
                try:
                    ContextManager._clear_all_custom_storage()
                    logger.info("【插件重置】已清空自定义存储")
                except Exception:
                    logger.warning("【插件重置】清空自定义存储失败", exc_info=True)
                logger.info("【插件重置】完成，准备热重载")
            except Exception as e:
                logger.error(f"【插件重置】发生错误: {e}", exc_info=True)
