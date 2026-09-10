import json

import pytest

from modelrc.context import SESSION_START, HookContext
from modelrc.rules import RuleError, load_rules, resolve


def write(config_dir, rules, prompts, main=None):
    (config_dir / "rules.d").mkdir(parents=True, exist_ok=True)
    (config_dir / "prompts").mkdir(parents=True, exist_ok=True)
    for name, body in prompts.items():
        (config_dir / "prompts" / name).write_text(body, encoding="utf-8")
    for name, body in rules.items():
        (config_dir / "rules.d" / name).write_text(json.dumps(body), encoding="utf-8")
    if main is not None:
        (config_dir / "rules.json").write_text(json.dumps(main), encoding="utf-8")


def ctx(**kw):
    base = dict(
        harness="claude",
        event=SESSION_START,
        model="claude-sonnet-example-5-1",
        cwd="/Users/me/work/proj",
        config_dir="/Users/me/.claude-private",
    )
    base.update(kw)
    return HookContext(**base)


def test_model_glob_hit_and_miss(tmp_path):
    write(
        tmp_path,
        {"10-sonnet-example.json": [{"name": "sonnet-example", "match": {"model": "*sonnet-example*"}, "prompt_file": "prompts/a.md"}]},
        {"a.md": "A"},
    )
    assert resolve(ctx(), tmp_path)[0] == "A"
    assert resolve(ctx(model="claude-opus-5"), tmp_path)[0] == ""


def test_missing_model_does_not_match(tmp_path):
    write(
        tmp_path,
        {"10.json": [{"match": {"model": "*sonnet-example*"}, "prompt_file": "prompts/a.md"}]},
        {"a.md": "A"},
    )
    assert resolve(ctx(model=""), tmp_path)[0] == ""


def test_empty_match_matches_everything(tmp_path):
    write(tmp_path, {"10.json": [{"match": {}, "prompt_file": "prompts/a.md"}]}, {"a.md": "A"})
    assert resolve(ctx(model="anything"), tmp_path)[0] == "A"


def test_list_pattern_is_any_of(tmp_path):
    write(
        tmp_path,
        {"10.json": [{"match": {"harness": ["claude", "codex"]}, "prompt_file": "prompts/a.md"}]},
        {"a.md": "A"},
    )
    assert resolve(ctx(harness="codex"), tmp_path)[0] == "A"
    assert resolve(ctx(harness="other"), tmp_path)[0] == ""


def test_cwd_and_config_dir_globs(tmp_path):
    write(
        tmp_path,
        {
            "10.json": [
                {
                    "match": {"cwd": "*/work/*", "config_dir": "*/.claude-private"},
                    "prompt_file": "prompts/a.md",
                }
            ]
        },
        {"a.md": "A"},
    )
    assert resolve(ctx(), tmp_path)[0] == "A"
    assert resolve(ctx(cwd="/Users/me/personal/x"), tmp_path)[0] == ""
    assert resolve(ctx(config_dir="/Users/me/.claude"), tmp_path)[0] == ""


def test_tilde_in_pattern_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/Users/me")
    write(
        tmp_path,
        {"10.json": [{"match": {"cwd": "~/work/*"}, "prompt_file": "prompts/a.md"}]},
        {"a.md": "A"},
    )
    assert resolve(ctx(), tmp_path)[0] == "A"


def test_multiple_hits_concatenate_in_file_order(tmp_path):
    write(
        tmp_path,
        {
            "20-second.json": [{"name": "second", "match": {}, "prompt_file": "prompts/b.md"}],
            "10-first.json": [{"name": "first", "match": {}, "prompt_file": "prompts/a.md"}],
        },
        {"a.md": "A", "b.md": "B"},
    )
    text, hits = resolve(ctx(), tmp_path)
    assert text == "A\n\nB"
    assert [h.name for h in hits] == ["first", "second"]


def test_main_rules_json_comes_before_rules_d(tmp_path):
    write(
        tmp_path,
        {"10.json": [{"name": "d", "match": {}, "prompt_file": "prompts/b.md"}]},
        {"a.md": "A", "b.md": "B"},
        main={"rules": [{"name": "main", "match": {}, "prompt_file": "prompts/a.md"}]},
    )
    assert [h.name for h in resolve(ctx(), tmp_path)[1]] == ["main", "d"]


def test_unknown_match_field_is_rejected(tmp_path):
    write(
        tmp_path,
        {"10.json": [{"match": {"modle": "x"}, "prompt_file": "prompts/a.md"}]},
        {"a.md": "A"},
    )
    with pytest.raises(RuleError, match="未知字段"):
        load_rules(tmp_path)


def test_missing_prompt_file_is_reported(tmp_path):
    write(tmp_path, {"10.json": [{"match": {}, "prompt_file": "prompts/nope.md"}]}, {})
    with pytest.raises(RuleError, match="不存在"):
        resolve(ctx(), tmp_path)


def test_missing_config_dir_yields_no_rules(tmp_path):
    assert load_rules(tmp_path / "nope") == []
    assert resolve(ctx(), tmp_path / "nope")[0] == ""
