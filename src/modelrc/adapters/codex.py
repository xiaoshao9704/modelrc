"""Codex adapter。

实测 codex-cli 0.153.4 与桌面版 0.154.0-alpha.6.2：
- SessionStart 含 model / cwd / session_id / permission_mode / transcript_path，
  不含 turn_id。共享字段不能用于区分 Claude 与 Codex。
- 插件通过独立清单显式传入 --harness codex，避免继承环境造成误判。
- additionalContext 注入 developer 上下文；没有 PostModelSwitch 事件。
- payload 的 source 恒为 startup，区分不了 exec。会话形态取 transcript 首行
  session_meta.payload.source（实测 codex-cli 0.171.0：hook 触发时首行已落盘）：
  "exec" 为 headless，{"subagent": ...} 为子代理，其余字符串（如 "vscode"）为交互。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..context import HEADLESS, INTERACTIVE, SESSION_START, SUBAGENT, HookContext
from .base import Adapter

SESSION_START_EVENT = "SessionStart"

_EVENT_MAP = {SESSION_START_EVENT: SESSION_START}

#: session_meta 首行可能带较长的 base_instructions，读够一行即可。
_HEAD_LINE_LIMIT = 1048576


class CodexAdapter(Adapter):
    name = "codex"

    def detect(self, payload, env):
        # 自动判别仅用于手动调用；插件入口始终显式指定宿主。
        if env.get("CLAUDECODE") == "1" or env.get("CLAUDE_CODE_SESSION_ID"):
            return False
        if "prompt_id" in payload or payload.get("hook_event_name") == "PostModelSwitch":
            return False
        if "hookEventName" in payload or "conversationId" in payload:
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
            mode=_mode_from_transcript(payload.get("transcript_path")),
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


def _mode_from_transcript(path):
    """读 transcript 首行 session_meta 判断会话形态。读不到或格式不认识就返回空串（未知）。"""
    if not path:
        return ""
    try:
        with Path(path).open("rb") as handle:
            line = handle.readline(_HEAD_LINE_LIMIT)
        entry = json.loads(line.decode("utf-8", "replace"))
    except (OSError, ValueError):
        return ""
    if not isinstance(entry, dict) or entry.get("type") != "session_meta":
        return ""
    meta = entry.get("payload")
    source = meta.get("source") if isinstance(meta, dict) else None
    if isinstance(source, dict):
        return SUBAGENT if "subagent" in source else ""
    if not isinstance(source, str) or not source:
        return ""
    return HEADLESS if source == "exec" else INTERACTIVE
