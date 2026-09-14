"""契约测试：对所有已注册 adapter 跑同一组断言。

新增 adapter 后无需改本文件，它会自动被覆盖。
"""

import json

import pytest

from modelrc import adapters
from modelrc.context import HookContext

ALL = adapters.ADAPTERS

#: 真实宿主入参；共享字段无法区分宿主，自动判别还需要环境信息。
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
        "transcript_path": None,
        "permission_mode": "default",
        "source": "startup",
    },
}

SAMPLE_ENVS = {"claude": {"CLAUDECODE": "1"}, "codex": {"CODEX_HOME": "/custom/codex"}}


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_name_is_registered(adapter):
    assert adapter.name
    assert adapters.by_name(adapter.name) is adapter


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_has_sample(adapter):
    assert adapter.name in SAMPLES, f"新 adapter {adapter.name} 需要在 SAMPLES 里补一份样本 payload"


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_detects_own_sample(adapter):
    assert adapter.detect(SAMPLES[adapter.name], SAMPLE_ENVS[adapter.name]) is True


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.name)
def test_does_not_detect_foreign_sample(adapter):
    """判别必须互斥，否则 hook 会用错 adapter 解析。"""
    for name, payload in SAMPLES.items():
        if name != adapter.name:
            assert adapter.detect(payload, SAMPLE_ENVS[name]) is False, f"{adapter.name} 误认了 {name} 的 payload"


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
    assert adapters.detect(SAMPLES[adapter.name], SAMPLE_ENVS[adapter.name]) is adapter


def test_shared_payload_without_host_environment_is_ambiguous():
    assert adapters.detect(SAMPLES["codex"], {}) is None


def test_claude_with_inherited_codex_home():
    env = {"CLAUDECODE": "1", "CODEX_HOME": "/custom/codex"}
    assert adapters.detect(SAMPLES["claude"], env).name == "claude"
    assert not adapters.by_name("codex").detect(SAMPLES["claude"], env)


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


# ---- resume：SessionStart 的 model 为空时从 transcript 回退 ------------------
#
# 实测（claude-code 2.1.258）：resume 起来的会话 SessionStart 会触发，但 model 字段
# 是空的。没有回退的话，带 model 约束的规则在 resume 时会静默不命中。


def _transcript(tmp_path, lines):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    return str(p)


def test_resume_falls_back_to_transcript_model(tmp_path):
    claude = adapters.by_name("claude")
    path = _transcript(tmp_path, [
        {"type": "user", "message": {"role": "user"}},
        {"type": "assistant", "message": {"model": "claude-sonnet-example-5-1"}},
    ])
    ctx = claude.parse(
        {"hook_event_name": "SessionStart", "source": "resume", "cwd": "/tmp",
         "transcript_path": path},
        {},
    )
    assert ctx.model == "claude-sonnet-example-5-1"


def test_transcript_fallback_takes_the_last_model(tmp_path):
    claude = adapters.by_name("claude")
    path = _transcript(tmp_path, [
        {"type": "assistant", "message": {"model": "claude-opus-5"}},
        {"type": "assistant", "message": {"model": "claude-sonnet-example-5-1"}},
    ])
    ctx = claude.parse(
        {"hook_event_name": "SessionStart", "cwd": "/tmp", "transcript_path": path}, {}
    )
    assert ctx.model == "claude-sonnet-example-5-1"


def test_explicit_model_wins_over_transcript(tmp_path):
    claude = adapters.by_name("claude")
    path = _transcript(tmp_path, [{"type": "assistant", "message": {"model": "old-model"}}])
    ctx = claude.parse(
        {"hook_event_name": "SessionStart", "model": "claude-opus-5", "cwd": "/tmp",
         "transcript_path": path},
        {},
    )
    assert ctx.model == "claude-opus-5"


def test_model_switch_does_not_consult_transcript(tmp_path):
    """切模型事件自带 to_model，不该被 transcript 里的旧模型污染。"""
    claude = adapters.by_name("claude")
    path = _transcript(tmp_path, [{"type": "assistant", "message": {"model": "old-model"}}])
    ctx = claude.parse(
        {"hook_event_name": "PostModelSwitch", "to_model": "claude-sonnet-example-5-1",
         "cwd": "/tmp", "transcript_path": path},
        {},
    )
    assert ctx.model == "claude-sonnet-example-5-1"


def test_transcript_fallback_survives_bad_input(tmp_path):
    """transcript 缺失、坏行、无 model 记录，都只能返回空串，不能抛异常。"""
    claude = adapters.by_name("claude")
    bad = tmp_path / "broken.jsonl"
    bad.write_text("not json\n{\"type\":\"user\"}\n", encoding="utf-8")
    for path in (None, "", str(tmp_path / "missing.jsonl"), str(tmp_path), str(bad)):
        ctx = claude.parse(
            {"hook_event_name": "SessionStart", "cwd": "/tmp", "transcript_path": path}, {}
        )
        assert ctx.model == "", f"path={path!r} 应回退为空串"


def test_transcript_fallback_reads_only_the_tail(tmp_path):
    """transcript 可能很大，只读尾部；被截断的半行不能让解析失败。"""
    claude = adapters.by_name("claude")
    p = tmp_path / "big.jsonl"
    filler = json.dumps({"type": "user", "message": {"role": "user", "pad": "x" * 2000}})
    lines = [filler] * 500 + [json.dumps({"type": "assistant", "message": {"model": "tail-model"}})]
    p.write_text("\n".join(lines), encoding="utf-8")
    assert p.stat().st_size > 262144
    ctx = claude.parse(
        {"hook_event_name": "SessionStart", "cwd": "/tmp", "transcript_path": str(p)}, {}
    )
    assert ctx.model == "tail-model"
