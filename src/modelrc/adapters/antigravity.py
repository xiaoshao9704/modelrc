"""Antigravity adapter.

Supports Antigravity lifecycle hooks (`SessionStart` and `PreInvocation`):
- Parses camelCase stdin metadata (`modelName`, `hookEventName`, `conversationId`,
  `transcriptPath`, `workspacePaths`, `cwd`, `lastUserInput`).
- Resolves concrete model IDs from `transcriptPath` `<USER_SETTINGS_CHANGE>` entries
  when `modelName` is empty or `"auto"`.
- Guards against injecting main-session prompts into `<swarm_worker>` conversations.
- Tracks per-conversation last resolved model in `PLUGIN_DATA` (with cache fallback)
  so `PreInvocation` acts as an on-demand `model_switch` detector without repeating
  `systemMessage` injections every turn.
- Emits Antigravity's `{"injectSteps": [{"systemMessage": {"systemMessage": ...}}]}`
  format, or `"{}"` when nothing should be injected.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from pathlib import Path

from ..context import MODEL_SWITCH, SESSION_START, HookContext
from .base import Adapter

SESSION_START_EVENT = "SessionStart"
PRE_INVOCATION_EVENT = "PreInvocation"

_EVENT_MAP = {
    SESSION_START_EVENT: SESSION_START,
    PRE_INVOCATION_EVENT: SESSION_START,
}

_WORKER_MARKER = "<swarm_worker>"
_WORKER_HEAD_BYTES = 32768
_TRANSCRIPT_TAIL_BYTES = 262144
_MAX_CONVERSATIONS = 500

_MODEL_CHANGE_RE = re.compile(
    r"<USER_SETTINGS_CHANGE>[^<]*?changed setting `Model Selection` from [^\n`]*? to "
    r"([^\n<]+?)(?:\.(?=\s|$)|(?=\s*(?:\n|<|$)))"
)


class AntigravityAdapter(Adapter):
    name = "antigravity"

    def detect(self, payload, env):
        if env.get("CLAUDECODE") == "1" or env.get("CLAUDE_CODE_SESSION_ID"):
            return False
        if "model" in payload or "hook_event_name" in payload or "transcript_path" in payload:
            return False
        return (
            "hookEventName" in payload
            or "modelName" in payload
            or "conversationId" in payload
            or bool(env.get("ANTIGRAVITY_CONFIG_DIR"))
        )

    def parse(self, payload, env):
        native = payload.get("hookEventName") or SESSION_START_EVENT
        transcript_path = payload.get("transcriptPath") or ""
        model = _resolve_model(payload.get("modelName"), transcript_path)
        config_dir = Path(
            env.get("ANTIGRAVITY_CONFIG_DIR") or "~/.gemini/config"
        ).expanduser()
        cwd = payload.get("cwd") or ""
        if not cwd:
            workspace_paths = payload.get("workspacePaths")
            if isinstance(workspace_paths, list) and workspace_paths:
                cwd = str(workspace_paths[0] or "")
        return HookContext(
            harness=self.name,
            event=_EVENT_MAP.get(native, SESSION_START),
            model=model,
            cwd=cwd,
            config_dir=str(config_dir),
            session_id=payload.get("conversationId") or "",
            native_event=native,
            raw=payload,
        )

    def prepare_hook(self, ctx, env):
        """Apply worker guard and per-conversation model deduplication.

        Returns `(updated_ctx, should_resolve)`.
        """
        if _is_swarm_worker(ctx.raw):
            return ctx, False

        native = ctx.native_event or SESSION_START_EVENT
        conv_id = ctx.session_id
        if not conv_id:
            return ctx, True

        state_path = _state_file_path(env)
        state = _load_state(state_path)

        if native == SESSION_START_EVENT or conv_id not in state:
            _save_conversation_model(state, state_path, conv_id, ctx.model, env)
            return ctx, True

        # Subsequent PreInvocation for a known conversation.
        last_model = state.get(conv_id, "")
        if not ctx.model or ctx.model == last_model:
            return ctx, False

        _save_conversation_model(state, state_path, conv_id, ctx.model, env)
        # replace 保留 mode 等其余字段（含 MODELRC_ROLE 覆盖结果）。
        return replace(ctx, event=MODEL_SWITCH), True

    def emit(self, ctx, text):
        if not text:
            return "{}"
        return json.dumps(
            {"injectSteps": [{"systemMessage": {"systemMessage": text}}]},
            ensure_ascii=False,
        )

    def emit_empty(self, ctx):
        return "{}"

    def native_events(self):
        return [SESSION_START_EVENT, PRE_INVOCATION_EVENT]


def _resolve_model(raw_model_name, transcript_path):
    raw_model = str(raw_model_name or "").strip()
    if raw_model and raw_model.lower() != "auto":
        return raw_model
    return _model_from_antigravity_transcript(transcript_path)


def _extract_text_segments(entry):
    """Collect string values from a decoded JSON transcript entry."""
    parts = []
    if isinstance(entry, str):
        parts.append(entry)
    elif isinstance(entry, dict):
        for val in entry.values():
            parts.extend(_extract_text_segments(val))
    elif isinstance(entry, list):
        for item in entry:
            parts.extend(_extract_text_segments(item))
    return parts


def _read_tail_text(path, tail_bytes=_TRANSCRIPT_TAIL_BYTES):
    if not path:
        return ""
    try:
        target = Path(path)
        size = target.stat().st_size
        with target.open("rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
                handle.readline()
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _model_from_antigravity_transcript(path, tail_bytes=_TRANSCRIPT_TAIL_BYTES):
    text = _read_tail_text(path, tail_bytes=tail_bytes)
    if not text:
        return ""

    latest = ""
    raw_lines = []
    for line in text.splitlines():
        if not line.strip():
            raw_lines.append(line)
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            raw_lines.append(line)
            continue
        for seg in _extract_text_segments(entry):
            for match in _MODEL_CHANGE_RE.finditer(seg):
                candidate = match.group(1).strip()
                if candidate:
                    latest = candidate

    if raw_lines:
        for match in _MODEL_CHANGE_RE.finditer("\n".join(raw_lines)):
            candidate = match.group(1).strip()
            if candidate:
                latest = candidate
    return latest


def _is_swarm_worker(payload):
    last_input = payload.get("lastUserInput") or ""
    if isinstance(last_input, str) and _WORKER_MARKER in last_input:
        return True

    transcript_path = payload.get("transcriptPath") or ""
    if not transcript_path:
        return False
    try:
        target = Path(transcript_path)
        with target.open("rb") as handle:
            head = handle.read(_WORKER_HEAD_BYTES).decode("utf-8", "replace")
    except OSError:
        return False

    if _WORKER_MARKER in head or "\\u003cswarm_worker\\u003e" in head:
        return True
    return False


def _state_file_candidates(env):
    plugin_data = env.get("PLUGIN_DATA")
    if plugin_data:
        return [Path(plugin_data).expanduser() / "antigravity-state.json"]
    xdg_cache = env.get("XDG_CACHE_HOME")
    base = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
    return [
        base / "modelrc" / "antigravity-state.json",
        Path("/tmp/modelrc-state/antigravity-state.json"),
    ]


def _state_file_path(env):
    candidates = _state_file_candidates(env)
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _load_state(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_conversation_model(state, path, conv_id, model, env=None):
    if conv_id in state:
        state.pop(conv_id, None)
    state[conv_id] = model
    while len(state) > _MAX_CONVERSATIONS:
        oldest = next(iter(state))
        state.pop(oldest, None)
    targets = [path]
    for fallback in _state_file_candidates(env or {}):
        if fallback not in targets:
            targets.append(fallback)
    payload = json.dumps(state, ensure_ascii=False)
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, target)
            return
        except OSError:
            continue
