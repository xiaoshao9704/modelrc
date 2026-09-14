import io
import json
from pathlib import Path

import pytest

from modelrc.cli import main
from test_adapters import SAMPLES


ROOT = Path(__file__).resolve().parent.parent


def test_codex_plugin_command_selects_host_despite_inherited_claude_env(tmp_path, monkeypatch, capsys):
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
    hooks = json.loads((ROOT / manifest["hooks"]).read_text())["hooks"]
    command = hooks["SessionStart"][0]["hooks"][0]["command"]
    assert command.endswith(" hook --harness codex")
    (tmp_path / "rules.json").write_text(json.dumps([{
        "match": {"harness": "codex", "model": "gpt-6-astra", "config_dir": "/custom/codex"},
        "prompt_file": "prompt.md",
    }]))
    (tmp_path / "prompt.md").write_text("codex context")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(SAMPLES["codex"])))
    assert main(["--config-dir", str(tmp_path), "hook", "--harness", "codex"],
                env={"CLAUDECODE": "1", "CODEX_HOME": "/custom/codex"}) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"] == "codex context"


@pytest.mark.parametrize("harness,filename", [("claude", "hooks.json"), ("codex", "codex-hooks.json")])
def test_generated_manifest_matches_shipped_file(harness, filename, capsys):
    assert main(["manifest", "--harness", harness]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads((ROOT / "hooks" / filename).read_text())


@pytest.mark.parametrize("failure", ["pattern", "encoding", "parse"])
def test_hook_errors_do_not_break_session(tmp_path, monkeypatch, capsys, failure):
    (tmp_path / "rules.json").write_text(json.dumps([{
        "match": {"model": 42} if failure == "pattern" else {},
        "prompt_file": "prompt.md",
    }]))
    (tmp_path / "prompt.md").write_bytes(b"\xff" if failure == "encoding" else b"prompt")
    payload = dict(SAMPLES["codex"])
    env = {"CODEX_HOME": 42} if failure == "parse" else {}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert main(["--config-dir", str(tmp_path), "hook", "--harness", "codex"], env=env) == 0
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("modelrc:")
