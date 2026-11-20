"""Antigravity adapter & CLI subprocess integration tests."""

import io
import json
import subprocess
from pathlib import Path

from modelrc import adapters
from modelrc.cli import main

ROOT = Path(__file__).resolve().parent.parent
MODELRC_BIN = ROOT / "bin" / "modelrc"


def _write_agy_rules(config_dir):
    (config_dir / "rules.d").mkdir(parents=True, exist_ok=True)
    (config_dir / "prompts").mkdir(parents=True, exist_ok=True)
    (config_dir / "prompts" / "antigravity-orchestration.md").write_text(
        "# Main session: direction, delegation, acceptance\nOrchestrate.",
        encoding="utf-8",
    )
    (config_dir / "rules.d" / "30-antigravity.json").write_text(
        json.dumps(
            [
                {
                    "name": "antigravity-orchestration",
                    "match": {
                        "harness": "antigravity",
                        "model": ["*carbon*", "*argon*", "*opus*", "*orchestrator*"],
                    },
                    "prompt_file": "prompts/antigravity-orchestration.md",
                }
            ]
        ),
        encoding="utf-8",
    )


def _run_bin(args, stdin="", env=None):
    import os

    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [str(MODELRC_BIN)] + args,
        input=stdin,
        capture_output=True,
        text=True,
        env=full_env,
    )


def test_session_start_direct_model_matches_case_insensitively(tmp_path):
    cfg = tmp_path / "modelrc_cfg"
    plugin_data = tmp_path / "plugin_data"
    _write_agy_rules(cfg)

    for idx, model_name in enumerate(
        ["gemini-4-carbon-medium", "Gemini 4 Carbon (Medium)", "Claude Opus 5.5 (High)"]
    ):
        payload = {
            "conversationId": f"conv-hit-{idx}",
            "workspacePaths": ["/tmp/proj"],
            "modelName": model_name,
            "hookEventName": "SessionStart",
            "cwd": "/tmp/proj",
        }
        proc = _run_bin(
            ["--config-dir", str(cfg), "hook", "--harness", "antigravity"],
            stdin=json.dumps(payload),
            env={"PLUGIN_DATA": str(plugin_data)},
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out == {
            "injectSteps": [
                {
                    "systemMessage": {
                        "systemMessage": "# Main session: direction, delegation, acceptance\nOrchestrate."
                    }
                }
            ]
        }


def test_session_start_non_matching_models_return_empty_json(tmp_path):
    cfg = tmp_path / "modelrc_cfg"
    plugin_data = tmp_path / "plugin_data"
    _write_agy_rules(cfg)

    for idx, model_name in enumerate(
        ["gemini-4-hydrogen-medium", "Gemini 4 Hydrogen (High)", "Claude Sonnet 5.5 (Medium)"]
    ):
        payload = {
            "conversationId": f"conv-miss-{idx}",
            "workspacePaths": ["/tmp/proj"],
            "modelName": model_name,
            "hookEventName": "SessionStart",
            "cwd": "/tmp/proj",
        }
        proc = _run_bin(
            ["--config-dir", str(cfg), "hook", "--harness", "antigravity"],
            stdin=json.dumps(payload),
            env={"PLUGIN_DATA": str(plugin_data)},
        )
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout) == {}


def test_auto_model_resolves_from_transcript_settings_change(tmp_path):
    cfg = tmp_path / "modelrc_cfg"
    plugin_data = tmp_path / "plugin_data"
    _write_agy_rules(cfg)

    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "USER_INPUT",
                        "content": "<USER_SETTINGS_CHANGE>\nThe user changed setting `Model Selection` from None to Gemini 4 Carbon (Medium).",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    payload = {
        "conversationId": "conv-auto-1",
        "transcriptPath": str(transcript),
        "modelName": "auto",
        "hookEventName": "SessionStart",
        "cwd": "/tmp/proj",
    }
    proc = _run_bin(
        ["--config-dir", str(cfg), "hook", "--harness", "antigravity"],
        stdin=json.dumps(payload),
        env={"PLUGIN_DATA": str(plugin_data)},
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert "injectSteps" in out
    assert "Main session: direction, delegation, acceptance" in out["injectSteps"][0]["systemMessage"]["systemMessage"]


def test_pre_invocation_dedup_and_model_switch(tmp_path):
    cfg = tmp_path / "modelrc_cfg"
    plugin_data = tmp_path / "plugin_data"
    _write_agy_rules(cfg)

    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "USER_INPUT",
                "content": "<USER_SETTINGS_CHANGE>\nThe user changed setting `Model Selection` from None to Gemini 4 Carbon (Medium).",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def invoke(model_name="auto"):
        payload = {
            "conversationId": "conv-dedup",
            "transcriptPath": str(transcript),
            "modelName": model_name,
            "hookEventName": "PreInvocation",
            "invocationNum": 1,
            "cwd": "/tmp/proj",
        }
        proc = _run_bin(
            ["--config-dir", str(cfg), "hook", "--harness", "antigravity"],
            stdin=json.dumps(payload),
            env={"PLUGIN_DATA": str(plugin_data)},
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    # 1st PreInvocation: injects for Gemini 4 Carbon (Medium)
    out1 = invoke()
    assert "injectSteps" in out1

    # 2nd PreInvocation (same model): deduplicated -> {}
    out2 = invoke()
    assert out2 == {}

    # 3rd PreInvocation: transcript switches to Gemini 4 Hydrogen (Medium) -> updates state, returns {}
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "type": "USER_INPUT",
                    "content": "<USER_SETTINGS_CHANGE>\nThe user changed setting `Model Selection` from Gemini 4 Carbon (Medium) to Gemini 4 Hydrogen (Medium).",
                }
            )
            + "\n"
        )
    out3 = invoke()
    assert out3 == {}

    # 4th PreInvocation: transcript switches to Claude Opus 5.5 (Medium) -> injects!
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "type": "USER_INPUT",
                    "content": "<USER_SETTINGS_CHANGE>\nThe user changed setting `Model Selection` from Gemini 4 Hydrogen (Medium) to Claude Opus 5.5 (Medium).",
                }
            )
            + "\n"
        )
    out4 = invoke()
    assert "injectSteps" in out4

    # Verify state persisted the dotted 5.5 model name accurately
    state = json.loads((plugin_data / "antigravity-state.json").read_text(encoding="utf-8"))
    assert state["conv-dedup"] == "Claude Opus 5.5 (Medium)"


def test_swarm_worker_guard_in_last_user_input_and_transcript(tmp_path):
    cfg = tmp_path / "modelrc_cfg"
    plugin_data = tmp_path / "plugin_data"
    _write_agy_rules(cfg)

    # Case 1: <swarm_worker> in lastUserInput
    p1 = {
        "conversationId": "conv-worker-1",
        "modelName": "Gemini 4 Carbon (Medium)",
        "lastUserInput": "Hello <swarm_worker> execute task",
        "hookEventName": "SessionStart",
        "cwd": "/tmp/proj",
    }
    proc1 = _run_bin(
        ["--config-dir", str(cfg), "hook", "--harness", "antigravity"],
        stdin=json.dumps(p1),
        env={"PLUGIN_DATA": str(plugin_data)},
    )
    assert proc1.returncode == 0
    assert json.loads(proc1.stdout) == {}

    # Case 2: <swarm_worker> in transcriptPath head
    transcript = tmp_path / "worker_transcript.jsonl"
    transcript.write_text(
        json.dumps({"type": "SYSTEM", "content": "<swarm_worker>You are worker</swarm_worker>"}) + "\n",
        encoding="utf-8",
    )
    p2 = {
        "conversationId": "conv-worker-2",
        "modelName": "Gemini 4 Carbon (Medium)",
        "transcriptPath": str(transcript),
        "lastUserInput": "continue",
        "hookEventName": "PreInvocation",
        "cwd": "/tmp/proj",
    }
    proc2 = _run_bin(
        ["--config-dir", str(cfg), "hook", "--harness", "antigravity"],
        stdin=json.dumps(p2),
        env={"PLUGIN_DATA": str(plugin_data)},
    )
    assert proc2.returncode == 0
    assert json.loads(proc2.stdout) == {}


def test_state_prunes_above_500_conversations(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "modelrc_cfg"
    plugin_data = tmp_path / "plugin_data"
    plugin_data.mkdir()
    _write_agy_rules(cfg)

    old_state = {f"old-{i}": "Gemini 4 Carbon (Medium)" for i in range(505)}
    (plugin_data / "antigravity-state.json").write_text(json.dumps(old_state), encoding="utf-8")

    payload = {
        "conversationId": "new-conv",
        "modelName": "Gemini 4 Carbon (Medium)",
        "hookEventName": "SessionStart",
        "cwd": "/tmp/proj",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = main(
        ["--config-dir", str(cfg), "hook", "--harness", "antigravity"],
        env={"PLUGIN_DATA": str(plugin_data)},
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "injectSteps" in out

    new_state = json.loads((plugin_data / "antigravity-state.json").read_text(encoding="utf-8"))
    assert len(new_state) == 500
    assert "new-conv" in new_state
    assert "old-0" not in new_state


def test_antigravity_config_dir_from_env():
    agy = adapters.by_name("antigravity")
    ctx = agy.parse({"cwd": "/tmp"}, {"ANTIGRAVITY_CONFIG_DIR": "/custom/agy"})
    assert ctx.config_dir == "/custom/agy"
