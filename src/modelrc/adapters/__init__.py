"""Adapter 注册表。加一个 agent 只需在这里补一行。"""

from __future__ import annotations

from .base import Adapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter

ADAPTERS = [ClaudeAdapter(), CodexAdapter()]

__all__ = ["Adapter", "ADAPTERS", "by_name", "detect"]


def by_name(name):
    for adapter in ADAPTERS:
        if adapter.name == name:
            return adapter
    known = ", ".join(a.name for a in ADAPTERS)
    raise KeyError(f"未知 harness: {name}（已注册: {known}）")


def detect(payload, env):
    """按注册顺序找第一个认领这份 payload 的 adapter。都不认领返回 None。"""
    for adapter in ADAPTERS:
        if adapter.detect(payload, env):
            return adapter
    return None
