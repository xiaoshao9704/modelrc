"""归一化的 hook 上下文。核心逻辑只认识这个结构，不认识任何具体 agent。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

#: 归一化事件名。adapter 负责在自己的原生事件名与这些之间做映射。
SESSION_START = "session_start"
MODEL_SWITCH = "model_switch"

#: 归一化会话形态（match.mode）。识别不出时为空串，表示未知。
INTERACTIVE = "interactive"
HEADLESS = "headless"
SUBAGENT = "subagent"
#: 外部编排宿主派发的执行者（目前为 Orca worker）。
WORKER = "worker"

#: Orca 给结构化 worker 预分配的终端句柄前缀；主会话与用户自开的终端没有这个前缀。
_ORCA_WORKER_HANDLE_PREFIX = "structworker_"

#: 派发方显式声明"这是被派发的执行者"。hook 子进程会继承它，任何宿主都适用。
ROLE_ENV = "MODELRC_ROLE"
_ROLE_TO_MODE = {"worker": HEADLESS, "headless": HEADLESS, "subagent": SUBAGENT}


@dataclass(frozen=True)
class HookContext:
    harness: str
    event: str
    model: str
    cwd: str
    config_dir: str
    session_id: str = ""
    native_event: str = ""
    raw: dict = field(default_factory=dict, repr=False)
    mode: str = ""
    host: str = ""


def apply_role_override(ctx: HookContext, env) -> HookContext:
    """MODELRC_ROLE 优先于 adapter 自己识别出的 mode。未设置或取值未知时原样返回。"""
    mode = _ROLE_TO_MODE.get((env.get(ROLE_ENV) or "").strip().lower())
    return replace(ctx, mode=mode) if mode else ctx


def apply_host(ctx: HookContext, env) -> HookContext:
    """根据 hook 进程继承的环境变量识别外部宿主；Orca 派发的 worker 的 mode 记为 worker。"""
    if not (env.get("ORCA_AGENT_SESSION_ID") or "").strip():
        return replace(ctx, host="")
    handle = (env.get("ORCA_TERMINAL_HANDLE") or "").strip()
    mode = WORKER if handle.startswith(_ORCA_WORKER_HANDLE_PREFIX) else ctx.mode
    return replace(ctx, host="orca", mode=mode)


def default_config_dir() -> Path:
    """modelrc 自身的配置目录：规则与提示词都住在这里，不在本仓库内。"""
    env = os.environ.get("MODELRC_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "modelrc"
