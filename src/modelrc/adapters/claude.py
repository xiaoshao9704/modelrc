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
        # permission_mode / transcript_path 两个宿主都有，不能作为判别依据。
        return "prompt_id" in payload or payload.get("hook_event_name") == MODEL_SWITCH_EVENT

    def parse(self, payload, env):
        native = payload.get("hook_event_name") or SESSION_START_EVENT
        # 切模型后生效的是新模型；SessionStart 才读 model。
        model = payload.get("to_model") if native == MODEL_SWITCH_EVENT else payload.get("model")
        if not model and native == SESSION_START_EVENT:
            # resume / fork 起来的会话，SessionStart 的 model 是空的（实测确认），
            # 此时从 transcript 里回退取上一次实际使用的模型。
            # 若 resume 时换了模型，PostModelSwitch 会带 to_model 再触发一次修正。
            model = _model_from_transcript(payload.get("transcript_path"))
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


def _model_from_transcript(path, tail_bytes=262144):
    """从 transcript 末尾回溯，取最近一条 assistant 记录里的模型名。

    只读文件尾部：transcript 可能很大，而我们只关心最后几条。
    读不到就返回空串——注入与否交给规则匹配决定，绝不在 hook 里抛异常。
    """
    if not path:
        return ""
    try:
        target = Path(path)
        size = target.stat().st_size
        with target.open("rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
                handle.readline()  # 丢弃被截断的半行
            chunk = handle.read()
    except OSError:
        return ""

    for line in reversed(chunk.decode("utf-8", "replace").splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        message = entry.get("message")
        model = message.get("model") if isinstance(message, dict) else None
        model = model or entry.get("model")
        if isinstance(model, str) and model:
            return model
    return ""
