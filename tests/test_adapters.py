"""契约测试：对所有已注册 adapter 跑同一组断言。

新增 adapter 后无需改本文件，它会自动被覆盖。
"""

import json

import pytest

from modelrc import adapters
from modelrc.context import HookContext

ALL = adapters.ADAPTERS

#: 每个 adapter 一份能被自己 detect 的最小 payload，用于契约测试。
SAMPLES = {
    "claude": {
        "hook_event_name": "SessionStart",
        "source": "startup",
        "model": "claude-sonnet-example-5-1",
        "cwd": "/tmp/proj",
        "session_id": "s1",
        "permission_mode": "default",
        "transcript_path": "/tmp/t.jsonl",
    },
    "codex": {
        "hook_event_name": "SessionStart",
        "model": "gpt-6-astra",
        "cwd": "/tmp/proj",
        "session_id": "s1",
        "turn_id": "t1",
    },
}


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_name_is_registered(adapter):
    assert adapter.name
    assert adapters.by_name(adapter.name) is adapter


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_has_sample(adapter):
    assert adapter.name in SAMPLES, f"新 adapter {adapter.name} 需要在 SAMPLES 里补一份样本 payload"


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_detects_own_sample(adapter):
    assert adapter.detect(SAMPLES[adapter.name], {}) is True


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_does_not_detect_foreign_sample(adapter):
    """判别必须互斥，否则 hook 会用错 adapter 解析。"""
    for name, payload in SAMPLES.items():
        if name != adapter.name:
            assert adapter.detect(payload, {}) is False, f"{adapter.name} 误认了 {name} 的 payload"


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_parse_normalizes(adapter):
    ctx = adapter.parse(SAMPLES[adapter.name], {})
    assert isinstance(ctx, HookContext)
    assert ctx.harness == adapter.name
    assert ctx.model
    assert ctx.cwd == "/tmp/proj"
    assert ctx.config_dir
    assert ctx.native_event == "SessionStart"


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_emit_roundtrip(adapter):
    ctx = adapter.parse(SAMPLES[adapter.name], {})
    out = json.loads(adapter.emit(ctx, "多行\n提示词"))
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert out["hookSpecificOutput"]["additionalContext"] == "多行\n提示词"


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_events_are_consistent(adapter):
    native = adapter.native_events()
    assert native, "至少要挂载一个事件"
    assert set(adapter.shared_events()) <= set(native)


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_registry_detect_picks_right_adapter(adapter):
    assert adapters.detect(SAMPLES[adapter.name], {}) is adapter


# ---- adapter 各自的特殊行为 ------------------------------------------------


def test_claude_env_detection():
    claude = adapters.by_name("claude")
    assert claude.detect({}, {"CLAUDECODE": "1"}) is True


def test_claude_model_switch_uses_new_model():
    claude = adapters.by_name("claude")
    ctx = claude.parse(
        {
            "hook_event_name": "PostModelSwitch",
            "from_model": "claude-opus-5",
            "to_model": "claude-sonnet-example-5-1",
            "cwd": "/tmp",
        },
        {},
    )
    assert ctx.model == "claude-sonnet-example-5-1"
    assert ctx.event == "model_switch"


def test_claude_config_dir_from_env():
    claude = adapters.by_name("claude")
    ctx = claude.parse({"cwd": "/tmp"}, {"CLAUDE_CONFIG_DIR": "/custom/claude"})
    assert ctx.config_dir == "/custom/claude"


def test_codex_excludes_model_switch_event():
    """Codex 没有 PostModelSwitch，不能把它写进共用 hooks.json。"""
    assert "PostModelSwitch" not in adapters.by_name("codex").native_events()
    assert "PostModelSwitch" not in adapters.by_name("claude").shared_events()
