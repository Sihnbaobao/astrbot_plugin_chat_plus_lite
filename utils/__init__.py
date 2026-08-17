"""
工具模块初始化（精简版）
导出所有工具类供主插件使用

作者: Sihnbaobao（重构）
版本: 0.0.1
"""

from .probability_manager import ProbabilityManager
from .message_processor import MessageProcessor
from .image_handler import ImageHandler
from .context_manager import ContextManager
from .decision_ai import DecisionAI
from .reply_handler import ReplyHandler
from .save_processor import SaveMixin
from .command_processor import CommandMixin
from .mention_processor import MentionMixin
from .poke_processor import PokeMixin
from .memory_injector import MemoryInjector
from .keyword_checker import KeywordChecker
from .message_cleaner import MessageCleaner

# 保留功能模块
from .ai_response_filter import AIResponseFilter
from .platform_ltm_helper import PlatformLTMHelper
from .image_description_cache import ImageDescriptionCache
from .emoji_detector import EmojiDetector, EMOJI_MARKER
from .smart_concurrent_manager import SmartConcurrentManager
from .ai_error_formatter import format_ai_error

# 全局调试日志开关（供各模块统一读取）
DEBUG_MODE: bool = False


def set_debug_mode(enabled: bool) -> None:
    """
    由主插件调用，统一设置调试日志开关
    所有模块应读取 utils.DEBUG_MODE 作为最终判定
    """
    global DEBUG_MODE
    DEBUG_MODE = bool(enabled)


__all__ = [
    "ProbabilityManager",
    "MessageProcessor",
    "ImageHandler",
    "ContextManager",
    "DecisionAI",
    "ReplyHandler",
    "PokeMixin",
    "MentionMixin",
    "CommandMixin",
    "SaveMixin",
    "MemoryInjector",
    "KeywordChecker",
    "MessageCleaner",
    "AIResponseFilter",
    "PlatformLTMHelper",
    "ImageDescriptionCache",
    "EmojiDetector",
    "EMOJI_MARKER",
    "SmartConcurrentManager",
    "format_ai_error",
    "DEBUG_MODE",
    "set_debug_mode",
]
