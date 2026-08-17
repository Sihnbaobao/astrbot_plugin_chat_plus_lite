"""Regression tests for the refactor-lite rewrite.

Core guarantees under test:
1. ReplyHandler no longer ships SYSTEM_REPLY_PROMPT (the ~100 line behavior
   instruction block that caused persona drift in group chats).
2. generate_reply produces a ProviderRequest whose system_prompt is exactly the
   persona and whose prompt is pure context (sender annotation + history) with
   no behavior instructions.
3. DecisionAI.SYSTEM_DECISION_PROMPT only covers the yes/no "should I reply"
   judgment and contains no references to removed features.
4. MessageCacheManager's expiry filter is pure and correct.
5. KeywordChecker trigger/blacklist matching still works.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _run(coro):
    """Run an async coroutine (sync test helper)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)

REPO_ROOT = Path(__file__).parents[1]
UTILS_DIR = REPO_ROOT / "utils"


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass


class _ProviderRequest:
    """Minimal double for astrbot.core.provider.entities.ProviderRequest."""

    def __init__(self, **kwargs):
        self.prompt = kwargs.get("prompt", "")
        self.system_prompt = kwargs.get("system_prompt", "")
        self.session_id = kwargs.get("session_id", "")
        self.image_urls = kwargs.get("image_urls", [])
        self.audio_urls = kwargs.get("audio_urls", [])
        self.contexts = kwargs.get("contexts", [])
        self.func_tool = kwargs.get("tool_set", None)


class _Event:
    """Minimal double for AstrMessageEvent used by generate_reply."""

    def __init__(self, message_str="", sender_id="42", sender_name="小明"):
        self._message_str = message_str
        self._sender_id = sender_id
        self._sender_name = sender_name
        self.session_id = "sess-1"
        self.unified_msg_origin = "aiocqhttp:GroupMessage:10001"
        self._extras = {}

    def get_sender_id(self):
        return self._sender_id

    def get_sender_name(self):
        return self._sender_name

    def get_message_str(self):
        return self._message_str

    def get_self_id(self):
        return "bot_self"

    def set_extra(self, key, value):
        self._extras[key] = value

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def request_llm(self, **kwargs):
        return _ProviderRequest(**kwargs)


class _PersonaManager:
    def __init__(self, prompt):
        self._prompt = prompt

    async def get_default_persona_v3(self, umo):
        return {"prompt": self._prompt, "name": "测试人格", "_begin_dialogs_processed": []}


class _ToolManager:
    def get_full_tool_set(self):
        return None


class _Context:
    def __init__(self, persona_prompt):
        self.persona_manager = _PersonaManager(persona_prompt)
        self._tools = _ToolManager()

    def get_llm_tool_manager(self):
        return self._tools


def _install_astrbot_stubs(monkeypatch):
    """Install the same lightweight astrbot module stubs used by test_image_handler."""
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api_all = types.ModuleType("astrbot.api.all")
    api_event = types.ModuleType("astrbot.api.event")
    api_platform = types.ModuleType("astrbot.api.platform")
    core = types.ModuleType("astrbot.core")
    core_provider = types.ModuleType("astrbot.core.provider")
    entities = types.ModuleType("astrbot.core.provider.entities")

    api_all.logger = _Logger()
    api.logger = _Logger()
    api_all.Context = object
    api_all.AstrMessageEvent = _Event
    api_event.AstrMessageEvent = _Event
    api_platform.AstrBotMessage = object
    api_platform.MessageMember = object
    api_platform.MessageType = object
    entities.ProviderRequest = _ProviderRequest

    modules = {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.all": api_all,
        "astrbot.api.event": api_event,
        "astrbot.api.platform": api_platform,
        "astrbot.core": core,
        "astrbot.core.provider": core_provider,
        "astrbot.core.provider.entities": entities,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def _load_module(monkeypatch, rel_path, module_name, stubs=None):
    """Load a utils module under a fake package with optional extra stubs."""
    _install_astrbot_stubs(monkeypatch)

    package_name = "gcp_lite_test_pkg"
    package = types.ModuleType(package_name)
    package.__path__ = [str(REPO_ROOT)]
    utils_package = types.ModuleType(f"{package_name}.utils")
    utils_package.__path__ = [str(UTILS_DIR)]
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, f"{package_name}.utils", utils_package)

    # 让 utils 包能被相对导入（stub 兄弟模块）
    for sub, obj in (stubs or {}).items():
        stub_module = types.ModuleType(f"{package_name}.utils.{sub}")
        for attr, value in obj.items():
            setattr(stub_module, attr, value)
        monkeypatch.setitem(sys.modules, f"{package_name}.utils.{sub}", stub_module)

    full_name = f"{package_name}.utils.{module_name}"
    spec = importlib.util.spec_from_file_location(full_name, UTILS_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, full_name, module)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# ReplyHandler
# ---------------------------------------------------------------------------

def test_reply_handler_has_no_system_reply_prompt(monkeypatch):
    handler = _load_module(monkeypatch, "reply_handler.py", "reply_handler")
    assert not hasattr(handler.ReplyHandler, "SYSTEM_REPLY_PROMPT")


def test_generate_reply_system_prompt_is_exactly_persona(monkeypatch):
    handler = _load_module(monkeypatch, "reply_handler.py", "reply_handler")
    persona = "你是温柔的猫娘，说话带喵。"
    event = _Event(message_str="在吗")
    context = _Context(persona_prompt=persona)

    req = _run(
        handler.ReplyHandler.generate_reply(
            event,
            context,
            formatted_message="[10:00] 小明(42): 在吗",
            extra_prompt="",
            prompt_mode="append",
        )
    )

    # system_prompt 只含人格，不叠加任何插件指令
    assert req.system_prompt == persona
    # req.prompt 是短消息占位（供向量检索类插件召回），完整上下文在 extra 中
    assert req.prompt == "在吗"
    # 完整 prompt（存于 extra，由 on_llm_request 恢复）只含上下文 + 发送者标注 + 最小结尾
    full_prompt = event.get_extra(handler.PLUGIN_CUSTOM_PROMPT, "")
    assert "在吗" in full_prompt
    assert "小明" in full_prompt
    assert "42" in full_prompt
    for banned in ("严禁元叙述", "系统行为指令", "回复身份", "严禁重复", "请开始回复"):
        assert banned not in full_prompt
    assert "请直接输出你的回复" in full_prompt


def test_generate_reply_sets_marker_extras(monkeypatch):
    handler = _load_module(monkeypatch, "reply_handler.py", "reply_handler")
    event = _Event(message_str="测试消息")
    context = _Context(persona_prompt="人格A")

    _run(
        handler.ReplyHandler.generate_reply(
            event,
            context,
            formatted_message="上下文内容",
            extra_prompt="",
            prompt_mode="append",
        )
    )

    assert event.get_extra(handler.PLUGIN_REQUEST_MARKER, False) is True
    assert event.get_extra(handler.PLUGIN_CUSTOM_SYSTEM_PROMPT, "") == "人格A"
    assert "上下文内容" in event.get_extra(handler.PLUGIN_CUSTOM_PROMPT, "")
    # 短消息占位：空消息时提供 [空消息] 占位符
    empty_event = _Event(message_str="")
    req = _run(
        handler.ReplyHandler.generate_reply(
            empty_event,
            context,
            formatted_message="ctx",
            extra_prompt="",
            prompt_mode="append",
        )
    )
    assert req.prompt in ("[空消息]", "")


# ---------------------------------------------------------------------------
# DecisionAI
# ---------------------------------------------------------------------------

def test_decision_prompt_has_no_removed_feature_references(monkeypatch):
    decision = _load_module(
        monkeypatch,
        "decision_ai.py",
        "decision_ai",
        stubs={
            "ai_response_filter": {"AIResponseFilter": object},
            "ai_error_formatter": {"format_ai_error": lambda e, l: f"{l}: {e}"},
        },
    )
    prompt = decision.DecisionAI.SYSTEM_DECISION_PROMPT
    for removed in ("对话疲劳", "判断记录", "兴趣话题", "时间与活跃度", "主动对话", "拟人"):
        assert removed not in prompt
    assert "是否回复" in prompt
    assert "yes或no" in prompt


# ---------------------------------------------------------------------------
# MessageCacheManager expiry filter
# ---------------------------------------------------------------------------

def _load_cache_manager(monkeypatch):
    return _load_module(
        monkeypatch,
        "message_cache_manager.py",
        "message_cache_manager",
        stubs={
            "message_processor": {"MessageProcessor": object},
            "message_cleaner": {"MessageCleaner": object},
            "context_manager": {"ContextManager": object},
        },
    )


def test_expiry_filter_removes_old_messages(monkeypatch):
    manager = _load_cache_manager(monkeypatch)
    import time as _time

    now = _time.time()
    messages = [
        {"content": "旧消息", "timestamp": now - 9999},
        {"content": "新消息", "timestamp": now},
    ]
    filtered = manager._filter_expired_cached_messages(
        messages, cache_ttl_seconds=600, max_cache_count=10
    )
    assert len(filtered) == 1
    assert filtered[0]["content"] == "新消息"


def test_expiry_filter_respects_max_count(monkeypatch):
    manager = _load_cache_manager(monkeypatch)
    import time as _time

    now = _time.time()
    messages = [
        {"content": f"m{i}", "timestamp": now - 100 + i} for i in range(5)
    ]
    filtered = manager._filter_expired_cached_messages(
        messages, cache_ttl_seconds=600, max_cache_count=2
    )
    assert len(filtered) == 2
    # 保留最新的两条（按 timestamp 排序）
    assert filtered[-1]["content"] == "m4"


# ---------------------------------------------------------------------------
# KeywordChecker
# ---------------------------------------------------------------------------

def test_keyword_checker_triggers_and_blacklist(monkeypatch):
    checker = _load_module(
        monkeypatch,
        "keyword_checker.py",
        "keyword_checker",
    )

    class _MsgEvent:
        def __init__(self, text):
            self._text = text
            self._components = []

        def get_message_str(self):
            return self._text

        def get_message_outline(self):
            return self._text

        def get_messages(self):
            return self._components

    hit_event = _MsgEvent("有人提到机器人关键词啦")
    is_hit, matched = checker.KeywordChecker.check_trigger_keywords_with_match(
        hit_event, ["机器人"]
    )
    assert is_hit is True
    assert matched == "机器人"

    miss_event = _MsgEvent("普通内容")
    is_hit, matched = checker.KeywordChecker.check_trigger_keywords_with_match(
        miss_event, ["机器人"]
    )
    assert is_hit is False

    banned = checker.KeywordChecker.check_blacklist_keywords(miss_event, ["违禁词"])
    assert banned is False
    banned_event = _MsgEvent("这条消息包含违禁词")
    banned = checker.KeywordChecker.check_blacklist_keywords(banned_event, ["违禁词"])
    assert banned is True
