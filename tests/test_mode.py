"""会话形态 mode：codex transcript 识别、MODELRC_ROLE 覆盖、规则匹配、hook 端到端。"""

import io
import json

import pytest

from modelrc import adapters
from modelrc.adapters.codex import _mode_from_transcript
from modelrc.cli import main
from modelrc.context import HEADLESS, INTERACTIVE, SESSION_START, SUBAGENT, HookContext, apply_role_override
from modelrc.rules import resolve


def _transcript(tmp_path, source, name="rollout.jsonl"):
    path = tmp_path / name
    meta = {"type": "session_meta", "payload": {"originator": "x", "source": source}}
    path.write_text(json.dumps(meta) + "\n" + json.dumps({"type": "event"}) + "\n", encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    "source,expected",
    [
        ("exec", HEADLESS),
        ("vscode", INTERACTIVE),
        ("cli", INTERACTIVE),
        ({"subagent": {"other": "guardian"}}, SUBAGENT),
        ({"subagent": {"thread_spawn": {"depth": 1}}}, SUBAGENT),
        ({"unknown": 1}, ""),
        ("", ""),
    ],
)
def test_codex_mode_from_session_meta(tmp_path, source, expected):
    assert _mode_from_transcript(_transcript(tmp_path, source)) == expected


def test_codex_mode_unknown_on_bad_transcript(tmp_path):
    assert _mode_from_transcript("") == ""
    assert _mode_from_transcript(str(tmp_path / "missing.jsonl")) == ""
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n", encoding="utf-8")
    assert _mode_from_transcript(str(bad)) == ""
    other = tmp_path / "other.jsonl"
    other.write_text(json.dumps({"type": "event", "payload": {"source": "exec"}}) + "\n", encoding="utf-8")
    assert _mode_from_transcript(str(other)) == ""


def test_codex_parse_sets_mode(tmp_path):
    payload = {"hook_event_name": "SessionStart", "model": "gpt-6.2-astra", "cwd": "/w",
               "session_id": "s", "source": "startup", "transcript_path": _transcript(tmp_path, "exec")}
    assert adapters.by_name("codex").parse(payload, {}).mode == HEADLESS


def _ctx(mode=""):
    return HookContext(harness="codex", event=SESSION_START, model="m", cwd="/w", config_dir="/c", mode=mode)


@pytest.mark.parametrize(
    "role,expected",
    [("worker", HEADLESS), ("headless", HEADLESS), (" Worker ", HEADLESS), ("subagent", SUBAGENT),
     ("", INTERACTIVE), ("nonsense", INTERACTIVE)],
)
def test_role_override(role, expected):
    env = {"MODELRC_ROLE": role} if role else {}
    assert apply_role_override(_ctx(INTERACTIVE), env).mode == expected


def _rules(tmp_path, match):
    (tmp_path / "rules.json").write_text(json.dumps([{"name": "r", "match": match, "prompt_file": "p.md"}]))
    (tmp_path / "p.md").write_text("P")


def test_rule_mode_interactive_or_unknown(tmp_path):
    _rules(tmp_path, {"mode": ["interactive", ""]})
    assert resolve(_ctx(INTERACTIVE), tmp_path)[0] == "P"
    assert resolve(_ctx(""), tmp_path)[0] == "P"
    assert resolve(_ctx(HEADLESS), tmp_path)[0] == ""
    assert resolve(_ctx(SUBAGENT), tmp_path)[0] == ""


def test_rule_without_mode_still_matches_everything(tmp_path):
    _rules(tmp_path, {"harness": "codex"})
    for mode in (INTERACTIVE, HEADLESS, SUBAGENT, ""):
        assert resolve(_ctx(mode), tmp_path)[0] == "P"


def _hook(tmp_path, monkeypatch, capsys, harness, payload, env):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert main(["--config-dir", str(tmp_path), "hook", "--harness", harness], env=env) == 0
    return capsys.readouterr().out


def test_hook_skips_codex_exec(tmp_path, monkeypatch, capsys):
    _rules(tmp_path, {"harness": "codex", "mode": ["interactive", ""]})
    base = {"hook_event_name": "SessionStart", "model": "gpt-6.2-astra", "cwd": "/w", "session_id": "s"}
    out = _hook(tmp_path, monkeypatch, capsys, "codex",
                dict(base, transcript_path=_transcript(tmp_path, "exec", "a.jsonl")), {})
    assert out == ""
    out = _hook(tmp_path, monkeypatch, capsys, "codex",
                dict(base, transcript_path=_transcript(tmp_path, "vscode", "b.jsonl")), {})
    assert json.loads(out)["hookSpecificOutput"]["additionalContext"] == "P"


def test_hook_role_env_skips_antigravity(tmp_path, monkeypatch, capsys):
    _rules(tmp_path, {"harness": "antigravity", "mode": ["interactive", ""]})
    payload = {"hookEventName": "SessionStart", "modelName": "gemini-4-neon-high", "cwd": "/w"}
    env = {"PLUGIN_DATA": str(tmp_path / "data")}
    assert "injectSteps" in _hook(tmp_path, monkeypatch, capsys, "antigravity", payload, env)
    assert _hook(tmp_path, monkeypatch, capsys, "antigravity", payload,
                 dict(env, MODELRC_ROLE="worker")) == "{}"


def test_resolve_cli_accepts_mode(tmp_path, capsys):
    _rules(tmp_path, {"mode": ["interactive", ""]})
    assert main(["--config-dir", str(tmp_path), "resolve", "--harness", "codex", "--model", "m",
                 "--mode", "headless"]) == 0
    assert "没有规则命中" in capsys.readouterr().out
