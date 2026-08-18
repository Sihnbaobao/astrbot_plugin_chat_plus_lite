"""
群聊增强插件 - Group Chat Plus（精简重构版 refactor-lite）
基于AI读空气的群聊增强插件，让bot更懂氛围

重构核心原则：
- 插件只决定"要不要回复"，不决定"说什么"
- 回复内容完全交给 AstrBot 原始链路（用户设定的人格 + 平台默认 prompt）
- 不再注入任何系统行为指令/情绪/注意力/主动对话等文本到 system_prompt / prompt

保留功能：
1. AI读空气判断 - 智能决定是否回复消息（DecisionAI，独立调用只输出 yes/no）
2. 概率筛选 - 非@消息按概率回复
3. 关键词触发 - 特定词触发（可配智能模式）
4. @消息与普通消息同样由读空气判断
5. 图片识别（转文字/多模态直传）、表情包标记、媒体路径内联
6. 转发消息解析、新成员入群解析
7. 黑名单（用户/关键词）
8. 时间戳/发送者标注（群聊里 AI 只比私聊多知道"谁在说话"）
9. 记忆注入（livingmemory 集成）
10. AstrBot 插件页管理控制台（Dashboard 内嵌，卡片式可视化）
11. 戳一戳（回复后戳/反戳/戳过追踪）
12. Smart 并发合并
13. 指令过滤、@全体成员/@他人过滤、重复回复过滤、内容过滤
14. 官方历史同步（用户消息/AI回复/缓存转正）

删除功能（详见 docs/REFACTOR_DESIGN.md）：
私聊全套、情绪系统、注意力机制、主动对话、等待窗口、对话疲劳、
错字生成、打字模拟、拟人模式、消息质量评分、回复密度、频率调整、
动态时间段概率、工具提醒文本注入、SystemPromptRewriter 差分重写

作者/维护: Sihnbaobao
版本: 0.0.2（重生重构 · 读空气主导/接管群聊）
"""

import random
import time
from datetime import datetime, timedelta, timezone
import copy
import sys
import hashlib
import asyncio
import json
import os
import re
from pathlib import Path
from typing import List, Optional, Any
from collections import OrderedDict
import aiohttp
from astrbot.api import logger

from astrbot.api.all import *
from astrbot.api.event import filter

from astrbot.core.message.components import Plain, At, AtAll
from astrbot.core.message.message_event_result import MessageChain

from astrbot.core.provider.entities import ProviderRequest

# 导入保留的工具模块
from .utils import (
    ProbabilityManager,
    MessageProcessor,
    ImageHandler,
    ContextManager,
    DecisionAI,
    ReplyHandler,
    MemoryInjector,
    KeywordChecker,
    MessageCleaner,
    PlatformLTMHelper,
    EmojiDetector,
    EMOJI_MARKER,
    SmartConcurrentManager,
    SaveMixin,
    CommandMixin,
    PokeMixin,
    MentionMixin,
)
from .utils.image_description_cache import ImageDescriptionCache
from .utils.message_cache_manager import MessageCacheManager

# aiocqhttp 平台相关（戳一戳功能仅支持该平台）
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)


@register(
    "astrbot_plugin_chat_plus_lite",
    "Sihnbaobao",
    "一个以AI读空气为主的群聊聊天效果增强插件（人格主导，简洁配置）",
    "0.0.2",
    "https://github.com/Sihnbaobao/astrbot_plugin_chat_plus_lite",
)
class ChatPlus(PokeMixin, MentionMixin, CommandMixin, SaveMixin, Star):
    """
    群聊增强插件主类（精简重构版）

    采用事件监听而非消息拦截，确保与其他插件兼容
    """

    # 重复回复缓存大小硬上限
    _DUPLICATE_CACHE_SIZE_LIMIT = 50

    # ============================================================
    # 初始化
    # ============================================================

    def __init__(self, context: Context, config: AstrBotConfig):
        """
        初始化插件

        Args:
            context: AstrBot的Context对象，包含各种API
            config: 插件配置
        """
        super().__init__(context)
        self.context = context
        self.config = config

        # V2.2.0：旧版平铺配置 → 分组结构一次性迁移（必须先于所有配置读取）
        self._migrate_legacy_flat_config()

        # ========== 基础配置 ==========
        self.enable_group_chat = self._cfg("enable_group_chat", True)
        self.debug_mode = self._cfg("enable_debug_log", False)
        self.enabled_groups = self._cfg("enabled_groups", [])

        # ========== 概率相关配置 ==========
        self.enable_random_probability_filter = self._cfg(
            "enable_random_probability_filter", False
        )  # 随机读空气总开关：关闭时普通消息直接交给人格 AI 判断
        self.initial_probability = self._cfg("initial_probability", 0.02)
        self.after_reply_probability = 0.8
        self.probability_duration = 120

        # ========== 决策AI（读空气）配置 ==========
        self.decision_ai_provider_id = self._cfg("decision_ai_provider_id", "")
        self.decision_ai_include_persona = self._cfg(
            "decision_ai_include_persona", True
        )
        self.decision_ai_persona_name = self._cfg("decision_ai_persona_name", "")
        self.decision_ai_extra_prompt = self._cfg("decision_ai_extra_prompt", "")
        self.decision_ai_timeout = self._cfg("decision_ai_timeout", 30)
        self.decision_ai_prompt_mode = self._cfg("decision_ai_prompt_mode", "append")
        self.decision_ai_reply_tendency = self._cfg(
            "decision_ai_reply_tendency", "persona"
        )
        self.enable_decision_ai_reasoning = self._cfg(
            "enable_decision_ai_reasoning", False
        )
        self.decision_ai_reasoning_log = self._cfg("decision_ai_reasoning_log", False)
        self.decision_ai_reasoning_log_mode = self._cfg(
            "decision_ai_reasoning_log_mode", "processed"
        )
        self.judgment_reasoning_start_marker = self._cfg(
            "judgment_reasoning_start_marker", "[[GCP_REASONING_START]]"
        )
        self.judgment_reasoning_end_marker = self._cfg(
            "judgment_reasoning_end_marker", "[[GCP_REASONING_END]]"
        )

        # ========== 回复配置 ==========
        self.reply_ai_extra_prompt = self._cfg("reply_ai_extra_prompt", "")
        self.reply_ai_prompt_mode = self._cfg("reply_ai_prompt_mode", "append")
        self.include_timestamp = self._cfg("include_timestamp", True)
        self.include_sender_info = self._cfg("include_sender_info", True)

        # ========== 上下文配置 ==========
        self.max_context_messages = self._cfg("max_context_messages", -1)
        self.custom_storage_max_messages = 500
        self.pending_cache_max_count = self._cfg("pending_cache_max_count", 10)
        self.pending_cache_ttl_seconds = self._cfg("pending_cache_ttl_seconds", 1800)

        # ========== 转发/入群解析配置 ==========
        # ========== 图片处理配置 ==========
        self.enable_image_processing = self._cfg("enable_image_processing", False)
        self.image_to_text_scope = self._cfg("image_to_text_scope", "mention_only")
        self.image_to_text_provider_id = self._cfg("image_to_text_provider_id", "")
        self.image_to_text_prompt = "请详细描述这张图片的内容"
        self.image_to_text_timeout = 60
        self.max_images_per_message = self._cfg("max_images_per_message", 10)
        self.enable_image_description_cache = self._cfg(
            "enable_image_description_cache", False
        )
        self.image_description_cache_max_entries = self._cfg(
            "image_description_cache_max_entries", 500
        )
        self.gcp_clear_image_cache_allowed_user_ids = self._cfg(
            "gcp_clear_image_cache_allowed_user_ids", []
        )
        self.platform_image_caption_max_wait = self._cfg(
            "platform_image_caption_max_wait", 2.0
        )
        self.platform_image_caption_retry_interval = self._cfg(
            "platform_image_caption_retry_interval", 50
        )
        self.platform_image_caption_fast_check_count = self._cfg(
            "platform_image_caption_fast_check_count", 5
        )
        self.probability_filter_cache_delay = self._cfg(
            "probability_filter_cache_delay", 500
        )

        # ========== 表情包标记配置 ==========
        self.enable_emoji_filter = self._cfg("enable_emoji_filter", False)
        self.emoji_probability_decay = 0.7
        self.emoji_decay_min_probability = 0.1

        # ========== 记忆注入配置（livingmemory） ==========
        self.enable_memory_injection = self._cfg("enable_memory_injection", False)
        self.memory_plugin_mode = self._cfg("memory_plugin_mode", "auto")
        self.memory_insertion_timing = "post_decision"
        self.livingmemory_top_k = self._cfg("livingmemory_top_k", 5)
        self.livingmemory_version = self._cfg("livingmemory_version", "auto")
        self.livingmemory_persona_compat_mode = self._cfg(
            "livingmemory_persona_compat_mode", "auto"
        )

        # ========== 关键词/黑名单配置 ==========
        self.trigger_keywords = self._cfg("trigger_keywords", [])
        self.blacklist_keywords = self._cfg("blacklist_keywords", [])
        self.keyword_smart_mode = self._cfg("keyword_smart_mode", True)  # 默认：关键词命中（含bot名字/被@）也交给读空气判断
        self.takeover_group_reply = self._cfg("takeover_group_reply", True)  # 默认：接管群聊回复（stop_event 挡住主对话，避免 @/关键词被兜底必回）
        self.enable_user_blacklist = self._cfg("enable_user_blacklist", False)
        self.blacklist_user_ids = self._cfg("blacklist_user_ids", [])

        # ========== 指令过滤配置 ==========
        self.enable_command_filter = self._cfg("enable_command_filter", True)
        self.command_prefixes = self._cfg("command_prefixes", ["/", "!", "#"])
        self.enable_full_command_detection = self._cfg(
            "enable_full_command_detection", False
        )
        self.full_command_list = self._cfg("full_command_list", ["new", "help", "reset"])
        self.enable_command_prefix_match = self._cfg(
            "enable_command_prefix_match", False
        )
        self.command_prefix_match_list = self._cfg("command_prefix_match_list", [])
        self.plugin_gcp_reset_allowed_user_ids = self._cfg(
            "plugin_gcp_reset_allowed_user_ids", []
        )
        self.plugin_gcp_reset_here_allowed_user_ids = self._cfg(
            "plugin_gcp_reset_here_allowed_user_ids", []
        )

        # ========== @消息过滤配置 ==========
        self.enable_ignore_at_others = self._cfg("enable_ignore_at_others", False)
        self.ignore_at_others_mode = self._cfg("ignore_at_others_mode", "strict")
        self.enable_ignore_at_all = self._cfg("enable_ignore_at_all", False)
        self.ignore_at_all_enabled = self.enable_ignore_at_all
        self.at_all_message_mode = self._cfg("at_all_message_mode", "skip_probability")
        self.at_all_probability_boost_value = self._cfg(
            "at_all_probability_boost_value", 0.3
        )

        # ========== 戳一戳配置 ==========
        self.poke_message_mode = self._cfg("poke_message_mode", "bot_only")
        self.poke_bot_skip_probability = True
        self.poke_after_reply_enabled = self._cfg("enable_poke_after_reply", False)
        self.poke_after_reply_probability = self._cfg(
            "poke_after_reply_probability", 0.15
        )
        self.poke_after_reply_delay = self._cfg("poke_after_reply_delay", 0.5)
        self.poke_trace_enabled = self._cfg("enable_poke_trace_prompt", False)
        self.poke_trace_max_tracked_users = self._cfg(
            "poke_trace_max_tracked_users", 5
        )
        self.poke_trace_ttl_seconds = self._cfg("poke_trace_ttl_seconds", 300)
        self.poke_enabled_groups = []  # 精简后固定默认：全部群可用戳一戳

        # 反戳概率（0=禁用，1=必定反戳并丢弃本插件处理）
        raw_reverse_prob = self._cfg("poke_reverse_on_poke_probability", 0)
        try:
            reverse_prob = float(raw_reverse_prob)
        except (TypeError, ValueError):
            reverse_prob = 0.0
        self.poke_reverse_on_poke_probability = max(0.0, min(1.0, reverse_prob))

        # ========== 去重过滤配置 ==========
        self.enable_duplicate_filter = self._cfg("enable_duplicate_filter", True)
        self.duplicate_filter_check_count = 5
        self.enable_duplicate_time_limit = True
        self.duplicate_filter_time_limit = 1800

        # ========== 并发/Smart配置 ==========
        self.concurrent_mode = self._cfg("concurrent_mode", "legacy")
        self.concurrent_wait_max_loops = self._cfg("concurrent_wait_max_loops", 10)
        self.concurrent_wait_interval = self._cfg("concurrent_wait_interval", 1)
        self.enable_smart_batch_reply_hint = self._cfg(
            "enable_smart_batch_reply_hint", True
        )
        self.smart_concurrent_merge_wait = self._cfg("smart_concurrent_merge_wait", 30)
        self.smart_concurrent_max_batch_size = self._cfg(
            "smart_concurrent_max_batch_size", 20
        )
        self.smart_concurrent_claim_delay = self._cfg(
            "smart_concurrent_claim_delay", 0.3
        )

        # ========== 性能警告阈值 ==========
        self.reply_timeout_warning_threshold = 120
        self.reply_generation_timeout_warning = 60

        # ========== 桌面端模式（AstrBot Desktop 兼容） ==========
        self.desktop_mode_setting = self._cfg("desktop_mode", "auto")

        # ========== 数据目录 ==========
        try:
            data_dir = Path(self.context.get_data_dir()) / "group_chat_plus"
        except Exception:
            data_dir = Path.cwd() / "data" / "group_chat_plus"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.plugin_data_dir = str(data_dir)

        # ========== 管理器初始化 ==========
        # 概率管理器
        ProbabilityManager.initialize({})

        # 上下文管理器（自定义存储）
        ContextManager.init(
            data_dir=str(data_dir),
            custom_storage_max_messages=self.custom_storage_max_messages,
        )

        # 消息缓存管理器（统一管理待决策消息的缓存）
        self.cache_manager = MessageCacheManager(
            cache_ttl_seconds=self.pending_cache_ttl_seconds,
            max_cache_count=self.pending_cache_max_count,
            debug_mode=self.debug_mode,
            include_timestamp=self.include_timestamp,
            include_sender_info=self.include_sender_info,
        )
        self.pending_messages_cache = self.cache_manager.pending_messages_cache

        # 图片描述缓存（省钱）
        self.image_description_cache = ImageDescriptionCache(
            data_dir=str(data_dir),
            max_entries=self.image_description_cache_max_entries,
            enabled=self.enable_image_description_cache,
        )


        # ========== 状态容器 ==========
        # 标记本插件正在处理的消息（用于 after_message_sent 筛选）
        self.processing_sessions: dict = {}
        # 并发控制锁
        self.concurrent_lock = asyncio.Lock()
        # 群聊消息到达顺序计数器（Smart 排序）
        self._arrival_seq_counter = 0
        # Smart 批次快照 {processing_id: [cached_message_dict, ...]}
        self._smart_batch_snapshots: dict = {}
        # 会话级流程 owner {chat_id: {"owner": str, "processing_id": str, "started_at": float}}
        self._chat_flow_owners: dict = {}
        # 消息缓存快照（供 after_message_sent 使用）{message_id: cached_message_dict}
        self._message_cache_snapshots: dict = {}
        # 指令消息标记 {message_id: timestamp}
        self.command_messages: dict = {}
        # 最近回复缓存（去重）{chat_id: [{"content": str, "timestamp": float}]}
        self.recent_replies_cache: dict = {}
        self.raw_reply_cache: dict = {}
        # 多轮工具调用累积AI回复文本 {message_id: [text, ...]}
        self._pending_bot_replies: dict = {}
        # 群聊消息序号 {chat_key: int}
        self._group_message_seq: dict = {}
        # agent完成标志 set[message_id]
        self._agent_done_flags: set = set()
        # 重复消息拦截标记 {message_id: True}
        self._duplicate_blocked_messages: dict = {}
        # 已保存消息标记 {message_id: timestamp}
        self._saved_messages: dict = {}
        # 平台重复推送去重 {source_event_id: timestamp}
        self._seen_message_ids: dict = {}
        # 戳一戳追踪记录 {chat_id: OrderedDict{user_id: expire_at}}
        self.poke_trace_records: dict = {}
        # AI错误消息标记 set[message_id]
        self._ai_error_message_ids: set = set()

        # Smart 并发参数同步
        try:
            SmartConcurrentManager._EXPIRE_SECONDS = float(self.smart_concurrent_merge_wait)
        except (TypeError, ValueError):
            pass
        try:
            SmartConcurrentManager._MAX_BATCH_SIZE = max(
                1, int(self.smart_concurrent_max_batch_size)
            )
        except (TypeError, ValueError):
            pass

        # 日志输出
        logger.info("=" * 50)
        logger.info("群聊增强插件已加载 - 0.0.2（重生重构版）")
        logger.info(f"🔘 群聊功能总开关: {'✓ 已启用' if self.enable_group_chat else '✗ 已禁用'}")
        logger.info(f"初始读空气概率: {self.initial_probability}")
        logger.info(f"回复后概率: {self.after_reply_probability}")
        logger.info(f"启用的群组: {self.enabled_groups} (留空=全部)")
        logger.info(f"详细日志模式: {'开启' if self.debug_mode else '关闭'}")
        logger.info("=" * 50)

    # ============================================================
    # 生命周期
    # ============================================================

    async def initialize(self):
        """插件激活时调用：同步并发参数、注册插件页 Web API。"""
        self.session = aiohttp.ClientSession()
        # 同步 Smart并发参数
        try:
            SmartConcurrentManager._EXPIRE_SECONDS = float(self.smart_concurrent_merge_wait)
        except (TypeError, ValueError):
            pass
        try:
            SmartConcurrentManager._MAX_BATCH_SIZE = max(
                1, int(self.smart_concurrent_max_batch_size)
            )
        except (TypeError, ValueError):
            pass

        # 注册 AstrBot 插件页 Web API（Dashboard 内嵌管理页面）
        self._register_web_apis()

    async def terminate(self):
        """插件禁用/重载时调用。"""
        if hasattr(self, "session"):
            try:
                await self.session.close()
            except Exception:
                pass

    # ============================================================
    # 插件页 Web API（AstrBot Dashboard 插件页，见 pages/control/）
    # V2.1.0：独立 Web 面板已移除，管理界面改为 AstrBot 插件页
    # （Dashboard 内嵌 iframe），后端 API 由此注册。
    # ============================================================

    # ============================================================
    # 配置访问兼容层（V2.2.0 配置分组：_conf_schema.json 按功能分栏）
    # 旧版平铺配置会在首次加载时自动迁移到分组结构。
    # ============================================================

    def _migrate_legacy_flat_config(self):
        """V2.2.0：旧版平铺配置 → 分组结构一次性迁移（需在读取配置前调用）。"""
        try:
            schema = getattr(self.config, "schema", None) or {}
            groups = {
                gname: meta.get("items", {})
                for gname, meta in schema.items()
                if isinstance(meta, dict)
                and meta.get("type") == "object"
                and isinstance(meta.get("items"), dict)
            }
            if not groups:
                return
            # 已处于分组结构（分组内已有数据）则跳过
            has_group_data = any(
                isinstance(self.config.get(g), dict) and self.config.get(g)
                for g in groups
            )
            if has_group_data:
                return
            migrated = 0
            for gname, items in groups.items():
                sub = {}
                for key in items:
                    if key in self.config:
                        sub[key] = self.config[key]
                        migrated += 1
                if sub:
                    self.config[gname] = sub
            for items in groups.values():
                for key in items:
                    if key in self.config:
                        del self.config[key]
            if migrated:
                self.config.save_config()
                logger.info(f"⚙️ 配置已迁移到分组结构（{migrated} 项）")
        except Exception as e:
            logger.warning(f"⚙️ 配置迁移失败（继续使用默认值）: {e}")

    def _cfg(self, key, default=None):
        """按分组结构读取配置；schema 外的键回退到平铺读取。"""
        try:
            schema = getattr(self.config, "schema", None) or {}
            for gname, gmeta in schema.items():
                if (
                    isinstance(gmeta, dict)
                    and isinstance(gmeta.get("items"), dict)
                    and key in gmeta["items"]
                ):
                    gval = self.config.get(gname)
                    if isinstance(gval, dict) and key in gval:
                        return gval[key]
                    return default
        except Exception:
            pass
        return self.config.get(key, default)

    def _set_cfg(self, key, value):
        """按分组结构写入配置；schema 外的键回退到平铺写入。"""
        try:
            schema = getattr(self.config, "schema", None) or {}
            for gname, gmeta in schema.items():
                if (
                    isinstance(gmeta, dict)
                    and isinstance(gmeta.get("items"), dict)
                    and key in gmeta["items"]
                ):
                    gval = self.config.get(gname)
                    if not isinstance(gval, dict):
                        gval = {}
                        self.config[gname] = gval
                    gval[key] = value
                    return
        except Exception:
            pass
        self.config[key] = value

    _PLUGIN_NAME = "astrbot_plugin_chat_plus_lite"

    # ============================================================
    # 插件页配置源：100% 由 _conf_schema.json 驱动
    # _schema_groups() 从 _conf_schema.json 动态读取分组与字段定义，
    # 插件页渲染与 AstrBot 配置页完全一致；全部配置统一由 _conf_schema.json 驱动
    # 有读取但 schema 未展示的隐藏参数。
    # ============================================================

    # schema 键 → 实例属性名 的例外映射（多数键名与属性名相同）
    _ATTR_MAP = {
        "desktop_mode": "desktop_mode_setting",
        "enable_debug_log": "debug_mode",
        "enable_poke_trace_prompt": "poke_trace_enabled",
        "enable_poke_after_reply": "poke_after_reply_enabled",
    }

    def _schema_groups(self):
        """从 _conf_schema.json 动态提取分组与字段定义（与 AstrBot 配置页一致）。"""
        try:
            schema = getattr(self.config, "schema", None) or {}
            groups = []
            for gname, gmeta in schema.items():
                if isinstance(gmeta, dict) and isinstance(gmeta.get("items"), dict):
                    groups.append(
                        {
                            "id": gname,
                            "title": gmeta.get("description") or gname,
                            "hint": gmeta.get("hint", ""),
                            "items": gmeta["items"],
                        }
                    )
            return groups
        except Exception:
            return []

    def _all_editable_keys(self) -> dict:
        """全部可编辑键 → 属性名（全部来自 schema 分组）。"""
        mapping = {}
        for group in self._schema_groups():
            for key in group["items"]:
                mapping[key] = self._ATTR_MAP.get(key, key)
        return mapping
    def _register_web_apis(self):
        """注册插件页 Web API（需要 AstrBot >= 4.25.3 的 Plugin Pages 支持）。"""
        try:
            self.context.register_web_api(
                f"/{self._PLUGIN_NAME}/status",
                self._api_status,
                ["GET"],
                "插件运行状态总览",
            )
            self.context.register_web_api(
                f"/{self._PLUGIN_NAME}/config/save",
                self._api_save_config,
                ["POST"],
                "保存插件页修改的配置",
            )
            self.context.register_web_api(
                f"/{self._PLUGIN_NAME}/prompts",
                self._api_prompts,
                ["GET"],
                "提示词预览（读空气判断/回复生成）",
            )
            logger.info("✅ 插件页 Web API 已注册（Dashboard 插件页可用）")
        except Exception as e:
            logger.warning(f"插件页 Web API 注册失败（需要 AstrBot v4.25.3+）: {e}")

    async def _api_status(self):
        """返回插件状态总览（供插件页渲染卡片/胶囊）。"""
        from astrbot.api.web import json_response

        values = {}
        for key, attr in self._all_editable_keys().items():
            values[key] = self._cfg(key, getattr(self, attr, None))

        prob_status = getattr(ProbabilityManager, "_probability_status", {}) or {}
        runtime = {
            "probability_session_count": len(prob_status),
            "smart_batch_snapshot_count": len(
                getattr(self, "_smart_batch_snapshots", {})
            ),
            "processing_session_count": len(getattr(self, "processing_sessions", {})),
        }
        groups = self._schema_groups()
        return json_response(
            {
                "version": "0.0.2",
                "values": values,
                "groups": groups,
                "runtime": runtime,
            }
        )

    async def _api_save_config(self):
        """保存插件页提交的配置变更（仅允许白名单内的键）。"""
        from astrbot.api.web import error_response, json_response, request

        try:
            payload = await request.json(default={})
        except Exception:
            payload = {}
        updates = payload.get("updates") if isinstance(payload, dict) else None
        if not isinstance(updates, dict) or not updates:
            return error_response("updates 必须是非空对象")

        applied = []
        skipped = []
        valid_keys = self._all_editable_keys()
        for key, value in updates.items():
            if key not in valid_keys:
                skipped.append(key)
                continue
            try:
                self._set_cfg(key, value)
            except Exception:
                skipped.append(key)
                continue
            setattr(self, valid_keys[key], value)
            applied.append(key)

        try:
            self.config.save_config()
        except Exception as e:
            logger.warning(f"插件页保存配置落盘失败: {e}")

        # Smart 并发参数需同步到类级
        try:
            SmartConcurrentManager._EXPIRE_SECONDS = float(
                self.smart_concurrent_merge_wait
            )
        except (TypeError, ValueError):
            pass
        try:
            SmartConcurrentManager._MAX_BATCH_SIZE = max(
                1, int(self.smart_concurrent_max_batch_size)
            )
        except (TypeError, ValueError):
            pass

        return json_response({"applied": applied, "skipped": skipped})

    def _page_tendency_prompt(self) -> str:
        """与 DecisionAI.should_reply 中 reply_tendency 段落保持一致的预览文本。"""
        tendency = self.decision_ai_reply_tendency
        if tendency == "reserved":
            return (
                "\n\n【本次判断为保守模式】：\n"
                "- 普通闲聊、寒暄、纯陈述一律不回复（返回no）\n"
                "- 只回复明确需要你回应的消息：直接@你、直接提问、求助、触发关键词且与你有实质关系\n"
                "- 不确定时一律返回no\n"
            )
        if tendency == "active":
            return (
                "\n\n【本次判断为积极模式】：\n"
                "- 适度放宽判断标准，主动参与群聊互动\n"
                "- 寒暄和普通闲聊也可以接话，不确定时倾向于回复（yes）\n"
            )
        return (
            "\n\n【本次判断以人格社交倾向为最高优先级】：\n"
            "- 若人格设定为沉默寡言/话少/冷淡型，普通闲聊默认不回复\n"
            "- 仅回复直接@、明确提问、求助、触发关键词且与你有实质关系的消息\n"
            "- 不确定时以人格社交倾向为最终依据\n"
        )

    async def _api_prompts(self):
        """返回读空气判断/回复生成的提示词预览（与真实拼接逻辑保持一致）。"""
        from astrbot.api.web import json_response

        try:
            from .utils.decision_ai import DecisionAI
            from .utils.reply_handler import ReplyHandler
        except Exception:
            return json_response(
                {
                    "decision": {"text": "（无法加载提示词模块）"},
                    "reply": {"text": ""},
                }
            )

        decision_custom = bool(
            self.decision_ai_extra_prompt
            and str(self.decision_ai_extra_prompt).strip()
        )
        if decision_custom and self.decision_ai_prompt_mode == "override":
            decision_text = str(self.decision_ai_extra_prompt).strip()
        else:
            decision_text = DecisionAI.SYSTEM_DECISION_PROMPT
            if decision_custom:
                decision_text += (
                    f"\n\n用户补充说明:\n{self.decision_ai_extra_prompt.strip()}\n"
                )
        decision_text += self._page_tendency_prompt()
        decision_text += DecisionAI.SYSTEM_DECISION_PROMPT_ENDING

        reply_custom = bool(
            self.reply_ai_extra_prompt and str(self.reply_ai_extra_prompt).strip()
        )
        if reply_custom and self.reply_ai_prompt_mode == "override":
            reply_text = str(self.reply_ai_extra_prompt).strip()
        else:
            reply_text = "[发送者标注 + 历史上下文 + 当前消息]"
            if reply_custom:
                reply_text += "\n" + str(self.reply_ai_extra_prompt).strip()
        reply_text += ReplyHandler.PROMPT_ENDING

        return json_response(
            {
                "decision": {
                    "mode": self.decision_ai_prompt_mode,
                    "has_custom": decision_custom,
                    "extra": str(self.decision_ai_extra_prompt or ""),
                    "text": decision_text,
                },
                "reply": {
                    "mode": self.reply_ai_prompt_mode,
                    "has_custom": reply_custom,
                    "extra": str(self.reply_ai_extra_prompt or ""),
                    "text": reply_text,
                },
            }
        )

    @filter.on_platform_loaded()
    async def on_platform_loaded(self):
        """平台加载完成后，发送重启完成提示（gcp_reset 后使用）。"""
        restart_umo = self._cfg("restart_umo")
        platform_id = self._cfg("platform_id")
        restart_start_ts = self._cfg("restart_start_ts")
        if not restart_umo or not platform_id or not restart_start_ts:
            return

        platform = self.context.get_platform_inst(platform_id)
        if not isinstance(platform, AiocqhttpAdapter):
            logger.warning("未找到 aiocqhttp 平台实例，跳过重启提示")
            try:
                await self.context.send_message(
                    session=restart_umo,
                    message_chain=MessageChain(
                        [Plain("⚠️ 重启完成提示发送失败：当前平台不支持重启提示功能（仅支持aiocqhttp平台）")]
                    ),
                )
            except Exception as e:
                logger.error(f"发送重启失败提示时出错: {e}")
            self.config["restart_umo"] = ""
            self.config["restart_start_ts"] = 0
            self.config.save_config()
            return

        client = platform.get_client()
        if not client:
            logger.warning("未找到 CQHttp 实例，跳过重启提示")
            try:
                await self.context.send_message(
                    session=restart_umo,
                    message_chain=MessageChain([Plain("⚠️ 重启完成提示发送失败：未找到CQHttp客户端实例")]),
                )
            except Exception as e:
                logger.error(f"发送重启失败提示时出错: {e}")
            self.config["restart_umo"] = ""
            self.config["restart_start_ts"] = 0
            self.config.save_config()
            return

        ws_connected = asyncio.Event()

        @client.on_websocket_connection
        def _(_):
            ws_connected.set()

        try:
            await asyncio.wait_for(ws_connected.wait(), timeout=10)
        except asyncio.TimeoutError:
            logger.warning("等待 aiocqhttp WebSocket 连接超时，可能未能发送重启完成提示。")

        elapsed = time.time() - float(restart_start_ts)
        await self.context.send_message(
            session=restart_umo,
            message_chain=MessageChain([Plain(f"AstrBot重启完成（耗时{elapsed:.2f}秒）")]),
        )
        self.config["restart_umo"] = ""
        self.config["restart_start_ts"] = 0
        self.config.save_config()

    # ============================================================
    # 重启辅助
    # ============================================================

    async def _get_auth_token(self):
        """获取认证 token（JWT 签发，失败降级密码登录）。"""
        try:
            token = self._generate_jwt_token()
            logger.debug("通过 jwt_secret 生成认证 token 成功")
            return token
        except Exception as e:
            logger.warning(f"通过 jwt_secret 生成 token 失败: {e}，降级尝试密码登录...")

        login_url = f"http://{self.host}:{self.port}/api/auth/login"
        login_data = {
            "username": self.dbc["username"],
            "password": self.dbc["password"],
        }
        async with self.session.post(login_url, json=login_data) as response:
            if response.status == 200:
                data = await response.json()
                if data and data.get("status") == "ok" and "data" in data:
                    token = data.get("data", {}).get("token")
                    if token:
                        return token
                raise Exception(f"登录响应格式错误: {data}")
            else:
                text = await response.text()
                raise Exception(f"登录失败，状态码: {response.status}, 响应: {text}")

    def _generate_jwt_token(self, dbc_override: dict | None = None) -> str:
        """使用 dashboard 的 jwt_secret 直接签发 JWT，跳过密码登录。"""
        import jwt as _jwt

        dbc = dbc_override if dbc_override is not None else self.dbc
        jwt_secret = dbc.get("jwt_secret", "")
        if not jwt_secret:
            raise ValueError("jwt_secret 不在 dashboard 配置中")

        payload = {
            "username": dbc.get("username", "astrbot"),
            "exp": datetime.now(timezone.utc) + timedelta(days=7),
        }
        return _jwt.encode(payload, jwt_secret, algorithm="HS256")

    def _detect_desktop_mode(self, config) -> bool:
        """多重策略检测是否运行在 AstrBot 桌面端环境。"""
        mode = self.desktop_mode_setting
        if mode == "force_desktop":
            logger.info("🖥️ [桌面端] 用户强制配置为桌面端模式（desktop_mode=force_desktop）")
            return True
        if mode == "force_standard":
            logger.info("🖥️ [桌面端] 用户强制配置为标准版模式（desktop_mode=force_standard）")
            return False

        detected_reason = ""
        if os.environ.get("ASTRBOT_DESKTOP_CLIENT") == "1":
            detected_reason = "env:ASTRBOT_DESKTOP_CLIENT=1"
        if not detected_reason:
            astrbot_root = os.environ.get("ASTRBOT_ROOT", "")
            if astrbot_root:
                try:
                    home = Path.home()
                    root_path = Path(astrbot_root).resolve()
                    if root_path == (home / ".astrbot").resolve():
                        detected_reason = f"path:ASTRBOT_ROOT={astrbot_root}"
                except Exception:
                    pass
        if not detected_reason:
            webui_dir = os.environ.get("ASTRBOT_WEBUI_DIR", "")
            if webui_dir and "resources" in webui_dir.replace("\\", "/").lower():
                detected_reason = f"env:ASTRBOT_WEBUI_DIR={webui_dir}"
        if not detected_reason:
            if os.environ.get("PYTHONNOUSERSITE") == "1" and os.environ.get("ASTRBOT_ROOT"):
                detected_reason = "env:PYTHONNOUSERSITE=1+ASTRBOT_ROOT"

        is_desktop = bool(detected_reason)
        try:
            config["desktop_detected_env"] = detected_reason or "none"
            config.save_config()
        except Exception:
            pass
        return is_desktop

    async def restart_core(self):
        """发送重启请求，重启AstrBot，并记录重启信息。"""
        try:
            if self.is_desktop_mode:
                logger.warning(
                    "🖥️ [桌面端] 即将发送重启请求。桌面端的进程由 Tauri 托管，"
                    "通过 HTTP API 触发的重启可能导致 Tauri 丢失对后端进程的跟踪。"
                    "如重启后出现异常，请通过桌面端托盘菜单手动重启后端。"
                )
            token = await self._get_auth_token()
            headers = {"Authorization": f"Bearer {token}"}
            async with self.session.post(self.restart_url, headers=headers) as response:
                if response.status == 200:
                    logger.info("系统重启请求已发送")
                else:
                    logger.error(f"重启请求失败，状态码: {response.status}")
                    raise RuntimeError(f"重启请求失败，状态码: {response.status}")
        except Exception as e:
            logger.error(f"发送重启请求时出错: {e}")
            raise e

    # ============================================================
    # 指令过滤与重置指令
    # ============================================================

    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize - 1)

    # ============================================================
    # 群消息入口
    # ============================================================

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=-1)
    async def on_group_message(self, event: AstrMessageEvent):
        """
        群消息事件监听

        优先级设置为 -1（低于默认的 0），确保其他插件先执行。
        如果其他插件已经发送了回复，本插件跳过处理，避免重复回复。
        """
        _cleanup_message_id = None
        try:
            # 检查群聊功能总开关
            if not self.enable_group_chat or event.is_private_chat():
                return

            # 直接打掉平台产生的真空消息
            _raw_msg_str = event.get_message_str()
            _msg_components = None
            try:
                if hasattr(event, "message_obj") and hasattr(event.message_obj, "message"):
                    _msg_components = event.message_obj.message
            except Exception:
                pass
            if (not _raw_msg_str or not _raw_msg_str.strip()) and not _msg_components:
                # 平台系统事件/真空消息（如进群通知）：不参与读空气，静默放行
                event.call_llm = True
                return

            msg_id = self._get_processing_id(event)
            source_event_id = self._build_source_event_id(event)
            self._ensure_arrival_metadata(event)
            _cleanup_message_id = msg_id

            # 消息去重（防止平台重复推送）
            current_time = time.time()
            if len(self._seen_message_ids) > 100:
                self._seen_message_ids = {
                    k: v for k, v in self._seen_message_ids.items() if current_time - v < 60
                }
            if source_event_id in self._seen_message_ids:
                if self.debug_mode:
                    logger.info(
                        f"[消息去重] 检测到重复消息 {source_event_id[:30]}...，跳过处理"
                    )
                event.call_llm = True
                return
            self._seen_message_ids[source_event_id] = current_time

            # 指令消息跳过
            if msg_id in self.command_messages:
                if self.debug_mode:
                    logger.info("消息已被标记为指令，跳过处理")
                return

            # 插件兼容性检查：其他插件已回复则跳过AI处理但保留缓存
            if getattr(event, "_has_send_oper", False):
                try:
                    if self._is_enabled(event):
                        chat_id = event.get_group_id()
                        message_text = (
                            MessageCleaner.extract_raw_message_from_event(
                                event, self_id=str(event.get_self_id())
                            )
                            or event.get_message_str()
                            or ""
                        )
                        if message_text.strip():
                            try:
                                mention_info = await self._check_mention_others(event)
                            except Exception:
                                mention_info = None
                            cached_message = {
                                "role": "user",
                                "content": message_text,
                                "timestamp": current_time,
                                "message_id": msg_id,
                                "sender_id": event.get_sender_id(),
                                "sender_name": event.get_sender_name(),
                                "message_timestamp": event.message_obj.timestamp
                                if hasattr(event, "message_obj")
                                and hasattr(event.message_obj, "timestamp")
                                else None,
                                "mention_info": mention_info,
                                "is_at_message": False,
                                "has_trigger_keyword": False,
                                "poke_info": None,
                                "persistent_poke_event_text": "",
                                "image_urls": [],
                                "is_at_all_message": False,
                                "is_empty_at": False,
                            }
                            self.cache_manager.add_to_cache(
                                chat_id, cached_message, source="插件兼容-其他插件已回复"
                            )
                except Exception as e:
                    logger.warning(f"[插件兼容] 缓存消息时出错（不影响后续）: {e}")
                return

            # 用户黑名单
            if self._is_user_blacklisted(event):
                return

            # @全体成员过滤
            if self._should_ignore_at_all(event):
                if self.debug_mode:
                    logger.info("[@全体成员检测] 消息包含@全体成员，本插件跳过处理")
                return

            try:
                event.set_extra("is_at_all_message", self._is_at_all_message(event))
            except Exception as e:
                logger.warning(f"[@全体成员识别] 写入事件标记失败，按普通消息继续: {e}")

            # 过滤伪造的戳一戳文本标识符
            message_str = event.get_message_str()
            if MessageCleaner.is_only_poke_marker(message_str):
                if self.debug_mode:
                    logger.info("【戳一戳标识符过滤】消息只包含[Poke:poke]标识符，跳过处理")
                return

            # @他人过滤
            if self._should_ignore_at_others(event):
                if self.debug_mode:
                    logger.info("[@他人检测] 消息符合忽略条件，本插件跳过处理")
                return

            # 戳一戳消息检测（忽略配置）
            poke_result = await self._check_poke_message(event)
            if poke_result.get("is_poke") and poke_result.get("should_ignore"):
                if self.debug_mode:
                    logger.info("【戳一戳检测】消息符合忽略条件，本插件跳过处理")
                return

            # 处理群消息
            async for result in self._process_message(event):
                yield result
        except Exception as e:
            logger.error(f"处理群消息时发生错误: {e}", exc_info=True)
        finally:
            # 安全网：确保 processing_sessions 条目不会泄漏
            if _cleanup_message_id:
                async with self.concurrent_lock:
                    self.processing_sessions.pop(_cleanup_message_id, None)
                self._message_cache_snapshots.pop(_cleanup_message_id, None)
                self._duplicate_blocked_messages.pop(_cleanup_message_id, None)
                self._smart_batch_snapshots.pop(_cleanup_message_id, None)

    # ============================================================
    # 消息处理主流程
    # ============================================================

    async def _format_ai_context(
        self,
        history_messages,
        current_message,
        bot_id,
        window_msgs=None,
        poke_notice="",
    ) -> str:
        """统一格式化 AI 上下文（集中 include 配置，减少主流程重复）。"""
        return await ContextManager.format_context_for_ai(
            history_messages,
            current_message,
            bot_id,
            include_timestamp=self.include_timestamp,
            include_sender_info=self.include_sender_info,
            window_buffered_messages=window_msgs,
            poke_notice=poke_notice,
        )

    async def _process_message(self, event: AstrMessageEvent):
        """
        消息处理主流程''  # 占位

        流程：
        初始检查 → 消息触发器（@/关键词）→ 戳一戳/@提及 → 概率判断 →
        内容处理（图片/媒体/上下文）→ Smart并发 → AI决策（读空气）→ 生成并发送回复
        """
        # 接管群聊回复：挡住 AstrBot 主对话对消息（含@/触发词）的兜底响应，是否回复只由读空气决定
        if self.takeover_group_reply:
            try:
                if hasattr(event, "stop_event"):
                    event.stop_event()
            except Exception:
                pass

        # 步骤1: 初始检查（最基本的过滤）
        (should_continue, platform_name, is_private, chat_id) = await self._perform_initial_checks(event)
        if not should_continue:
            return

        # 步骤2: 检查消息触发器（决定是否跳过概率判断）
        _chat_key_for_seq = ProbabilityManager.get_chat_key(platform_name, is_private, chat_id)
        current_group_seq = self._group_message_seq.get(_chat_key_for_seq, 0) + 1
        self._group_message_seq[_chat_key_for_seq] = current_group_seq
        (is_at_message, has_trigger_keyword, matched_trigger_keyword) = await self._check_message_triggers(event)

        # 步骤2.5: 检测@全体成员与戳一戳信息（概率判断前提取）
        is_at_all_message = False
        try:
            is_at_all_message = bool(
                event.get_extra("is_at_all_message", False)
                if hasattr(event, "get_extra")
                else False
            )
        except Exception:
            is_at_all_message = False

        poke_result = await self._check_poke_message(event)
        poke_info_for_probability = (
            poke_result
            if poke_result.get("is_poke") and not poke_result.get("should_ignore")
            else None
        )

        # 提前构建戳一戳文本（概率检查之前）
        persistent_poke_event_text = ""
        poke_notice_text = ""
        if poke_info_for_probability:
            _poke_info_inner = poke_info_for_probability.get("poke_info")
            if _poke_info_inner:
                try:
                    persistent_poke_event_text = (
                        MessageProcessor.build_persistent_poke_event_text(_poke_info_inner)
                    )
                except Exception:
                    pass
                try:
                    _is_pb = _poke_info_inner.get("is_poke_bot", False)
                    _sid = str(_poke_info_inner.get("sender_id", "") or "")
                    _sname = str(_poke_info_inner.get("sender_name", "") or "").strip() or "未知用户"
                    _tid = str(_poke_info_inner.get("target_id", "") or "")
                    _tname = str(_poke_info_inner.get("target_name", "") or "").strip() or "未知用户"
                    if _is_pb:
                        poke_notice_text = f"[戳一戳提示]有人在戳你，戳你的人是{_sname}(ID:{_sid})"
                    else:
                        poke_notice_text = f"[戳一戳提示]这是一个戳一戳消息，但不是戳你的，是{_sname}(ID:{_sid})在戳{_tname}(ID:{_tid})"
                except Exception:
                    pass

        # 步骤2.8: 提前检测@提及信息
        mention_info = await self._check_mention_others(event)

        # 关键逻辑：触发关键词等同于@消息
        should_treat_as_at = is_at_message or has_trigger_keyword

        # 步骤2.7: 表情包检测（概率判断前，用于概率衰减和标记注入，仅QQ平台）
        is_emoji_message = False
        if self.enable_emoji_filter:
            platform_name_lower = platform_name.lower() if platform_name else ""
            is_qq_platform = any(
                kw in platform_name_lower
                for kw in ("qq", "napcat", "lagrange", "aiocqhttp", "onebot")
            )
            if is_qq_platform:
                try:
                    is_emoji_message = EmojiDetector.is_emoji_message(event)
                except Exception as e:
                    logger.warning(f"【步骤2.7】🎭 表情包检测失败，跳过: {e}")

        # 步骤3: 概率判断（第一道核心过滤）
        should_process = await self._check_probability_before_processing(
            event,
            platform_name,
            is_private,
            chat_id,
            is_at_message,
            has_trigger_keyword,
            poke_info_for_probability,
            is_emoji_message=is_emoji_message,
            is_at_all_message=is_at_all_message,
        )
        if not should_process:
            # 未通过概率筛选时，缓存消息（避免上下文断裂）
            try:
                original_message_text = MessageCleaner.extract_raw_message_from_event(
                    event, self_id=str(event.get_self_id())
                )
                await asyncio.sleep(0)
                has_image = PlatformLTMHelper.has_image_in_message(event)
                if has_image:
                    if self.probability_filter_cache_delay > 0:
                        await asyncio.sleep(self.probability_filter_cache_delay / 1000.0)
                is_pure_image = PlatformLTMHelper.is_pure_image_message(event)

                processed_text = None
                should_cache = True
                success = False

                if has_image:
                    (success, platform_processed_text) = (
                        await PlatformLTMHelper.extract_image_caption_from_platform(
                            self.context,
                            event,
                            original_message_text,
                            max_wait=self.platform_image_caption_max_wait,
                            retry_interval=self.platform_image_caption_retry_interval,
                            fast_check_count=self.platform_image_caption_fast_check_count,
                        )
                    )
                    if success and platform_processed_text:
                        processed_text = platform_processed_text
                        await self._save_platform_descriptions_to_cache(
                            event, platform_processed_text
                        )
                    else:
                        cache_fallback_text = await self._try_cache_fallback_for_images(event)
                        if cache_fallback_text:
                            processed_text = cache_fallback_text
                            success = True
                        elif is_pure_image:
                            should_cache = False
                        else:
                            should_cache, processed_text = (
                                MessageCleaner.process_cached_message_images(
                                    original_message_text
                                )
                            )
                else:
                    processed_text = original_message_text
                    should_cache = bool(processed_text and processed_text.strip())

                if should_cache and processed_text:
                    image_retained_in_cache = (has_image and success) or (not has_image)
                    if (
                        is_emoji_message
                        and self.enable_emoji_filter
                        and image_retained_in_cache
                    ):
                        processed_text = EmojiDetector.add_emoji_marker(processed_text)
                    cached_message = {
                        "role": "user",
                        "content": processed_text,
                        "timestamp": time.time(),
                        "message_id": self._get_processing_id(event),
                        "sender_id": event.get_sender_id(),
                        "sender_name": event.get_sender_name(),
                        "message_timestamp": event.message_obj.timestamp
                        if hasattr(event, "message_obj")
                        and hasattr(event.message_obj, "timestamp")
                        else None,
                        "mention_info": mention_info,
                        "is_at_message": is_at_message,
                        "has_trigger_keyword": has_trigger_keyword,
                        "is_at_all_message": is_at_all_message,
                        "poke_info": None,
                        "persistent_poke_event_text": persistent_poke_event_text,
                        "probability_filtered": True,
                        "image_urls": [],
                        "is_empty_at": False,
                    }
                    source_label = "概率过滤-带图片描述" if (has_image and success) else "概率过滤"
                    self.cache_manager.add_to_cache(
                        chat_id, cached_message, source=source_label
                    )
            except Exception as e:
                logger.warning(f"[概率过滤-缓存] 缓存消息失败: {e}")

            return

        # 步骤3.5: 戳一戳反戳逻辑（放在概率判断之后）
        poke_info = (
            poke_info_for_probability.get("poke_info")
            if poke_info_for_probability
            else None
        )
        if poke_info:
            reversed_and_discarded = await self._maybe_reverse_poke_on_poke(
                event, poke_info, is_private, chat_id
            )
            if reversed_and_discarded:
                return

        # @消息/关键词触发提前检查是否已被其他插件处理
        if is_at_message or has_trigger_keyword:
            if ReplyHandler.check_if_already_replied(event):
                trigger_label = "@消息" if is_at_message else "关键词触发消息"
                logger.info(f"{trigger_label}已被其他插件处理,跳过后续流程")
                return

        # 步骤4-6: 处理消息内容（图片处理等耗时操作）
        result = await self._process_message_content(
            event,
            chat_id,
            current_group_seq,
            should_treat_as_at,
            mention_info,
            has_trigger_keyword,
            poke_info,
            raw_is_at_message=is_at_message,
            is_emoji_message=is_emoji_message,
            is_at_all_message=is_at_all_message,
            persistent_poke_event_text=persistent_poke_event_text,
        )
        if not result[0]:
            return

        (
            _,
            original_message_text,
            message_text,
            formatted_context,
            image_urls,
            history_messages,
            cached_message_data,
            emoji_marker_applied,
        ) = result

        def _build_current_message_for_ai(current_text: str) -> str:
            _is_empty_at = MessageCleaner.is_empty_at_message(
                original_message_text,
                is_at_message,
                mention_info=mention_info,
                mode="only_ai",
            )
            _current_message = MessageProcessor.add_metadata_to_message(
                event,
                current_text,
                self.include_timestamp,
                self.include_sender_info,
                mention_info,
                "keyword"
                if has_trigger_keyword
                else "at"
                if should_treat_as_at
                else "ai_decision",
                poke_info,
                _is_empty_at,
                "",
                "",
                is_at_all_message=is_at_all_message,
                persistent_poke_event_text=persistent_poke_event_text,
            )
            return _current_message

        current_message_for_ai = _build_current_message_for_ai(message_text)

        merged_image_urls = image_urls or []
        try:
            if (
                self.enable_image_processing
                and not self.image_to_text_provider_id
                and chat_id in self.pending_messages_cache
            ):
                for _cached in self.pending_messages_cache[chat_id]:
                    if isinstance(_cached, dict):
                        _urls = _cached.get("image_urls") or []
                        if _urls:
                            merged_image_urls.extend(_urls)
                if merged_image_urls:
                    _seen_urls = set()
                    _dedup_urls = []
                    for _u in merged_image_urls:
                        if _u and _u not in _seen_urls:
                            _seen_urls.add(_u)
                            _dedup_urls.append(_u)
                    merged_image_urls = _dedup_urls
        except Exception as e:
            logger.warning(f"[图片缓存] 合并图片URL失败: {e}")

        current_message_cache = cached_message_data
        processing_id = self._get_processing_id(event)
        source_event_id = self._build_source_event_id(event)
        arrival_seq, arrival_monotonic = self._ensure_arrival_metadata(event)
        early_message_id = processing_id

        if self.concurrent_mode == "smart":
            await SmartConcurrentManager.register_arrival(
                chat_id=chat_id,
                processing_id=processing_id,
                source_event_id=source_event_id,
                arrival_seq=arrival_seq,
                arrival_monotonic=arrival_monotonic,
            )

        if self.concurrent_mode == "smart" and cached_message_data:
            try:
                _smart_content = MessageCleaner.clean_message(message_text or "")
            except Exception:
                _smart_content = message_text or ""
            _smart_cached = dict(cached_message_data)
            _is_forced = is_at_message or has_trigger_keyword
            await SmartConcurrentManager.attach_payload(
                chat_id=chat_id,
                processing_id=processing_id,
                content=_smart_content,
                sender_name=self._safe_sender_display(event),
                sender_id=str(event.get_sender_id()),
                cached_data=_smart_cached,
                is_forced=_is_forced,
            )
            if self.debug_mode:
                logger.info(
                    f"🔀 [Smart并发] 消息 {processing_id[:20]}... 已挂载批处理载荷"
                )

            # Smart 模式下先按 arrival_seq 等待更早消息，确保只有 anchor 进入 AI 决策
            smart_claim = None
            for smart_wait_idx in range(max(1, self.concurrent_wait_max_loops)):
                if await SmartConcurrentManager.is_consumed(processing_id):
                    logger.info(
                        f"🔀 [Smart并发] 消息 {processing_id[:20]}... 已在决策前被更早批次吸收，跳过独立处理"
                    )
                    event.call_llm = True
                    await SmartConcurrentManager.remove_self(chat_id, processing_id)
                    self._message_cache_snapshots.pop(processing_id, None)
                    self._smart_batch_snapshots.pop(processing_id, None)
                    return

                if await SmartConcurrentManager.has_earlier_pending(chat_id, processing_id):
                    if smart_wait_idx == 0 and self.debug_mode:
                        logger.info("🔀 [Smart并发] 决策前检测到更早到达的消息尚未完成，等待其先成为 anchor")
                    await asyncio.sleep(self.concurrent_wait_interval)
                    continue

                if (
                    smart_wait_idx == 0
                    and not _is_forced
                    and self.smart_concurrent_claim_delay > 0
                ):
                    await asyncio.sleep(self.smart_concurrent_claim_delay)

                smart_claim = await SmartConcurrentManager.claim_batch(
                    chat_id, processing_id
                )
                if smart_claim.get("is_consumed"):
                    logger.info(
                        f"🔀 [Smart并发] 消息 {processing_id[:20]}... 已在 claim 阶段被更早 anchor 吸收，跳过独立处理"
                    )
                    event.call_llm = True
                    await SmartConcurrentManager.remove_self(chat_id, processing_id)
                    self._message_cache_snapshots.pop(processing_id, None)
                    self._smart_batch_snapshots.pop(processing_id, None)
                    return
                if smart_claim.get("is_anchor"):
                    merged_entries = smart_claim.get("merged_entries", []) or []
                    if merged_entries:
                        logger.info(
                            f"🔀 [Smart并发] 以当前消息为 anchor，吸收了 {len(merged_entries)} 条后续消息进入同一批次"
                        )
                        smart_window_messages = []
                        for _sm in merged_entries:
                            _sm_cache_entry = dict(_sm.get("cached_data") or {})
                            if not _sm_cache_entry:
                                continue
                            _sm_cache_entry["window_buffered"] = True
                            _sm_cache_entry["smart_merged"] = True
                            _sm_cache_entry["smart_batch_dynamic_hint"] = True
                            smart_window_messages.append(_sm_cache_entry)
                        if smart_window_messages:
                            self._smart_batch_snapshots[processing_id] = [
                                copy.deepcopy(_msg) for _msg in smart_window_messages
                            ]
                    break
            else:
                logger.warning(
                    f"⚠️ [Smart并发] 消息 {processing_id[:20]}... 在决策前等待更早消息超时，按当前单条消息继续"
                )

        try:
            if current_message_cache:
                self._message_cache_snapshots[early_message_id] = copy.deepcopy(
                    current_message_cache
                )
        except Exception as e:
            logger.warning(f"[并发保护] 保存缓存副本失败: {e}")

        # 步骤7: AI决策判断（第二道核心过滤）
        _welcome_skip_all = (
            (
                event.get_extra("is_welcome_message")
                and event.get_extra("welcome_message_mode") == "skip_all"
            )
            if hasattr(event, "get_extra")
            else False
        )
        _at_all_skip_all = is_at_all_message and self.at_all_message_mode == "skip_all"

        if _welcome_skip_all or _at_all_skip_all:
            should_reply = True
            if self.debug_mode:
                logger.info("【步骤7】skip_all 模式消息，跳过AI决策，强制处理")
        else:
            decision_context = formatted_context
            if self.concurrent_mode == "smart":
                smart_batch_messages = self._smart_batch_snapshots.get(early_message_id, [])
                if smart_batch_messages:
                    try:
                        decision_context = await self._format_ai_context(
                            history_messages, current_message_for_ai, event.get_self_id(),
                            window_msgs=smart_batch_messages, poke_notice=poke_notice_text,
                        )
                    except Exception as smart_ctx_err:
                        logger.warning(
                            f"[Smart并发] 决策阶段重建批次上下文失败，回退原上下文: {smart_ctx_err}"
                        )
            should_reply = await self._check_ai_decision(
                event,
                decision_context,
                is_at_message,
                has_trigger_keyword,
                merged_image_urls,
                matched_trigger_keyword=matched_trigger_keyword,
                original_message_text=original_message_text,
            )

        if not should_reply:
            # AI决策判定不通过时，将消息添加到缓存
            if cached_message_data:
                self.cache_manager.add_to_cache(chat_id, cached_message_data, source="AI决策过滤")
                logger.debug("📦 决策AI判断: 不回复此消息，已缓存消息，等待后续转正")

            # Smart 批次下被吸收但未触发回复的后续消息回落为普通缓存
            if self.concurrent_mode == "smart":
                smart_batch_messages = self._smart_batch_snapshots.pop(early_message_id, [])
                for _smart_msg in smart_batch_messages:
                    _fallback_cache = dict(_smart_msg)
                    _fallback_cache.pop("window_buffered", None)
                    _fallback_cache.pop("smart_batch_dynamic_hint", None)
                    self.cache_manager.add_to_cache(
                        chat_id, _fallback_cache, source="AI决策过滤-smart-batch"
                    )

            if self.debug_mode:
                cache_count = self.cache_manager.get_cache_count(chat_id)
                logger.info(f"  [缓存验证] 当前会话缓存数量: {cache_count} 条")

            self._message_cache_snapshots.pop(early_message_id, None)

            if self.debug_mode:
                logger.info("=" * 60)
            return

        # 并发保护：使用锁保护检查-标记流程，避免竞态条件
        message_id = processing_id
        max_wait_loops = self.concurrent_wait_max_loops
        wait_interval = self.concurrent_wait_interval

        _concurrent_waited = False
        for loop_count in range(max_wait_loops):
            if self.concurrent_mode == "smart":
                consumed = await SmartConcurrentManager.is_consumed(message_id)
                if consumed:
                    logger.info(
                        f"🔀 [Smart并发] 消息 {message_id[:20]}... 已被更早批次吸收，跳过独立回复"
                    )
                    event.call_llm = True
                    await SmartConcurrentManager.remove_self(chat_id, message_id)
                    self._message_cache_snapshots.pop(message_id, None)
                    _smart_batch_followers = self._smart_batch_snapshots.pop(message_id, None)
                    if _smart_batch_followers:
                        for _sm in _smart_batch_followers:
                            _fallback = dict(_sm)
                            _fallback.pop("window_buffered", None)
                            _fallback.pop("smart_batch_dynamic_hint", None)
                            self.cache_manager.add_to_cache(
                                chat_id, _fallback, source="Smart并发-决策后被吸收-followers"
                            )
                    if cached_message_data:
                        self.cache_manager.add_to_cache(
                            chat_id,
                            dict(cached_message_data),
                            source="Smart并发-决策后被吸收-anchor",
                        )
                    return

                if await SmartConcurrentManager.has_earlier_pending(chat_id, message_id):
                    if loop_count == 0 and self.debug_mode:
                        logger.info("🔀 [Smart并发] 检测到更早到达的消息尚未完成，等待其先成为 anchor")
                    await asyncio.sleep(wait_interval)
                    continue

            # 获取锁进行原子性检查和标记
            async with self.concurrent_lock:
                if message_id in self.processing_sessions:
                    logger.info(f"🚫 [并发去重] 消息 {message_id[:30]}... 已在处理中，跳过重复处理")
                    event.call_llm = True
                    return

                existing_processing = [
                    msg_id
                    for msg_id, cid in self.processing_sessions.items()
                    if cid == chat_id and msg_id != message_id
                ]

                if not existing_processing:
                    self.processing_sessions[message_id] = chat_id
                    if self.debug_mode:
                        logger.info(f"  已标记消息 {message_id[:30]}... 为本插件处理中")
                    break

            if loop_count == 0:
                logger.warning(
                    f"⚠️ [并发检测] 会话 {chat_id} 中有 {len(existing_processing)} 条消息正在处理中，"
                    f"开始等待（最多 {max_wait_loops} 次，每次 {wait_interval} 秒）..."
                )
            _concurrent_waited = True
            await asyncio.sleep(wait_interval)

            if self.debug_mode:
                logger.info(f"  [并发等待] 第 {loop_count + 1}/{max_wait_loops} 次检测...")
        else:
            async with self.concurrent_lock:
                still_processing = [
                    msg_id
                    for msg_id, cid in self.processing_sessions.items()
                    if cid == chat_id and msg_id != message_id
                ]
                if still_processing:
                    logger.warning(
                        f"⚠️ [并发警告] 等待 {max_wait_loops * wait_interval:.1f} 秒后仍有 "
                        f"{len(still_processing)} 条消息在处理，强制继续执行（可能产生竞争）"
                    )
                self.processing_sessions[message_id] = chat_id
                if self.debug_mode:
                    logger.info(f"  已标记消息 {message_id[:30]}... 为本插件处理中")

        # 并发等待后刷新上下文（仅当本消息确实等待过更早消息）
        if _concurrent_waited and history_messages is not None:
            try:
                _refreshed_history = await self._refresh_history_after_wait(
                    event, chat_id, history_messages, self.max_context_messages
                )
                if _refreshed_history is not None:
                    history_messages = _refreshed_history
                    _bot_id = event.get_self_id()
                    _window_buffered_msgs = (
                        self.cache_manager.get_window_buffered_messages(chat_id)
                    )
                    formatted_context = await self._format_ai_context(
                        history_messages, current_message_for_ai, _bot_id,
                        window_msgs=_window_buffered_msgs, poke_notice=poke_notice_text,
                    )
                    if self.debug_mode:
                        logger.info(
                            f"🔄 [并发刷新] 已刷新上下文，历史消息: {len(history_messages)} 条，"
                            f"上下文长度: {len(formatted_context)} 字符"
                        )
            except Exception as _refresh_err:
                logger.warning(f"🔄 [并发刷新] 刷新上下文失败，使用原始上下文: {_refresh_err}")

        # 表情包标记回退逻辑（处理跳过路径）
        if is_emoji_message and self.enable_emoji_filter and not emoji_marker_applied:
            has_image_info = bool(merged_image_urls) or (
                "[图片内容:" in message_text if message_text else False
            )
            if has_image_info and message_text and EMOJI_MARKER not in message_text:
                message_text = EmojiDetector.add_emoji_marker(message_text)
                current_message_for_ai = _build_current_message_for_ai(message_text)
                bot_id = event.get_self_id()
                formatted_context = await self._format_ai_context(
                    history_messages, current_message_for_ai, bot_id,
                    window_msgs=self.cache_manager.get_window_buffered_messages(chat_id),
                    poke_notice=poke_notice_text,
                )
                emoji_marker_applied = True

        try:
            smart_batch_reply_hint = ""
            if self.concurrent_mode == "smart":
                smart_batch_messages = self._smart_batch_snapshots.get(message_id, [])
                if smart_batch_messages:
                    try:
                        formatted_context = await self._format_ai_context(
                            history_messages, current_message_for_ai, event.get_self_id(),
                            window_msgs=smart_batch_messages, poke_notice=poke_notice_text,
                        )
                    except Exception as smart_reply_ctx_err:
                        logger.warning(
                            f"[Smart并发] 回复阶段重建批次上下文失败，回退原上下文: {smart_reply_ctx_err}"
                        )

                if (
                    self.concurrent_mode == "smart"
                    and self.enable_smart_batch_reply_hint
                    and smart_batch_messages
                ):
                    try:
                        smart_batch_summary = self._summarize_smart_batch_messages(
                            smart_batch_messages,
                            anchor_sender_id=event.get_sender_id(),
                        )
                        smart_batch_reply_hint = self._build_smart_batch_reply_hint(
                            event, smart_batch_summary
                        )
                    except Exception as smart_hint_err:
                        logger.warning(
                            f"[Smart并发] 生成批次回复提示失败，降级忽略: {smart_hint_err}"
                        )
                        smart_batch_reply_hint = ""

            async for result in self._generate_and_send_reply(
                event,
                formatted_context,
                message_text,
                platform_name,
                is_private,
                chat_id,
                is_at_message,
                has_trigger_keyword,
                merged_image_urls,
                history_messages,
                current_message_cache,
                smart_batch_reply_hint=smart_batch_reply_hint,
            ):
                yield result
        finally:
            async with self.concurrent_lock:
                owner = self._chat_flow_owners.get(chat_id)
                if owner and owner.get("processing_id") == message_id:
                    self._chat_flow_owners.pop(chat_id, None)

            if self.concurrent_mode == "smart":
                await SmartConcurrentManager.remove_self(chat_id, message_id)

    # ============================================================
    # 初始检查与触发器
    # ============================================================

    async def _perform_initial_checks(self, event: AstrMessageEvent) -> tuple:
        """
        执行初始检查

        Returns:
            (should_continue, platform_name, is_private, chat_id)
        """
        if self.debug_mode:
            logger.info("=" * 60)
            logger.info("【步骤1】开始基础检查")

        if not self._is_enabled(event):
            if self.debug_mode:
                logger.info("【步骤1】群组未启用插件,跳过处理")
            return False, None, None, None

        if MessageProcessor.is_message_from_bot(event):
            if self.debug_mode:
                logger.info("忽略机器人自己的消息")
            return False, None, None, None

        platform_name = event.get_platform_name()
        is_private = event.is_private_chat()
        chat_id = event.get_group_id() if not is_private else event.get_sender_id()

        if self.debug_mode:
            logger.info("【步骤1】基础信息:")
            logger.info(f"  平台: {platform_name}")
            logger.info(f"  类型: {'私聊' if is_private else '群聊'}")
            logger.info(f"  会话ID: {chat_id}")
            logger.info(f"  发送者: {event.get_sender_name()}({event.get_sender_id()})")

        # 黑名单关键词检查
        blacklist_keywords = self.blacklist_keywords
        if KeywordChecker.check_blacklist_keywords(event, blacklist_keywords):
            if self.debug_mode:
                logger.info("【步骤2】黑名单关键词匹配，丢弃消息")
                logger.info("=" * 60)
            return False, None, None, None

        return True, platform_name, is_private, chat_id

    async def _check_message_triggers(self, event: AstrMessageEvent) -> tuple:
        """
        检查消息触发器（@消息和触发关键词）

        Returns:
            (is_at_message, has_trigger_keyword, matched_trigger_keyword)
        """
        is_at_message = MessageProcessor.is_at_message(event)

        if self.debug_mode:
            logger.info(f"【步骤3】@消息检测: {'是@消息' if is_at_message else '非@消息'}")

        trigger_keywords = self.trigger_keywords
        has_trigger_keyword, matched_trigger_keyword = (
            KeywordChecker.check_trigger_keywords_with_match(event, trigger_keywords)
        )

        if has_trigger_keyword:
            if self.debug_mode:
                logger.info(
                    f"【步骤4】检测到触发关键词: {matched_trigger_keyword}，跳过读空气判断"
                )

        return is_at_message, has_trigger_keyword, matched_trigger_keyword

    # ============================================================
    # 概率判断
    # ============================================================

    async def _check_probability_before_processing(
        self,
        event: AstrMessageEvent,
        platform_name: str,
        is_private: bool,
        chat_id: str,
        is_at_message: bool,
        has_trigger_keyword: bool,
        poke_info: dict = None,
        is_emoji_message: bool = False,
        is_at_all_message: bool = False,
    ) -> bool:
        """
        执行概率判断（在图片处理之前）

        Returns:
            True=继续处理, False=丢弃消息
        """
        # 戳机器人的特殊处理：配置允许时跳过概率判断
        skip_probability_for_poke = False
        if poke_info and self.poke_bot_skip_probability:
            inner_poke_info = poke_info.get("poke_info", {})
            if inner_poke_info.get("is_poke_bot"):
                skip_probability_for_poke = True

        # 新成员入群消息的特殊处理
        skip_probability_for_welcome = False
        is_welcome_message = (
            event.get_extra("is_welcome_message") if hasattr(event, "get_extra") else False
        )
        welcome_mode = (
            event.get_extra("welcome_message_mode")
            if hasattr(event, "get_extra")
            else "normal"
        )
        if is_welcome_message and welcome_mode in ("skip_probability", "skip_all"):
            skip_probability_for_welcome = True

        # @全体成员消息的特殊处理
        skip_probability_for_at_all = False
        at_all_transient_probability_boost = 0.0
        if is_at_all_message:
            at_all_mode = str(self.at_all_message_mode or "skip_probability")
            if at_all_mode in ("skip_probability", "skip_all"):
                skip_probability_for_at_all = True
            elif at_all_mode == "probability_boost":
                at_all_transient_probability_boost = max(
                    0.0, min(1.0, self.at_all_probability_boost_value)
                )

        # 随机读空气筛选总开关：关闭时普通消息也直接交给 AI 人格判断（AI 全权主导）
        random_filter_active = self.enable_random_probability_filter
        if (
            not is_at_message
            and not has_trigger_keyword
            and not skip_probability_for_poke
            and not skip_probability_for_welcome
            and not skip_probability_for_at_all
            and random_filter_active
        ):
            if self.debug_mode:
                logger.info("【步骤5】开始读空气概率判断")

            should_process = await self._check_probability(
                platform_name,
                is_private,
                chat_id,
                event,
                poke_info=poke_info,
                is_emoji_message=is_emoji_message,
                transient_probability_boost=at_all_transient_probability_boost,
            )
            if not should_process:
                logger.info("【步骤5】未通过概率筛选，消息已缓存（避免上下文断裂）")
                if self.debug_mode:
                    logger.info("=" * 60)
                return False

            logger.info("读空气概率判断: 决定处理此消息")
        else:
            if not random_filter_active and self.debug_mode:
                logger.info("【步骤5】随机概率筛选已关闭（AI 判断全权主导），普通消息直接进入 AI 判断")
            if is_at_message and self.debug_mode:
                logger.info("【步骤5】@消息,跳过概率判断,必定处理")
            if has_trigger_keyword and self.debug_mode:
                keyword_smart_mode = self.keyword_smart_mode
                if keyword_smart_mode:
                    logger.info("【步骤5】触发关键词消息(智能模式),跳过概率判断,但保留读空气判断")
                else:
                    logger.info("【步骤5】触发关键词消息,跳过概率判断,必定处理")

        return True

    async def _check_probability(
        self,
        platform_name: str,
        is_private: bool,
        chat_id: str,
        event: AstrMessageEvent,
        poke_info: dict = None,
        is_emoji_message: bool = False,
        transient_probability_boost: float = 0.0,
    ) -> bool:
        """
        读空气概率检查，决定是否处理消息

        Returns:
            True=处理，False=跳过
        """
        current_probability = await ProbabilityManager.get_current_probability(
            platform_name,
            is_private,
            chat_id,
            self.initial_probability,
        )

        if self.debug_mode:
            logger.info(f"  当前概率: {current_probability:.2f}")
            logger.info(f"  初始概率: {self.initial_probability:.2f}")

        # 表情包概率衰减
        if is_emoji_message and self.enable_emoji_filter:
            if current_probability >= self.emoji_decay_min_probability:
                old_probability = current_probability
                decay_factor = max(0.0, 1.0 - self.emoji_probability_decay)
                current_probability = current_probability * decay_factor
                logger.info(
                    f"  【表情包衰减】检测到表情包，概率衰减: "
                    f"{old_probability:.2f} -> {current_probability:.2f} "
                    f"(衰减因子={self.emoji_probability_decay}, 乘数={decay_factor:.2f})"
                )

        # @全体成员临时概率提升
        if transient_probability_boost > 0:
            old_probability = current_probability
            current_probability = current_probability + transient_probability_boost
            logger.info(
                f"  【@全体成员-当前消息临时提升】概率调整: {old_probability:.2f} -> {current_probability:.2f} "
                f"(+{transient_probability_boost:.2f})"
            )

        # 系统硬性边界 [0, 1]
        current_probability = max(0.0, min(1.0, current_probability))

        # 随机判断
        roll = random.random()
        should_process = roll < current_probability
        if self.debug_mode:
            logger.info(
                f"读空气概率检查: 当前概率={current_probability:.2f}, 随机值={roll:.2f}, 结果={'触发' if should_process else '未触发'}"
            )

        return should_process

    # ============================================================
    # AI决策判断（读空气）
    # ============================================================

    async def _check_ai_decision(
        self,
        event: AstrMessageEvent,
        formatted_context: str,
        is_at_message: bool,
        has_trigger_keyword: bool,
        image_urls: Optional[List[str]] = None,
        matched_trigger_keyword: str = "",
        original_message_text: str = "",
    ) -> bool:
        """
        执行AI决策判断（在处理完消息内容后）

        Returns:
            True=应该回复, False=不回复
        """
        keyword_smart_mode = self.keyword_smart_mode

        platform_name = event.get_platform_name()
        is_private = event.is_private_chat()
        chat_id = event.get_group_id() if not is_private else event.get_sender_id()

        # 在读空气AI之前注入记忆（可选，pre_decision 模式）
        decision_formatted_context = formatted_context
        if (
            self.enable_memory_injection
            and self.memory_insertion_timing == "pre_decision"
        ):
            memory_mode = self.memory_plugin_mode
            livingmemory_top_k = self.livingmemory_top_k
            livingmemory_version = self.livingmemory_version
            livingmemory_persona_compat_mode = self.livingmemory_persona_compat_mode

            memory_mode, livingmemory_version = MemoryInjector.resolve_mode(
                self.context, memory_mode, livingmemory_version
            )

            if memory_mode is None:
                if self.debug_mode:
                    logger.info("[决策AI] auto模式未检测到可用的记忆插件，跳过记忆注入")
            elif MemoryInjector.check_memory_plugin_available(
                self.context, mode=memory_mode, version=livingmemory_version
            ):
                try:
                    memories = await MemoryInjector.get_memories(
                        self.context,
                        event,
                        mode=memory_mode,
                        top_k=livingmemory_top_k,
                        version=livingmemory_version,
                        persona_compat_mode=livingmemory_persona_compat_mode,
                    )
                    mem_text = str(memories).strip() if memories is not None else ""
                    if mem_text and ("当前没有任何记忆" not in mem_text):
                        old_len = len(decision_formatted_context)
                        decision_formatted_context = (
                            MemoryInjector.inject_memories_to_message(
                                decision_formatted_context, mem_text
                            )
                        )
                        if self.debug_mode:
                            logger.info(
                                f"[决策AI] 已在判定前注入记忆({memory_mode}模式)，长度增加: {len(decision_formatted_context) - old_len} 字符"
                            )
                        try:
                            ckey = ProbabilityManager.get_chat_key(
                                platform_name, is_private, chat_id
                            )
                            if not hasattr(self, "_pre_decision_context_by_chat"):
                                self._pre_decision_context_by_chat = {}
                            self._pre_decision_context_by_chat[ckey] = (
                                decision_formatted_context
                            )
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(f"[决策AI] 判定前注入记忆失败: {e}", exc_info=True)
            elif self.debug_mode:
                logger.info(f"[决策AI] 记忆插件({memory_mode}模式)不可用，判定前跳过记忆注入")

        # 判断是否需要进行AI决策
        # 所有消息一律交给读空气AI按人格判断：@、触发关键词（bot名/“璃月”等）都只是
        # 判断上下文里的信息，不因命中而必回；keyword_smart_mode=关时关键词命中才按“必回”处理
        should_do_ai_decision = keyword_smart_mode or not has_trigger_keyword

        if should_do_ai_decision:
            if self.debug_mode:
                logger.info("【步骤9】调用决策AI判断是否回复")

            _decision_start = time.time()

            # 判断是否通过关键词触发（智能模式下）
            is_keyword_triggered = has_trigger_keyword and keyword_smart_mode

            should_reply = await DecisionAI.should_reply(
                self.context,
                event,
                decision_formatted_context,
                self.decision_ai_provider_id,
                self.decision_ai_extra_prompt,
                self.decision_ai_timeout,
                self.decision_ai_prompt_mode,
                image_urls=image_urls,
                include_sender_info=self.include_sender_info,
                is_keyword_triggered=is_keyword_triggered,
                matched_keyword=matched_trigger_keyword,
                enable_reasoning=self.enable_decision_ai_reasoning,
                reasoning_log_enabled=self.decision_ai_reasoning_log,
                reasoning_log_mode=self.decision_ai_reasoning_log_mode,
                reasoning_start_marker=self.judgment_reasoning_start_marker,
                reasoning_end_marker=self.judgment_reasoning_end_marker,
                include_persona=self.decision_ai_include_persona,
                configured_persona_name=self.decision_ai_persona_name,
                reply_tendency=self.decision_ai_reply_tendency,
            )

            if self.debug_mode:
                _decision_elapsed = time.time() - _decision_start
                logger.info(f"【步骤9】决策AI判断完成，耗时: {_decision_elapsed:.2f}秒")

            if not should_reply:
                logger.debug("决策AI判断: 不应该回复此消息")
                # 清理pre_decision缓存（防止内存残留）
                try:
                    ckey = ProbabilityManager.get_chat_key(
                        platform_name, is_private, chat_id
                    )
                    if (
                        hasattr(self, "_pre_decision_context_by_chat")
                        and ckey in self._pre_decision_context_by_chat
                    ):
                        del self._pre_decision_context_by_chat[ckey]
                except Exception:
                    pass
                return False

            logger.debug("决策AI判断: 应该回复此消息")
            return True
        else:
            if self.debug_mode and has_trigger_keyword and not keyword_smart_mode:
                logger.info("【步骤9】触发关键词(非智能模式),跳过AI决策,必定回复")
            try:
                ckey = ProbabilityManager.get_chat_key(
                    platform_name, is_private, chat_id
                )
                if not hasattr(self, "_ai_decision_skipped"):
                    self._ai_decision_skipped = set()
                self._ai_decision_skipped.add(ckey)
            except Exception:
                pass
            return True

    # ============================================================
    # 消息内容处理
    # ============================================================

    async def _process_message_content(
        self,
        event: AstrMessageEvent,
        chat_id: str,
        current_group_seq: int,
        is_at_message: bool,
        mention_info: dict = None,
        has_trigger_keyword: bool = False,
        poke_info: dict = None,
        raw_is_at_message: bool = None,
        is_emoji_message: bool = False,
        is_at_all_message: bool = False,
        persistent_poke_event_text: str = "",
    ) -> tuple:
        """
        处理消息内容（图片处理、上下文格式化）

        Returns:
            (should_continue, original_message_text, processed_message, formatted_context,
             image_urls, history_messages, cached_message, emoji_marker_applied)
        """
        if self.debug_mode:
            logger.info("【步骤6】提取纯净原始消息")

        original_message_text = MessageCleaner.extract_raw_message_from_event(
            event, self_id=str(event.get_self_id())
        )
        if self.debug_mode:
            logger.info(f"  纯净原始消息: {original_message_text[:100]}...")

        real_is_at_message = (
            raw_is_at_message if raw_is_at_message is not None else is_at_message
        )

        # only_ai: 只把"只包含@AI且没有他人/全体/正文"的空消息视为单独无信息@AI
        is_empty_at = MessageCleaner.is_empty_at_message(
            original_message_text,
            real_is_at_message,
            mention_info=mention_info,
            mode="only_ai",
        )
        if is_empty_at and self.debug_mode:
            logger.info("  纯@消息将使用特殊处理")

        # 处理图片
        if self.debug_mode:
            logger.info("【步骤6.5】处理图片内容")

        (
            should_continue,
            processed_message,
            image_urls,
            image_retained,
        ) = await ImageHandler.process_message_images(
            event,
            self.context,
            self.enable_image_processing,
            self.image_to_text_scope,
            self.image_to_text_provider_id,
            self.image_to_text_prompt,
            real_is_at_message,
            has_trigger_keyword,
            self.image_to_text_timeout,
            self.image_description_cache,
            self.max_images_per_message,
            self_id=str(event.get_self_id()),
        )

        if not should_continue:
            logger.info("图片处理后决定丢弃此消息（图片被过滤或处理失败）")
            if self.debug_mode:
                logger.info("【步骤6.5】图片处理判定丢弃消息，不缓存")
                logger.info("=" * 60)
            return False, None, None, None, None, None, None, False, {}

        # 提取非图片媒体文件（语音/视频/文件）的路径并内联注入
        _media_audio_urls: list = []
        try:
            (_media_audio_urls, _media_video_paths, _media_file_infos) = (
                await ImageHandler.extract_media_urls(event)
            )
            if _media_audio_urls or _media_video_paths or _media_file_infos:
                processed_message = ImageHandler.enrich_media_markers(
                    processed_message,
                    audio_urls=_media_audio_urls,
                    video_paths=_media_video_paths,
                    file_infos=_media_file_infos,
                )
                event.set_extra("_plugin_media_audio_urls", _media_audio_urls)
                if self.debug_mode:
                    logger.info(
                        f"【步骤6.45】提取非图片媒体: audio={len(_media_audio_urls)}个, "
                        f"video={len(_media_video_paths)}个, file={len(_media_file_infos)}个"
                    )
        except Exception as e:
            logger.warning(f"[媒体提取] 提取非图片媒体文件时出错（已跳过）: {e}")

        # 表情包标记注入（正常处理路径）
        emoji_marker_applied = False
        if is_emoji_message and self.enable_emoji_filter and image_retained:
            if processed_message:
                processed_message = EmojiDetector.add_emoji_marker(processed_message)
            else:
                processed_message = EmojiDetector.add_emoji_marker("")
            emoji_marker_applied = True

        current_message_id = self._get_processing_id(event)

        # 准备待缓存的用户消息数据
        cached_message = {
            "role": "user",
            "content": processed_message,
            "timestamp": time.time(),
            "message_id": current_message_id,
            "sender_id": event.get_sender_id(),
            "sender_name": event.get_sender_name(),
            "message_timestamp": event.message_obj.timestamp
            if hasattr(event, "message_obj") and hasattr(event.message_obj, "timestamp")
            else None,
            "mention_info": mention_info,
            "group_seq": current_group_seq,
            "is_at_message": is_at_message,
            "has_trigger_keyword": has_trigger_keyword,
            "poke_info": poke_info,
            "persistent_poke_event_text": persistent_poke_event_text,
            "image_urls": image_urls or [],
            "audio_urls": _media_audio_urls,
            "is_at_all_message": is_at_all_message,
            "is_empty_at": is_empty_at,
        }

        # 确定触发方式
        trigger_type = None
        if has_trigger_keyword:
            trigger_type = "keyword"
        elif is_at_message:
            trigger_type = "at"
        else:
            trigger_type = "ai_decision"

        # 戳过对方追踪提示
        poke_trace_text = ""
        if (
            self.poke_trace_enabled
            and self._is_poke_enabled_in_group(chat_id)
            and self._check_and_consume_poke_trace(chat_id, event.get_sender_id())
        ):
            _n = self._safe_sender_display(event)
            _id = event.get_sender_id()
            poke_trace_text = f"[戳过对方提示]你刚刚戳过这条消息的发送者{_n}(ID:{_id})"

        message_text_for_ai = MessageProcessor.add_metadata_to_message(
            event,
            processed_message,
            self.include_timestamp,
            self.include_sender_info,
            mention_info,
            trigger_type,
            poke_info,
            is_empty_at,
            "",
            "",
            is_at_all_message=is_at_all_message,
            persistent_poke_event_text=persistent_poke_event_text,
            poke_trace_text=poke_trace_text,
        )

        # [戳一戳提示] 由 format_context_for_ai 追加到分隔符之外
        _poke_notice_text = ""
        if poke_info and isinstance(poke_info, dict):
            try:
                _is_poke_bot = poke_info.get("is_poke_bot", False)
                _sender_id = str(poke_info.get("sender_id", "") or "")
                _sender_name = (
                    str(poke_info.get("sender_name", "") or "").strip() or "未知用户"
                )
                _sender_display = (
                    f"{_sender_name}(ID:{_sender_id})" if _sender_id else _sender_name
                )
                _target_id = str(poke_info.get("target_id", "") or "")
                _target_name = (
                    str(poke_info.get("target_name", "") or "").strip() or "未知用户"
                )
                _target_display = (
                    f"{_target_name}(ID:{_target_id})" if _target_id else _target_name
                )
                if _is_poke_bot:
                    _poke_notice_text = (
                        f"[戳一戳提示]有人在戳你，戳你的人是{_sender_display}"
                    )
                else:
                    _poke_notice_text = f"[戳一戳提示]这是一个戳一戳消息，但不是戳你的，是{_sender_display}在戳{_target_display}"
            except Exception:
                _poke_notice_text = ""

        if self.debug_mode:
            logger.info("【步骤7.5】为当前消息添加元数据（用于AI识别）")
            logger.info(f"  添加元数据后: {message_text_for_ai[:150]}...")

        # 提取历史上下文
        max_context = self.max_context_messages

        # 配置矫正
        if not isinstance(max_context, int):
            try:
                max_context = int(max_context)
            except (ValueError, TypeError):
                max_context = -1
        if isinstance(max_context, int) and max_context < -1:
            max_context = -1

        if self.debug_mode:
            logger.info("【步骤8】提取历史上下文")

        # 获取历史消息（统一方法：优先官方存储，回退自定义存储）
        if isinstance(max_context, int) and max_context == 0:
            history_messages = []
        else:
            history_messages = await ContextManager.get_history_messages_with_fallback(
                event=event,
                max_messages=max_context,
                context=self.context,
                cached_messages=[],
            )
            # 兼容性代码：尝试从 conversation_manager 获取额外的官方对话历史
            try:
                cm = self.context.conversation_manager
                if cm:
                    uid = event.unified_msg_origin
                    cid = await cm.get_curr_conversation_id(uid)
                    if cid:
                        conv = await cm.get_conversation(
                            unified_msg_origin=uid, conversation_id=cid
                        )
                        official_history = None
                        if conv is not None:
                            if getattr(conv, "history", None):
                                try:
                                    official_history = json.loads(conv.history)
                                except Exception:
                                    official_history = None
                            if official_history is None and getattr(conv, "content", None):
                                if isinstance(conv.content, list):
                                    official_history = conv.content
                                else:
                                    try:
                                        official_history = json.loads(conv.content)
                                    except Exception:
                                        official_history = None
                        if isinstance(official_history, list) and len(official_history) > 0:
                            hist_msgs = []
                            self_id = event.get_self_id()
                            platform_name = event.get_platform_name()
                            is_private_chat = event.is_private_chat()
                            default_user_name = "对方" if is_private_chat else "群友"
                            if isinstance(max_context, int):
                                if max_context == -1:
                                    msgs_iter = official_history
                                elif max_context > 0:
                                    msgs_iter = official_history[-max_context:]
                                else:
                                    msgs_iter = []
                            else:
                                msgs_iter = official_history
                            for idx, msg in enumerate(msgs_iter):
                                if (
                                    isinstance(msg, dict)
                                    and "role" in msg
                                    and "content" in msg
                                ):
                                    m = AstrBotMessage()
                                    m.message_str = ContextManager._content_to_safe_text(
                                        msg.get("content")
                                    )
                                    m.platform_name = platform_name
                                    _ts = (
                                        msg.get("timestamp")
                                        or msg.get("ts")
                                        or msg.get("time")
                                    )
                                    try:
                                        m.timestamp = (
                                            int(float(_ts)) if _ts else int(time.time())
                                        )
                                    except Exception:
                                        m.timestamp = int(time.time())
                                    m.type = (
                                        MessageType.GROUP_MESSAGE
                                        if not is_private_chat
                                        else MessageType.FRIEND_MESSAGE
                                    )
                                    if not is_private_chat:
                                        m.group_id = event.get_group_id()
                                    m.self_id = self_id
                                    m.session_id = getattr(
                                        event, "session_id", None
                                    ) or (
                                        event.get_sender_id()
                                        if is_private_chat
                                        else event.get_group_id()
                                    )
                                    raw_message_id = (
                                        msg.get("message_id")
                                        or msg.get("id")
                                        or msg.get("mid")
                                        or ""
                                    )
                                    m.message_id = (
                                        str(raw_message_id)
                                        or f"official_{idx}_{m.timestamp}"
                                    )
                                    if msg["role"] == "assistant":
                                        m.sender = MessageMember(
                                            user_id=self_id, nickname="AI"
                                        )
                                    else:
                                        sender_info = (
                                            msg.get("sender")
                                            if isinstance(msg.get("sender"), dict)
                                            else None
                                        )
                                        sender_id = None
                                        sender_name = None
                                        if sender_info:
                                            sender_id = (
                                                sender_info.get("user_id")
                                                or sender_info.get("id")
                                                or sender_info.get("uid")
                                                or sender_info.get("qq")
                                                or sender_info.get("uin")
                                            )
                                            sender_name = sender_info.get(
                                                "nickname"
                                            ) or sender_info.get("name")
                                        sender_id = (
                                            str(sender_id)
                                            if sender_id is not None
                                            else f"history_user_{idx}"
                                        )
                                        sender_name = sender_name or default_user_name
                                        m.sender = MessageMember(
                                            user_id=sender_id, nickname=sender_name
                                        )
                                    hist_msgs.append(m)
                            # 按历史截止时间戳过滤
                            _cutoff_ts = ContextManager.get_history_cutoff(chat_id)
                            if _cutoff_ts > 0 and hist_msgs:
                                hist_msgs = [
                                    _m
                                    for _m in hist_msgs
                                    if (getattr(_m, "timestamp", 0) or 0) >= _cutoff_ts
                                ]
                            if hist_msgs:
                                if history_messages:
                                    existing_contents = set()
                                    for _existing in history_messages:
                                        content = None
                                        if isinstance(_existing, AstrBotMessage):
                                            content = getattr(
                                                _existing, "message_str", None
                                            )
                                        elif isinstance(_existing, dict):
                                            content = (
                                                ContextManager._make_content_hashable(
                                                    _existing.get("content")
                                                )
                                            )
                                        if content is not None:
                                            existing_contents.add(content)
                                    for hm in hist_msgs:
                                        if (
                                            hm.message_str
                                            and hm.message_str in existing_contents
                                        ):
                                            continue
                                        history_messages.append(hm)
                                        if hm.message_str:
                                            existing_contents.add(hm.message_str)
                                else:
                                    history_messages = hist_msgs
            except Exception:
                pass

        # 使用缓存管理器合并缓存消息
        if isinstance(max_context, int) and max_context == 0:
            if self.debug_mode:
                logger.info("  跳过缓存合并: max_context_messages=0")
        else:
            history_messages, cached_count, dedup_skipped = (
                self.cache_manager.merge_cache_to_history(
                    chat_id=chat_id,
                    history_messages=history_messages,
                    event=event,
                    current_message_id=None,
                )
            )
            if self.debug_mode and cached_count > 0:
                logger.info(f"  [缓存管理器] 已合并 {cached_count} 条缓存消息到历史")

        # 应用上下文限制（按时间保留最新的）
        if (
            history_messages
            and isinstance(max_context, int)
            and max_context > 0
            and len(history_messages) > max_context
        ):
            history_messages = history_messages[-max_context:]

        if self.debug_mode:
            logger.info(
                f"  最终历史消息: {len(history_messages) if history_messages else 0} 条"
            )

        # 获取窗口缓冲消息（Smart批次）
        window_buffered_msgs = self.cache_manager.get_window_buffered_messages(chat_id)

        # 格式化上下文
        bot_id = event.get_self_id()
        formatted_context = await self._format_ai_context(
            history_messages, message_text_for_ai, bot_id,
            window_msgs=window_buffered_msgs, poke_notice=_poke_notice_text,
        )

        if self.debug_mode:
            logger.info(f"  格式化后长度: {len(formatted_context)} 字符")

        return (
            True,
            original_message_text,
            processed_message,
            formatted_context,
            image_urls,
            history_messages,
            cached_message,
            emoji_marker_applied,
        )

    # ============================================================
    # 生成并发送回复
    # ============================================================

    async def _generate_and_send_reply(
        self,
        event: AstrMessageEvent,
        formatted_context: str,
        message_text: str,
        platform_name: str,
        is_private: bool,
        chat_id: str,
        is_at_message: bool = False,
        has_trigger_keyword: bool = False,
        image_urls: list = None,
        history_messages: list = None,
        current_message_cache: dict = None,
        smart_batch_reply_hint: str = "",
    ):
        """
        生成并发送回复，保存历史

        Returns:
            生成器，用于yield回复
        """
        _process_start_time = time.time()

        if image_urls is None:
            image_urls = []

        # 注入记忆
        final_message = formatted_context
        try:
            ckey = ProbabilityManager.get_chat_key(platform_name, is_private, chat_id)

            # pre_decision 模式下，优先使用缓存的上下文（已植入记忆）
            if (
                self.enable_memory_injection
                and self.memory_insertion_timing == "pre_decision"
            ):
                if (
                    hasattr(self, "_pre_decision_context_by_chat")
                    and ckey in self._pre_decision_context_by_chat
                ):
                    final_message = self._pre_decision_context_by_chat.pop(
                        ckey, formatted_context
                    )

            # 清理跳过决策AI的标记
            if hasattr(self, "_ai_decision_skipped") and ckey in self._ai_decision_skipped:
                try:
                    self._ai_decision_skipped.discard(ckey)
                except Exception:
                    pass
        except Exception:
            pass

        if (
            self.enable_memory_injection
            and self.memory_insertion_timing == "post_decision"
        ):
            if self.debug_mode:
                logger.info("【步骤11】注入记忆内容")

            memory_mode = self.memory_plugin_mode
            livingmemory_top_k = self.livingmemory_top_k
            livingmemory_version = self.livingmemory_version
            livingmemory_persona_compat_mode = self.livingmemory_persona_compat_mode

            memory_mode, livingmemory_version = MemoryInjector.resolve_mode(
                self.context, memory_mode, livingmemory_version
            )

            if memory_mode is None:
                if self.debug_mode:
                    logger.info("  auto模式未检测到可用的记忆插件，跳过记忆注入")
            elif MemoryInjector.check_memory_plugin_available(
                self.context, mode=memory_mode, version=livingmemory_version
            ):
                memories = await MemoryInjector.get_memories(
                    self.context,
                    event,
                    mode=memory_mode,
                    top_k=livingmemory_top_k,
                    version=livingmemory_version,
                    persona_compat_mode=livingmemory_persona_compat_mode,
                )
                if memories:
                    final_message = MemoryInjector.inject_memories_to_message(
                        final_message, memories
                    )
                    if self.debug_mode:
                        logger.info(
                            f"  已注入记忆({memory_mode}模式),长度增加: {len(final_message) - len(formatted_context)} 字符"
                        )
            else:
                logger.warning(f"记忆插件({memory_mode}模式)未安装或不可用,跳过记忆注入")

        # 调用AI生成回复
        if self.debug_mode:
            logger.info("【步骤13】调用AI生成回复")
            logger.info(f"  最终消息长度: {len(final_message)} 字符")

        _start_time = time.time()

        ai_error_flag = False
        message_id_for_error = None
        try:
            message_id_for_error = self._get_processing_id(event)
        except Exception:
            message_id_for_error = None

        try:
            # 从 event extras 读取语音URL（视频/文件路径已内联到 final_message 中）
            _media_audio_urls = event.get_extra("_plugin_media_audio_urls", []) or []

            reply_result = await ReplyHandler.generate_reply(
                event,
                self.context,
                final_message,
                self.reply_ai_extra_prompt,
                self.reply_ai_prompt_mode,
                image_urls,
                audio_urls=_media_audio_urls,
                include_sender_info=self.include_sender_info,
                include_timestamp=self.include_timestamp,
                history_messages=history_messages,
                smart_batch_reply_hint=smart_batch_reply_hint,
            )
        except Exception as e:
            ai_error_flag = True
            logger.error(f"生成AI回复时发生未捕获异常: {e}", exc_info=True)
            reply_result = event.plain_result(f"生成回复时发生错误: {str(e)}")

        if (
            not ai_error_flag
            and hasattr(reply_result, "is_llm_result")
            and hasattr(reply_result, "chain")
        ):
            try:
                if not reply_result.is_llm_result():
                    parts = []
                    for comp in getattr(reply_result, "chain", []) or []:
                        text = self._coerce_component_text(getattr(comp, "text", None))
                        if text:
                            parts.append(text)
                    err_text = "".join(parts)
                    if "生成回复时发生错误" in err_text:
                        ai_error_flag = True
            except Exception:
                pass

        if ai_error_flag and message_id_for_error:
            try:
                self._ai_error_message_ids.add(message_id_for_error)
            except Exception:
                pass

        _elapsed = time.time() - _start_time
        if self.debug_mode:
            logger.info(f"【步骤13】AI回复生成完成，耗时: {_elapsed:.2f}秒")
        elif _elapsed > self.reply_generation_timeout_warning:
            logger.warning(
                f"⚠️ AI回复生成耗时异常: {_elapsed:.2f}秒（超过{self.reply_generation_timeout_warning}秒）"
            )

        # 保存用户消息（从缓存读取并添加元数据）
        if self.debug_mode:
            logger.info("【步骤14】保存用户消息")

        try:
            message_to_save = ""
            last_cached = current_message_cache

            if not last_cached:
                msg_id_for_lookup = self._get_processing_id(event)
                if chat_id in self.pending_messages_cache:
                    for cached_msg in reversed(self.pending_messages_cache[chat_id]):
                        if (
                            isinstance(cached_msg, dict)
                            and cached_msg.get("message_id") == msg_id_for_lookup
                        ):
                            last_cached = cached_msg
                            break

            if (
                last_cached
                and isinstance(last_cached, dict)
                and "content" in last_cached
            ):
                raw_content = last_cached["content"]

                trigger_type = None
                if last_cached.get("has_trigger_keyword"):
                    trigger_type = "keyword"
                elif last_cached.get("is_at_message"):
                    trigger_type = "at"
                else:
                    trigger_type = "ai_decision"

                message_to_save = MessageProcessor.add_metadata_from_cache(
                    raw_content,
                    last_cached.get("sender_id", event.get_sender_id()),
                    last_cached.get("sender_name", event.get_sender_name()),
                    last_cached.get("message_timestamp") or last_cached.get("timestamp"),
                    self.include_timestamp,
                    self.include_sender_info,
                    last_cached.get("mention_info"),
                    trigger_type,
                    last_cached.get("poke_info"),
                    last_cached.get("is_empty_at", False),
                    "",
                    last_cached.get("is_at_all_message", False),
                    persistent_poke_event_text=last_cached.get(
                        "persistent_poke_event_text", ""
                    ),
                )
                message_to_save = MessageCleaner.clean_message(message_to_save)

            # 如果从缓存获取失败，使用当前处理后的消息
            if not message_to_save:
                logger.warning("⚠️ 缓存中无消息，使用当前处理后的消息（这不应该发生！）")
                trigger_type = None
                if has_trigger_keyword:
                    trigger_type = "keyword"
                elif is_at_message:
                    trigger_type = "at"
                else:
                    trigger_type = "ai_decision"

                _fb_mention_info = (
                    last_cached.get("mention_info")
                    if isinstance(last_cached, dict)
                    else None
                )
                _fb_at_all = bool(
                    last_cached.get("is_at_all_message", False)
                    if isinstance(last_cached, dict)
                    else False
                )
                message_to_save = MessageProcessor.add_metadata_to_message(
                    event,
                    message_text,
                    self.include_timestamp,
                    self.include_sender_info,
                    _fb_mention_info,
                    trigger_type,
                    None,
                    False,
                    "",
                    "",
                    is_at_all_message=_fb_at_all,
                    persistent_poke_event_text=last_cached.get(
                        "persistent_poke_event_text", ""
                    )
                    if last_cached
                    else "",
                )
                message_to_save = MessageCleaner.clean_message(message_to_save)

            if self.debug_mode:
                logger.info(f"  准备保存的完整消息: {message_to_save[:300]}...")

            await ContextManager.save_user_message(
                event, message_to_save, self.context, skip_custom_storage=True
            )
        except Exception as e:
            logger.error(f"保存用户消息时发生错误: {e}", exc_info=True)

        # 发送前过滤检查：防止直接转发用户消息和重复发送相同回复
        reply_text = ""
        is_provider_request = False
        if reply_result:
            is_provider_request = isinstance(reply_result, ProviderRequest)
            if isinstance(reply_result, str):
                reply_text = reply_result.strip()

        # 检查1: 回复是否与用户消息相同（防止直接转发）
        if reply_text and not is_provider_request:
            user_message_clean = message_text.strip()
            if reply_text == user_message_clean:
                logger.info("[消息过滤]回复与用户消息相同，已过滤")
                if event.is_at_or_wake_command:
                    event.call_llm = True
                return

        # 检查2: 回复是否与最近发送的回复重复
        is_duplicate_blocked = False
        if reply_text and not is_provider_request and self.enable_duplicate_filter:
            if chat_id not in self.recent_replies_cache:
                self.recent_replies_cache[chat_id] = []

            current_time = time.time()
            if self.enable_duplicate_time_limit:
                time_limit = max(60, self.duplicate_filter_time_limit)
                self.recent_replies_cache[chat_id] = [
                    reply
                    for reply in self.recent_replies_cache[chat_id]
                    if current_time - reply.get("timestamp", 0) < time_limit
                ]

            check_count = max(1, self.duplicate_filter_check_count)
            for recent_reply in self.recent_replies_cache[chat_id][-check_count:]:
                recent_content = recent_reply.get("content", "")
                recent_timestamp = recent_reply.get("timestamp", 0)
                if self.enable_duplicate_time_limit:
                    time_limit = max(60, self.duplicate_filter_time_limit)
                    if current_time - recent_timestamp >= time_limit:
                        continue
                if recent_content and reply_text == recent_content.strip():
                    logger.info("[消息过滤]回复与最近发送的回复重复，已拦截发送（后续流程继续执行）")
                    is_duplicate_blocked = True
                    break

        # 发送回复
        if not is_duplicate_blocked:
            if reply_result is None:
                logger.error("❌ [发送失败] reply_result为None，无法发送回复")
                if event.is_at_or_wake_command:
                    event.call_llm = True
                return

            if self.debug_mode:
                logger.info(f"【步骤13.9】准备发送回复，类型: {type(reply_result).__name__}")

            # 插件发起 LLM 请求时标记已调用 LLM，阻止框架对 @消息触发第二次默认 LLM 调用
            if isinstance(reply_result, ProviderRequest):
                event.call_llm = True

            yield reply_result

            # 安全兜底：agent完整流程结束后，检查是否有未保存的累积回复
            message_id = self._get_processing_id(event)
            if (
                message_id in self._pending_bot_replies
                and self._pending_bot_replies[message_id]
            ):
                logger.warning(
                    f"[安全兜底] 检测到 {len(self._pending_bot_replies[message_id])} 段未保存的累积回复"
                    f"（on_llm_response可能未触发），执行兜底保存"
                )
                try:
                    await self._finalize_bot_reply_save(event, message_id)
                except Exception as fallback_err:
                    logger.error(f"[安全兜底] 兜底保存失败: {fallback_err}", exc_info=True)

            if self.debug_mode:
                logger.info("【步骤13.9】回复已通过yield发送")
        else:
            if event.is_at_or_wake_command:
                event.call_llm = True
            if self.debug_mode:
                logger.info("【步骤13.9】跳过发送回复（重复消息已拦截），继续后续流程")

        # 记录已发送的回复（用于后续去重检查）
        if reply_text and not is_provider_request and not is_duplicate_blocked:
            if chat_id not in self.recent_replies_cache:
                self.recent_replies_cache[chat_id] = []
            self.recent_replies_cache[chat_id].append(
                {"content": reply_text, "timestamp": time.time()}
            )
            max_cache_size = min(
                max(10, self.duplicate_filter_check_count * 2),
                self._DUPLICATE_CACHE_SIZE_LIMIT,
            )
            if len(self.recent_replies_cache[chat_id]) > max_cache_size:
                self.recent_replies_cache[chat_id] = self.recent_replies_cache[chat_id][
                    -max_cache_size:
                ]

        # 调整读空气概率（传统模式：回复后提升）
        if self.debug_mode:
            logger.info("【步骤15】调整读空气概率（传统模式）")

        await ProbabilityManager.boost_probability(
            platform_name,
            is_private,
            chat_id,
            self.after_reply_probability,
            self.probability_duration,
        )

        if self.debug_mode:
            logger.info("=" * 60)
            logger.info("✓ 消息处理流程完成")

        _process_total_time = time.time() - _process_start_time
        if _process_total_time > self.reply_timeout_warning_threshold:
            logger.warning(
                f"⚠️ 消息处理总耗时异常: {_process_total_time:.2f}秒"
                f"（超过{self.reply_timeout_warning_threshold}秒阈值）"
            )

        logger.debug("消息处理完成,已发送回复并保存历史")

        # 回复后戳一戳功能
        if self.poke_after_reply_enabled:
            replied_user_id = event.get_sender_id()
            await self._do_poke_after_reply(event, replied_user_id, is_private, chat_id)

    async def _refresh_history_after_wait(
        self,
        event: AstrMessageEvent,
        chat_id: str,
        current_history: list,
        max_context: int,
    ) -> Optional[List]:
        """
        并发等待后刷新历史消息

        在并发等待期间，前一条消息的AI回复可能已经保存到官方对话历史中。
        如果发现新消息则返回更新后的历史列表，否则返回None。
        """
        try:
            cm = self.context.conversation_manager
            if not cm:
                return None

            uid = event.unified_msg_origin
            cid = await cm.get_curr_conversation_id(uid)
            if not cid:
                return None

            conv = await cm.get_conversation(
                unified_msg_origin=uid, conversation_id=cid
            )
            if not conv or not conv.history:
                return None

            try:
                official_history = json.loads(conv.history)
            except (json.JSONDecodeError, TypeError):
                return None

            if not isinstance(official_history, list) or len(official_history) == 0:
                return None

            self_id = event.get_self_id()
            platform_name = event.get_platform_name()
            is_private_chat = event.is_private_chat()

            try:
                max_context = int(max_context)
            except (TypeError, ValueError):
                max_context = -1

            if isinstance(max_context, int) and max_context > 0:
                msgs_iter = official_history[-max_context:]
            elif isinstance(max_context, int) and max_context == 0:
                return None
            else:
                msgs_iter = official_history

            refreshed_msgs = []
            for idx, msg in enumerate(msgs_iter):
                if (
                    not isinstance(msg, dict)
                    or "role" not in msg
                    or "content" not in msg
                ):
                    continue

                m = AstrBotMessage()
                m.message_str = ContextManager._content_to_safe_text(msg.get("content"))
                m.platform_name = platform_name
                _ts = msg.get("timestamp") or msg.get("ts") or msg.get("time")
                try:
                    m.timestamp = int(float(_ts)) if _ts else int(time.time())
                except Exception:
                    m.timestamp = int(time.time())
                m.type = (
                    MessageType.GROUP_MESSAGE
                    if not is_private_chat
                    else MessageType.FRIEND_MESSAGE
                )
                if not is_private_chat:
                    m.group_id = event.get_group_id()
                m.self_id = self_id
                m.session_id = getattr(event, "session_id", None) or (
                    event.get_sender_id() if is_private_chat else event.get_group_id()
                )
                raw_message_id = (
                    msg.get("message_id") or msg.get("id") or msg.get("mid") or ""
                )
                m.message_id = (
                    str(raw_message_id) or f"official_refresh_{idx}_{m.timestamp}"
                )

                if msg["role"] == "assistant":
                    m.sender = MessageMember(user_id=self_id, nickname="AI")
                else:
                    sender_info = (
                        msg.get("sender")
                        if isinstance(msg.get("sender"), dict)
                        else None
                    )
                    sender_id = None
                    sender_name = None
                    if sender_info:
                        sender_id = (
                            sender_info.get("user_id")
                            or sender_info.get("id")
                            or sender_info.get("uid")
                            or sender_info.get("qq")
                            or sender_info.get("uin")
                        )
                        sender_name = sender_info.get("nickname") or sender_info.get(
                            "name"
                        )
                    sender_id = (
                        str(sender_id)
                        if sender_id is not None
                        else f"refresh_user_{idx}"
                    )
                    sender_name = sender_name or ("对方" if is_private_chat else "群友")
                    m.sender = MessageMember(user_id=sender_id, nickname=sender_name)

                refreshed_msgs.append(m)

            _cutoff_ts = ContextManager.get_history_cutoff(chat_id)
            if _cutoff_ts > 0 and refreshed_msgs:
                refreshed_msgs = [
                    _m
                    for _m in refreshed_msgs
                    if (getattr(_m, "timestamp", 0) or 0) >= _cutoff_ts
                ]

            refreshed_msgs, _, _ = self.cache_manager.merge_cache_to_history(
                chat_id=chat_id,
                history_messages=refreshed_msgs,
                event=event,
                current_message_id=None,
            )

            if (
                isinstance(max_context, int)
                and max_context > 0
                and len(refreshed_msgs) > max_context
            ):
                refreshed_msgs = refreshed_msgs[-max_context:]

            if len(refreshed_msgs) <= len(current_history):
                return None

            return refreshed_msgs

        except Exception as e:
            logger.warning(f"[并发刷新] 获取最新历史失败: {e}")
            return None

    # ============================================================
    # 黑名单与启用检查
    # ============================================================

    def _is_enabled(self, event: AstrMessageEvent) -> bool:
        """
        检查当前群组是否启用插件

        判断逻辑：
        - 私聊直接返回False（不处理）
        - enabled_groups为空则全部群聊启用
        - enabled_groups有值则仅列表内的群启用
        """
        if event.is_private_chat():
            if self.debug_mode:
                logger.info("插件不处理私聊消息")
            return False

        enabled_groups = self.enabled_groups

        if not enabled_groups or len(enabled_groups) == 0:
            return True

        group_id = event.get_group_id()
        if group_id in enabled_groups:
            return True
        else:
            if self.debug_mode:
                logger.info(f"群组 {group_id} 未在启用列表中")
            return False

    def _is_user_blacklisted(self, event: AstrMessageEvent) -> bool:
        """检测发送者是否在用户黑名单中。"""
        try:
            if not self.enable_user_blacklist:
                return False

            blacklist = self.blacklist_user_ids
            if not blacklist:
                return False

            sender_id = event.get_sender_id()
            sender_id_str = str(sender_id)

            is_blacklisted = (
                sender_id in blacklist
                or sender_id_str in blacklist
                or (
                    int(sender_id_str) in blacklist
                    if sender_id_str.isdigit()
                    else False
                )
            )

            if is_blacklisted:
                if self.debug_mode:
                    logger.info(f"🚫 [用户黑名单] 用户 {sender_id} 在黑名单中，本插件跳过处理该消息")
                return True

            return False

        except Exception as e:
            logger.error(f"[用户黑名单检测] 发生错误: {e}", exc_info=True)
            return False

    # ============================================================
    # LLM 请求钩子（恢复插件内容，保留第三方注入）
    # ============================================================

    @filter.on_llm_request(priority=-1)
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """
        LLM 请求钩子（priority=-1，最后执行）

        当检测到请求来自本插件（PLUGIN_REQUEST_MARKER）时：
        1. 把 req.prompt 从短消息（向量检索用）换回完整上下文（full_prompt）
        2. 恢复插件 contexts（[]），保留其他插件注入的 contexts
        3. 恢复插件图片/音频URL（合并第三方注入）
        4. 合并插件工具集到 req.func_tool（保留框架内置工具）
        5. 注入 Skills 提示词（框架对无 conversation 的请求跳过此步骤）
        6. 不再注入任何插件行为指令/情绪/工具提醒文本
        """
        from .utils.reply_handler import (
            PLUGIN_REQUEST_MARKER,
            PLUGIN_CUSTOM_CONTEXTS,
            PLUGIN_CUSTOM_SYSTEM_PROMPT,
            PLUGIN_CUSTOM_PROMPT,
            PLUGIN_IMAGE_URLS,
            PLUGIN_FUNC_TOOL,
            PLUGIN_CURRENT_MESSAGE,
        )

        # 检查是否是来自本插件的请求
        is_plugin_request = event.get_extra(PLUGIN_REQUEST_MARKER, False)
        if not is_plugin_request:
            return

        try:
            plugin_contexts = event.get_extra(PLUGIN_CUSTOM_CONTEXTS, [])
            plugin_prompt = event.get_extra(PLUGIN_CUSTOM_PROMPT, "")
            plugin_image_urls = event.get_extra(PLUGIN_IMAGE_URLS, [])
            plugin_short_prompt = event.get_extra(PLUGIN_CURRENT_MESSAGE, "") or ""
            plugin_audio_urls = event.get_extra("_plugin_audio_urls", []) or []

            if self.debug_mode:
                logger.info("🔧 [on_llm_request] 检测到本插件的 LLM 请求，开始恢复内容...")

            # 1. 恢复 prompt：保留框架前缀（如 prompt_prefix）与第三方后缀注入
            #    用短消息在快照中定位，前后部分原样保留
            if plugin_prompt:
                current = req.prompt or ""
                if plugin_short_prompt and plugin_short_prompt in current:
                    prefix, _, suffix = current.partition(plugin_short_prompt)
                    req.prompt = prefix + plugin_prompt + suffix
                else:
                    req.prompt = plugin_prompt

            # 2. 恢复 contexts：插件用 []，保留第三方注入的 contexts
            extra_contexts = []
            if isinstance(req.contexts, list) and req.contexts:
                if plugin_contexts:
                    extra_contexts = [c for c in req.contexts if c not in plugin_contexts]
                else:
                    extra_contexts = list(req.contexts)
            req.contexts = list(plugin_contexts or []) + extra_contexts

            # 3. system_prompt 保持现状：人格已在请求时传入，
            #    框架（TOOL_CALL_PROMPT 等）与第三方插件只会追加，不会覆盖

            # 4. 图片/音频 URL 合并（保留第三方注入）
            _merged_image_urls = list(plugin_image_urls or [])
            _seen_urls = set(_merged_image_urls)
            for _u in req.image_urls or []:
                if _u not in _seen_urls:
                    _seen_urls.add(_u)
                    _merged_image_urls.append(_u)
            req.image_urls = _merged_image_urls

            _merged_audio_urls = list(plugin_audio_urls or [])
            _seen_audios = set(_merged_audio_urls)
            for _u in req.audio_urls or []:
                if _u not in _seen_audios:
                    _seen_audios.add(_u)
                    _merged_audio_urls.append(_u)
            if _merged_audio_urls:
                req.audio_urls = _merged_audio_urls

            # 5. 合并插件工具集与框架内置工具，而非直接替换
            plugin_tool_set = event.get_extra(PLUGIN_FUNC_TOOL)
            if plugin_tool_set is not None:
                try:
                    plugin_tools = getattr(plugin_tool_set, "tools", None)
                    if plugin_tools is None:
                        plugin_tools = getattr(plugin_tool_set, "func_list", None)
                    plugin_tools = list(plugin_tools or [])
                except Exception:
                    plugin_tools = []
                if req.func_tool is None:
                    req.func_tool = plugin_tool_set
                elif hasattr(req.func_tool, "merge") and hasattr(plugin_tool_set, "tools"):
                    req.func_tool.merge(plugin_tool_set)
                elif hasattr(req.func_tool, "add_tool"):
                    for tool in plugin_tools:
                        req.func_tool.add_tool(tool)
                elif hasattr(req.func_tool, "remove_func") and hasattr(
                    req.func_tool, "func_list"
                ):
                    for tool in plugin_tools:
                        req.func_tool.remove_func(tool.name)
                        req.func_tool.func_list.append(tool)
                else:
                    req.func_tool = plugin_tool_set

            # 6. 注入 Skills 提示词（插件请求无 conversation，框架跳过）
            try:
                from astrbot.core.skills.skill_manager import (
                    SkillManager,
                    build_skills_prompt,
                )

                skill_manager = SkillManager()
                skills = skill_manager.list_skills(active_only=True)
                if skills:
                    skills_prompt = build_skills_prompt(skills)
                    req.system_prompt = (req.system_prompt or "") + f"\n{skills_prompt}\n"
            except Exception as e:
                logger.warning(f"⚠️ 注入 Skills 提示词时出错（不影响主流程）: {e}")

            if self.debug_mode:
                logger.info("  ✅ 已恢复插件自定义上下文:")
                logger.info(f"    - contexts 数量: {len(req.contexts)}")
                logger.info(
                    f"    - system_prompt 长度: {len(req.system_prompt or '')}"
                )
                logger.info(f"    - prompt 长度: {len(req.prompt or '')}")
                logger.info(
                    f"    - image_urls 数量: {len(req.image_urls) if req.image_urls else 0}"
                )
        except Exception as e:
            logger.error(f"[on_llm_request] 恢复插件请求内容失败: {e}", exc_info=True)
        finally:
            # 处理完成后立即清理event.extra字段，防止event对象污染
            try:
                event.set_extra(PLUGIN_REQUEST_MARKER, None)
                event.set_extra(PLUGIN_CUSTOM_CONTEXTS, None)
                event.set_extra(PLUGIN_CUSTOM_SYSTEM_PROMPT, None)
                event.set_extra(PLUGIN_CUSTOM_PROMPT, None)
                event.set_extra(PLUGIN_IMAGE_URLS, None)
                event.set_extra("_plugin_audio_urls", None)
                event.set_extra("_plugin_media_audio_urls", None)
                event.set_extra(PLUGIN_FUNC_TOOL, None)
                event.set_extra(PLUGIN_CURRENT_MESSAGE, None)
                logger.info("[安全] 已清理LLM请求上下文缓存")
            except Exception as e:
                logger.warning(f"⚠️ 清理event.extra字段时发生错误: {e}")

    # ============================================================
    # LLM 响应 / 结果装饰 / 消息发送后
    # ============================================================

    @filter.on_llm_response(priority=-1)
    async def on_llm_response(self, event: AstrMessageEvent, response):
        """
        agent完成信号：当agent真正完成时（所有工具调用结束），
        设置完成标志，告知 after_message_sent 可以最终保存所有累积的回复。
        """
        try:
            message_id = self._get_processing_id(event)

            async with self.concurrent_lock:
                if message_id not in self.processing_sessions:
                    return

            self._agent_done_flags.add(message_id)

            if self.debug_mode:
                pending_count = len(self._pending_bot_replies.get(message_id, []))
                logger.info(
                    f"[on_llm_response] agent已完成，message_id={message_id[:30]}...，"
                    f"已累积 {pending_count} 段回复文本"
                )

            # 边界情况：agent完成但最终response没有文本，而之前有累积的中间文本
            has_final_text = bool(
                response
                and (
                    getattr(response, "completion_text", None)
                    or getattr(response, "result_chain", None)
                )
            )
            pending_texts = self._pending_bot_replies.get(message_id, [])

            if not has_final_text and pending_texts:
                logger.info(
                    f"[on_llm_response] agent完成但无最终文本，保存 {len(pending_texts)} 段累积文本"
                )
                await self._finalize_bot_reply_save(event, message_id)

        except Exception as e:
            logger.error(f"[on_llm_response] 处理失败: {e}", exc_info=True)

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        """
        在最终结果装饰阶段进行处理：
        - 仅处理由本插件标记的消息（processing_sessions）
        - 应用输出内容过滤（去除敏感词等）
        - 检查重复消息（若与最近回复重复，清空结果以跳过发送）
        """
        try:
            is_private = event.is_private_chat()
            chat_id = event.get_group_id() if not is_private else event.get_sender_id()

            message_id = self._get_processing_id(event)

            async with self.concurrent_lock:
                if message_id not in self.processing_sessions:
                    return

            result = event.get_result()
            if not result or not hasattr(result, "chain") or not result.chain:
                return

            if not result.is_llm_result():
                return

            reply_text = "".join(
                self._coerce_component_text(getattr(comp, "text", None))
                for comp in result.chain
            ).strip()
            if not reply_text:
                return

            self.raw_reply_cache[message_id] = reply_text

            # 多轮工具调用支持：累积原始回复文本
            if message_id not in self._pending_bot_replies:
                self._pending_bot_replies[message_id] = []
            self._pending_bot_replies[message_id].append(reply_text)

            # 应用输出内容过滤（独立于保存过滤）
            filtered_reply_text = reply_text
            if filtered_reply_text != reply_text:
                logger.info(
                    f"[输出过滤] 已过滤AI回复，原长度: {len(reply_text)}, 过滤后: {len(filtered_reply_text)}"
                )
                first_text_comp = True
                for comp in result.chain:
                    if hasattr(comp, "text"):
                        if first_text_comp:
                            comp.text = filtered_reply_text
                            first_text_comp = False
                        else:
                            comp.text = ""
                reply_text = filtered_reply_text

            if not reply_text:
                if self.debug_mode:
                    logger.info("[输出过滤] 过滤后内容为空，跳过发送")
                event.clear_result()
                if message_id in self.raw_reply_cache:
                    del self.raw_reply_cache[message_id]
                return

            # 重复检测必须在任何装饰性修改之前，基于原始内容检测
            if self.enable_duplicate_filter:
                now_ts = time.time()
                if chat_id not in self.recent_replies_cache:
                    self.recent_replies_cache[chat_id] = []

                if self.enable_duplicate_time_limit:
                    time_limit = max(60, self.duplicate_filter_time_limit)
                    self.recent_replies_cache[chat_id] = [
                        r
                        for r in self.recent_replies_cache[chat_id]
                        if now_ts - r.get("timestamp", 0) < time_limit
                    ]

                check_count = max(1, self.duplicate_filter_check_count)
                for recent in self.recent_replies_cache[chat_id][-check_count:]:
                    recent_content = recent.get("content", "")
                    recent_timestamp = recent.get("timestamp", 0)
                    if self.enable_duplicate_time_limit:
                        time_limit = max(60, self.duplicate_filter_time_limit)
                        if now_ts - recent_timestamp >= time_limit:
                            continue
                    if recent_content and reply_text == recent_content.strip():
                        logger.warning(
                            "🚫 [装饰阶段过滤] 检测到与最近回复重复，跳过发送（后续流程继续执行）"
                        )
                        event.clear_result()
                        self._duplicate_blocked_messages[message_id] = True
                        if message_id in self.raw_reply_cache:
                            del self.raw_reply_cache[message_id]
                        if self.debug_mode:
                            logger.info(
                                f"[装饰阶段] 已标记消息为重复拦截: {message_id[:30]}...（将跳过AI消息保存，但保存用户消息）"
                            )

                        # 重复拦截后 after_message_sent 不会被框架调用，
                        # 在此处直接保存用户消息和缓存消息到官方对话系统
                        try:
                            await self._save_user_messages_on_duplicate_block(
                                event, message_id
                            )
                        except Exception as save_err:
                            logger.warning(
                                f"[装饰阶段] 重复拦截后保存用户消息失败: {save_err}"
                            )
                        return

            # 通过重复检测后立即写入缓存（修复并发竞态）
            if self.enable_duplicate_filter and reply_text:
                try:
                    if chat_id not in self.recent_replies_cache:
                        self.recent_replies_cache[chat_id] = []
                    self.recent_replies_cache[chat_id].append(
                        {"content": reply_text, "timestamp": time.time()}
                    )
                    max_cache_size = min(
                        max(10, self.duplicate_filter_check_count * 2),
                        self._DUPLICATE_CACHE_SIZE_LIMIT,
                    )
                    if len(self.recent_replies_cache[chat_id]) > max_cache_size:
                        self.recent_replies_cache[chat_id] = self.recent_replies_cache[
                            chat_id
                        ][-max_cache_size:]
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"[装饰阶段] 去重处理失败: {e}", exc_info=True)

    # ============================================================
    # Smart 并发批次提示
    # ============================================================

    def _summarize_smart_batch_messages(
        self, smart_batch_messages: list, anchor_sender_id: str
    ) -> dict:
        """汇总 Smart 批次追加消息，用于构建回复阶段提示。"""
        summary = {
            "total_messages": 0,
            "other_sender_count": 0,
            "same_sender_count": 0,
            "has_other_senders": False,
            "has_same_sender_followups": False,
            "senders": [],
            "summary_lines": [],
        }
        if not smart_batch_messages:
            return summary

        sender_map = OrderedDict()
        anchor_sender_id = str(anchor_sender_id) if anchor_sender_id is not None else ""

        for msg in smart_batch_messages:
            if not isinstance(msg, dict):
                continue
            sender_id = str(msg.get("sender_id") or "unknown")
            sender_name = msg.get("sender_name") or "未知用户"
            content = ContextManager._content_to_safe_text(
                msg.get("content", "")
            ).strip()
            if not content:
                content = "（无文本内容）"
            content = content.replace("\n", " ")
            is_same_sender = sender_id == anchor_sender_id and anchor_sender_id != ""

            item = sender_map.setdefault(
                sender_id,
                {
                    "sender_id": sender_id,
                    "sender_name": sender_name,
                    "count": 0,
                    "latest_content": "",
                    "is_same_sender": is_same_sender,
                    "has_at": False,
                    "has_keyword": False,
                    "has_poke": False,
                },
            )
            item["count"] += 1
            item["latest_content"] = content[:120]
            item["has_at"] = item["has_at"] or bool(msg.get("is_at_message"))
            item["has_keyword"] = item["has_keyword"] or bool(
                msg.get("has_trigger_keyword")
            )
            item["has_poke"] = item["has_poke"] or bool(msg.get("poke_info"))

        senders = list(sender_map.values())
        summary["senders"] = senders
        summary["total_messages"] = sum(item["count"] for item in senders)
        summary["same_sender_count"] = sum(
            item["count"] for item in senders if item.get("is_same_sender")
        )
        summary["other_sender_count"] = sum(
            item["count"] for item in senders if not item.get("is_same_sender")
        )
        summary["has_other_senders"] = any(
            not item.get("is_same_sender") for item in senders
        )
        summary["has_same_sender_followups"] = summary["same_sender_count"] > 0

        summary_lines = []
        for item in senders:
            flags = []
            if item.get("is_same_sender"):
                flags.append("当前对象的追加消息")
            else:
                flags.append("其他用户插话")
            if item.get("has_at"):
                flags.append("@触发")
            if item.get("has_keyword"):
                flags.append("关键词触发")
            if item.get("has_poke"):
                flags.append("戳一戳相关")
            flag_text = f"（{'、'.join(flags)}）" if flags else ""
            count_text = f"{item['count']}条"
            summary_lines.append(
                f"- {item['sender_name']}(ID:{item['sender_id']}) {count_text}{flag_text}：{item['latest_content']}"
            )
        summary["summary_lines"] = summary_lines
        return summary

    def _build_smart_batch_reply_hint(
        self, event: AstrMessageEvent, smart_batch_summary: dict
    ) -> str:
        """构建 Smart 并发批次回复提示。"""
        if not smart_batch_summary or not smart_batch_summary.get("summary_lines"):
            return ""

        sender_name = event.get_sender_name() or "当前对话对象"
        sender_id = event.get_sender_id()
        total_messages = smart_batch_summary.get("total_messages", 0)
        has_other_senders = smart_batch_summary.get("has_other_senders", False)
        has_same_sender_followups = smart_batch_summary.get(
            "has_same_sender_followups", False
        )

        scenario_parts = []
        if has_same_sender_followups:
            scenario_parts.append("当前这个人又补发了后续消息")
        if has_other_senders:
            scenario_parts.append("期间还有其他用户插话")
        if not scenario_parts:
            scenario_parts.append("当前消息后面还有紧接着的追加消息")
        scenario_text = "，".join(scenario_parts)

        summary_block = "\n".join(smart_batch_summary.get("summary_lines", []))
        return (
            "\n\n[系统提示-Smart并发]\n"
            f"你这次面对的是一个 Smart 并发批次：在 {sender_name}(ID:{sender_id}) 这条当前消息之后，"
            f"又紧接着出现了 {total_messages} 条追加消息。{scenario_text}。\n"
            "这些追加消息已按发送者名字和ID标出，帮你理解完整对话背景：\n"
            f"{summary_block}\n"
            f"你只需回复 {sender_name}(ID:{sender_id}) 的当前消息。追加消息是背景参考，"
            f"直接自然说话即可，不要逐条回复、不要进行任何判断或分析。\n"
        )

    # ============================================================
    # 图片描述缓存辅助（省钱）
    # ============================================================

    async def _save_platform_descriptions_to_cache(
        self, event, platform_processed_text: str
    ):
        """将平台自动理解的图片描述保存到图片描述缓存中（省钱）。"""
        if not self.image_description_cache or not self.image_description_cache.enabled:
            return
        if not platform_processed_text:
            return
        try:
            from astrbot.api.message_components import Image

            if not hasattr(event, "message_obj") or not hasattr(
                event.message_obj, "message"
            ):
                return

            message_chain = event.message_obj.message
            image_components = [
                comp for comp in message_chain if isinstance(comp, Image)
            ]
            if not image_components:
                return

            descriptions = re.findall(
                r"[图片内容:s*([^]]+)]", platform_processed_text
            )
            if not descriptions:
                return

            save_count = 0
            for idx, img_component in enumerate(image_components):
                if idx >= len(descriptions):
                    break
                try:
                    image_path = await img_component.convert_to_file_path()
                    if not image_path:
                        continue
                    description = descriptions[idx].strip()
                    if not description:
                        continue
                    if self.image_description_cache.lookup(image_path):
                        continue
                    self.image_description_cache.save(image_path, description)
                    save_count += 1
                except Exception as e:
                    logger.warning(f"[图片缓存-平台描述] 保存图片 {idx} 时失败: {e}")
                    continue

            if save_count > 0:
                logger.info(
                    f"💾 [图片缓存-平台描述] 已将 {save_count} 张平台自动理解的图片描述保存到缓存 (省钱!)"
                )
        except Exception as e:
            logger.warning(f"[图片缓存-平台描述] 保存平台描述到缓存失败: {e}")

    async def _try_cache_fallback_for_images(self, event) -> Optional[str]:
        """
        省钱回退：平台描述获取失败后，从图片描述缓存中查找已缓存的图片描述。

        Returns:
            构建好的带描述文本（至少一张图片命中缓存），或 None
        """
        if not self.image_description_cache or not self.image_description_cache.enabled:
            return None
        try:
            from astrbot.api.message_components import Image, Plain

            if not hasattr(event, "message_obj") or not hasattr(
                event.message_obj, "message"
            ):
                return None

            message_chain = event.message_obj.message

            result_parts = []
            cache_hit_count = 0

            for component in message_chain:
                if isinstance(component, Plain):
                    text = self._coerce_component_text(component.text)
                    if text:
                        result_parts.append(text)
                elif isinstance(component, Image):
                    try:
                        image_path = await component.convert_to_file_path()
                        if image_path:
                            cached_desc = self.image_description_cache.lookup(image_path)
                            if cached_desc:
                                result_parts.append(f"[图片内容: {cached_desc}]")
                                cache_hit_count += 1
                    except Exception:
                        continue

            if cache_hit_count == 0:
                return None

            result_text = "".join(result_parts).strip()
            if not result_text:
                return None

            logger.info(f"💰 [省钱回退] 从缓存恢复了 {cache_hit_count} 张图片的描述")
            return result_text

        except Exception as e:
            logger.warning(f"[省钱回退] 查询图片缓存时发生错误: {e}")
            return None

    # ============================================================
    # 通用辅助方法
    # ============================================================

    @staticmethod
    def _coerce_component_text(value: Any) -> str:
        """将消息组件文本强制转换为字符串。"""
        try:
            if value is None:
                return ""
            if isinstance(value, str):
                return value
            if isinstance(value, (list, tuple)):
                parts = []
                for item in value:
                    text = getattr(item, "text", None)
                    if text is not None:
                        parts.append(str(text))
                    elif isinstance(item, str):
                        parts.append(item)
                return "".join(parts)
            return str(value)
        except Exception:
            return ""

    def _build_source_event_id(self, event: AstrMessageEvent) -> str:
        """构建平台重复推送识别ID；尽量稳定，但不误伤用户主动重复发言。"""
        try:
            cached = getattr(event, "_plugin_source_event_id", None)
            if cached:
                return cached

            result_id = ""
            if hasattr(event, "message_obj") and hasattr(
                event.message_obj, "message_id"
            ):
                platform_msg_id = str(event.message_obj.message_id or "").strip()
                if platform_msg_id:
                    result_id = f"{event.get_platform_name()}_{platform_msg_id}"

            if not result_id:
                msg_ts = None
                if hasattr(event, "message_obj") and hasattr(
                    event.message_obj, "timestamp"
                ):
                    msg_ts = getattr(event.message_obj, "timestamp", None)
                sender_id = event.get_sender_id() or ""
                group_id = (
                    event.get_group_id() if not event.is_private_chat() else "private"
                )
                content_outline = (
                    event.get_message_outline() or event.get_message_str() or ""
                )
                content_outline = content_outline[:160]
                hash_input = (
                    f"{event.get_platform_name()}|{sender_id}|{group_id}|{msg_ts}|{content_outline}"
                ).encode("utf-8", errors="ignore")
                result_id = (
                    f"fallback_source_{hashlib.md5(hash_input).hexdigest()[:20]}"
                )

            try:
                event._plugin_source_event_id = result_id
            except AttributeError:
                pass
            return result_id
        except Exception as e:
            return (
                f"fallback_source_error_{hashlib.md5(str(e).encode()).hexdigest()[:12]}"
            )

    def _get_processing_id(self, event: AstrMessageEvent) -> str:
        """获取插件内部处理实例ID；与平台重复推送识别ID解耦。"""
        try:
            cached = getattr(event, "_plugin_processing_id", None)
            if cached:
                return cached

            source_event_id = self._build_source_event_id(event)
            result_id = f"proc_{source_event_id}_{id(event)}"
            try:
                event._plugin_processing_id = result_id
            except AttributeError:
                pass
            return result_id
        except Exception as e:
            return f"proc_fallback_{int(time.time() * 1000)}_{hashlib.md5(str(e).encode()).hexdigest()[:8]}"

    def _ensure_arrival_metadata(self, event: AstrMessageEvent) -> tuple:
        """为当前 event 分配稳定的到达序号与单调时间。"""
        try:
            arrival_seq = getattr(event, "_plugin_arrival_seq", None)
            arrival_monotonic = getattr(event, "_plugin_arrival_monotonic", None)
            if arrival_seq and arrival_monotonic:
                return arrival_seq, arrival_monotonic

            self._arrival_seq_counter += 1
            arrival_seq = self._arrival_seq_counter
            arrival_monotonic = time.monotonic()

            try:
                event._plugin_arrival_seq = arrival_seq
                event._plugin_arrival_monotonic = arrival_monotonic
            except AttributeError:
                pass
            return arrival_seq, arrival_monotonic
        except Exception:
            return 0, time.monotonic()

