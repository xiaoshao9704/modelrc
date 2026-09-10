"""归一化的 hook 上下文。核心逻辑只认识这个结构，不认识任何具体 agent。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: 归一化事件名。adapter 负责在自己的原生事件名与这些之间做映射。
SESSION_START = "session_start"
MODEL_SWITCH = "model_switch"


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


def default_config_dir() -> Path:
    """modelrc 自身的配置目录：规则与提示词都住在这里，不在本仓库内。"""
    env = os.environ.get("MODELRC_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "modelrc"
