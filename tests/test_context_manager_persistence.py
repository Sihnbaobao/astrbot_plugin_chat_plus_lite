"""Regression tests for context cutoff and custom storage persistence."""

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path


class _Logger:
    """Logger stub required by the standalone context module."""

    def debug(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def _load_context_manager(monkeypatch):
    """Load ContextManager with the minimal imports needed by persistence code."""
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api_all = types.ModuleType("astrbot.api.all")
    api_all.logger = _Logger()
    api_all.AstrBotMessage = type("AstrBotMessage", (), {})
    api_all.AstrMessageEvent = type("AstrMessageEvent", (), {})
    components = types.ModuleType("astrbot.api.message_components")
    components.Plain = type("Plain", (), {})
    package = types.ModuleType("context_manager_test")
    package.__path__ = []
    message_processor = types.ModuleType("context_manager_test.message_processor")
    message_processor.MessageProcessor = type("MessageProcessor", (), {})

    for name, module in {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.all": api_all,
        "astrbot.api.message_components": components,
        "context_manager_test": package,
        "context_manager_test.message_processor": message_processor,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    path = Path(__file__).parents[1] / "utils" / "context_manager.py"
    spec = importlib.util.spec_from_file_location(
        "context_manager_test.context_manager",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module.ContextManager


def test_cutoff_storage_round_trips_bom_and_writes_atomically(monkeypatch, tmp_path):
    """Cutoff state survives reload and accepts a BOM-prefixed JSON file."""
    context_manager = _load_context_manager(monkeypatch)
    context_manager.init(str(tmp_path), custom_storage_max_messages=0)
    context_manager.set_history_cutoff("chat-1")
    saved_cutoff = context_manager.get_history_cutoff("chat-1")

    cutoff_file = tmp_path / "history_cutoff.json"
    assert cutoff_file.exists()
    assert not list(tmp_path.glob(".history_cutoff.json.*.tmp"))

    cutoff_file.write_text(
        "\ufeff{\"chat-2\": 123.5}",
        encoding="utf-8",
    )
    context_manager._load_cutoff_timestamps(str(tmp_path))

    assert context_manager.get_history_cutoff("chat-1") == 0.0
    assert context_manager.get_history_cutoff("chat-2") == 123.5
    assert saved_cutoff > 0


def test_custom_storage_serializes_concurrent_appends(monkeypatch, tmp_path):
    """Concurrent append-and-trim operations leave valid JSON with all entries."""
    context_manager = _load_context_manager(monkeypatch)
    file_path = tmp_path / "history.json"
    messages = [
        {"message_str": f"message-{index}", "timestamp": index}
        for index in range(20)
    ]

    async def append_and_trim(message):
        await asyncio.to_thread(
            context_manager._append_message_to_file,
            file_path,
            message,
        )
        await asyncio.to_thread(
            context_manager._trim_messages_in_file,
            file_path,
            20,
        )

    async def scenario():
        await asyncio.gather(
            *(append_and_trim(message) for message in messages)
        )

    asyncio.run(scenario())

    persisted = json.loads(file_path.read_text(encoding="utf-8"))
    assert len(persisted) == len(messages)
    assert {message["message_str"] for message in persisted} == {
        message["message_str"] for message in messages
    }
