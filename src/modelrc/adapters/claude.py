"""Claude Code adapter。

已核对 claude-code 2.1.258：
- SessionStart 入参含可选 model；PostModelSwitch 入参含 from_model / to_model
- 两者输出都支持 hookSpecificOutput.additionalContext
- hook 子进程环境含 CLAUDECODE=1 与 CLAUDE_CODE_SESSION_ID
"""

from __future__ import annotations

import json
from pathlib import Path

from ..context import MODEL_SWITCH, SESSION_START, HookContext
from .base import Adapter

SESSION_START_EVENT = "SessionStart"
MODEL_SWITCH_EVENT = "PostModelSwitch"

_EVENT_MAP = {SESSION_START_EVENT: SESSION_START, MODEL_SWITCH_EVENT: MODEL_SWITCH}


class ClaudeAdapter(Adapter):
    name = "claude"

    def detect(self, payload, env):
        if env.get("CLAUDECODE") == "1" or env.get("CLAUDE_CODE_SESSION_ID"):
            return True
        # payload 兜底：这几个字段是 Claude Code hook 入参独有的。
        return any(k in payload for k in ("permission_mode", "prompt_id", "transcript_path"))

    def parse(self, payload, env):
        native = payload.get("hook_event_name") or SESSION_START_EVENT
        # 切模型后生效的是新模型；SessionStart 才读 model。
        model = payload.get("to_model") if native == MODEL_SWITCH_EVENT else payload.get("model")
        config_dir = Path(env.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
        return HookContext(
            harness=self.name,
            event=_EVENT_MAP.get(native, native),
            model=model or "",
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
        return [SESSION_START_EVENT, MODEL_SWITCH_EVENT]

    def shared_events(self):
        # PostModelSwitch 是 Claude 独有的，不进共用 hooks.json，
        # 免得 Codex 读到不认识的事件名。它由 .claude-plugin/plugin.json 单独声明。
        return [SESSION_START_EVENT]
