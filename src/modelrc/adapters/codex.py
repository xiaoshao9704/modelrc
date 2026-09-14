"""Codex adapter。

实测 codex-cli 0.153.4 与桌面版 0.154.0-alpha.6.2：
- SessionStart 含 model / cwd / session_id / permission_mode / transcript_path，
  不含 turn_id。共享字段不能用于区分 Claude 与 Codex。
- 插件通过独立清单显式传入 --harness codex，避免继承环境造成误判。
- additionalContext 注入 developer 上下文；没有 PostModelSwitch 事件。
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
        # 自动判别仅用于手动调用；插件入口始终显式指定宿主。
        if env.get("CLAUDECODE") == "1" or env.get("CLAUDE_CODE_SESSION_ID"):
            return False
        if "prompt_id" in payload or payload.get("hook_event_name") == "PostModelSwitch":
            return False
        return bool(env.get("CODEX_HOME")) or "turn_id" in payload

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
