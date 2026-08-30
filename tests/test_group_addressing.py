"""Regression tests for deterministic group addressing."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
UTILS_DIR = REPO_ROOT / "utils"


class _Logger:
    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _Plain:
    def __init__(self, text):
        self.text = text


class _At:
    def __init__(self, qq):
        self.qq = qq


class _Reply:
    def __init__(self, sender_id, message_str=""):
        self.sender_id = sender_id
        self.message_str = message_str


class _Event:
    def __init__(self, message_chain, message_str=""):
        self.message_obj = types.SimpleNamespace(message=message_chain)
        self._message_str = message_str
        self.unified_msg_origin = "bot_name:GroupMessage:10001"

    def get_self_id(self):
        return "bot_self"

    def get_message_str(self):
        return self._message_str

    def get_message_outline(self):
        return self._message_str


def _install_stubs(monkeypatch):
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api_all = types.ModuleType("astrbot.api.all")
    core = types.ModuleType("astrbot.core")
    core_message = types.ModuleType("astrbot.core.message")
    core_components = types.ModuleType("astrbot.core.message.components")

    logger = _Logger()
    api.logger = logger
    api_all.logger = logger
    api_all.AstrMessageEvent = _Event
    core_components.At = _At
    core_components.Plain = _Plain
    core_components.Reply = _Reply

    modules = {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.all": api_all,
        "astrbot.core": core,
        "astrbot.core.message": core_message,
        "astrbot.core.message.components": core_components,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def _load_module(monkeypatch, module_name):
    _install_stubs(monkeypatch)
    package_name = "group_addressing_test_pkg"
    package = types.ModuleType(package_name)
    package.__path__ = [str(REPO_ROOT)]
    utils_package = types.ModuleType(f"{package_name}.utils")
    utils_package.__path__ = [str(UTILS_DIR)]
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, f"{package_name}.utils", utils_package)

    full_name = f"{package_name}.utils.{module_name}"
    spec = importlib.util.spec_from_file_location(
        full_name, UTILS_DIR / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, full_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def addressing_modules(monkeypatch):
    return (
        _load_module(monkeypatch, "message_processor"),
        _load_module(monkeypatch, "keyword_checker"),
    )


def test_quoted_reply_cannot_fake_at_or_keyword(addressing_modules):
    processor, checker = addressing_modules
    event = _Event(
        [_Reply("other", "@bot_self 璃月"), _Plain("算了")],
        "[引用消息] @bot_self 璃月 算了",
    )

    assert not processor.MessageProcessor.is_at_message(event)
    assert not checker.KeywordChecker.check_trigger_keywords(event, ["璃月"])
    assert not processor.MessageProcessor.is_reply_to_bot(event)


def test_current_message_address_signals_are_preserved(addressing_modules):
    processor, checker = addressing_modules

    at_event = _Event([_At("bot_self"), _Plain("你好")], "@bot_self 你好")
    keyword_event = _Event([_Reply("other"), _Plain("璃月，听得到吗")], "璃月")
    bot_reply_event = _Event(
        [_Reply("bot_self", "上一条回复"), _Plain("继续")],
        "[引用消息] 继续",
    )
    other_reply_event = _Event(
        [_Reply("other", "上一条消息"), _Plain("继续")],
        "[引用消息] 继续",
    )

    assert processor.MessageProcessor.is_at_message(at_event)
    assert checker.KeywordChecker.check_trigger_keywords(keyword_event, ["璃月"])
    assert processor.MessageProcessor.is_reply_to_bot(bot_reply_event)
    assert not processor.MessageProcessor.is_reply_to_bot(other_reply_event)
