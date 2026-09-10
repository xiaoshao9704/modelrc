"""Adapter 契约：一个 agent 的识别方式与数据格式绑在同一个类里。

新增一个 agent = 新增一个 Adapter 子类并在 adapters/__init__.py 注册。
核心逻辑（rules.py）与 CLI 都不需要改动，契约测试会自动覆盖新 adapter。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..context import HookContext


class Adapter(ABC):
    #: agent 标识。同时是规则里 match.harness 的取值与 --harness 的取值。
    name = ""

    @abstractmethod
    def detect(self, payload, env):
        """这份 payload / 环境是不是我。显式 --harness 优先于本方法。"""

    @abstractmethod
    def parse(self, payload, env):
        """把该 agent 的 hook 入参归一化成 HookContext。"""

    @abstractmethod
    def emit(self, ctx, text):
        """把要注入的文本渲染成该 agent 期望的 stdout JSON。"""

    @abstractmethod
    def native_events(self):
        """该 agent 支持挂载、且本工具需要的原生事件名。用于生成插件清单。"""

    def shared_events(self):
        """需要写进共用 hooks/hooks.json 的事件。两边都认的放这里。"""
        return self.native_events()
