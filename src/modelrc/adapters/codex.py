"""Codex adapter。

已核对 codex-cli 0.153.4：
- 插件 hooks 走 hooks/hooks.json，结构与 Claude Code 同构，事件名同为 PascalCase，
  且 ${CLAUDE_PLUGIN_ROOT} 变量被显式支持（另有别名 ${PLUGIN_ROOT}）
- hook 入参含 model / cwd / session_id / turn_id，无 permission_mode
- 只有 command 类型的 handler 可用（prompt / agent / mcp hooks 尚未支持）
- 事件集不含 PostModelSwitch
"""

from __future__ import annotations

import json
from pathlib import Path

from ..context import SESSION_START, HookContext
from .base import Adapter

SESSION_START_EVENT = "SessionStart"

_EVENT_MAP = {SESSION_START_EVENT: SESSION_START}


class CodexAdapter(Adapter):
    name = "codex"

    def detect(self, payload, env):
        # Codex 未确认会向 hook 子进程注入专属环境变量，所以以 payload 特征为准：
        # 有 turn_id 且没有 Claude 独有字段。
        if "turn_id" in payload and "permission_mode" not in payload:
            return True
        return bool(env.get("CODEX_HOME")) and "permission_mode" not in payload

    def parse(self, payload, env):
        native = payload.get("hook_event_name") or SESSION_START_EVENT
        config_dir = Path(env.get("CODEX_HOME") or "~/.codex").expanduser()
        return HookContext(
            harness=self.name,
            event=_EVENT_MAP.get(native, native),
            model=payload.get("model") or "",
            cwd=payload.get("cwd") or "",
            config_dir=str(config_dir),
            session_id=payload.get("session_id") or "",
            native_event=native,
            raw=payload,
        )

    def emit(self, ctx, text):
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": ctx.native_event or SESSION_START_EVENT,
                    "additionalContext": text,
                }
            },
            ensure_ascii=False,
        )

    def native_events(self):
        return [SESSION_START_EVENT]
