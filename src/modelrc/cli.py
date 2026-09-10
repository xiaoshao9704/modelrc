"""modelrc 命令行。作为插件 hook 被调用，也可手工用于自检与调试。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import adapters
from .context import SESSION_START, HookContext, default_config_dir
from .rules import RuleError, load_rules, resolve


def _fail_soft(message):
    """hook 出错绝不能打断会话：写 stderr，正常退出，不注入任何内容。"""
    print(f"modelrc: {message}", file=sys.stderr)
    return 0


def cmd_hook(args, env):
    raw = sys.stdin.read()
    if not raw.strip():
        return _fail_soft("stdin 为空")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _fail_soft(f"stdin 不是合法 JSON: {exc}")
    if not isinstance(payload, dict):
        return _fail_soft("stdin JSON 顶层应是对象")

    if args.harness:
        try:
            adapter = adapters.by_name(args.harness)
        except KeyError as exc:
            return _fail_soft(str(exc))
    else:
        adapter = adapters.detect(payload, env)
        if adapter is None:
            return _fail_soft("无法判别 agent 形态，可用 --harness 显式指定")

    ctx = adapter.parse(payload, env)
    try:
        text, _hits = resolve(ctx, _config_dir(args))
    except (RuleError, json.JSONDecodeError) as exc:
        return _fail_soft(str(exc))

    if text:
        sys.stdout.write(adapter.emit(ctx, text))
    return 0


def cmd_resolve(args, env):
    adapter = adapters.by_name(args.harness)
    ctx = HookContext(
        harness=adapter.name,
        event=args.event,
        model=args.model,
        cwd=args.cwd or str(Path.cwd()),
        config_dir=args.harness_config_dir or "",
    )
    text, hits = resolve(ctx, _config_dir(args))
    if not hits:
        print("没有规则命中。")
        return 0
    print("命中规则: " + ", ".join(f"{r.name}（{r.source.name}）" for r in hits))
    print("-" * 60)
    print(text)
    return 0


def cmd_doctor(args, env):
    config_dir = _config_dir(args)
    ok = True

    version = ".".join(str(n) for n in sys.version_info[:3])
    print(f"[ok] 解释器 {sys.executable}（{version}）")

    exists = config_dir.is_dir()
    ok &= exists
    print(f"[{'ok' if exists else '!!'}] 配置目录 {config_dir}")

    try:
        rules = load_rules(config_dir)
    except (RuleError, json.JSONDecodeError) as exc:
        print(f"[!!] 规则加载失败: {exc}")
        return 1
    print(f"[ok] 规则 {len(rules)} 条")

    known = {a.name for a in adapters.ADAPTERS}
    for rule in rules:
        try:
            rule.render(config_dir)
            print(f"     - {rule.name}（{rule.source.name}）")
        except RuleError as exc:
            ok = False
            print(f"[!!] {exc}")
        harnesses = rule.match.get("harness")
        for value in [harnesses] if isinstance(harnesses, str) else (harnesses or []):
            if value not in known and "*" not in value:
                print(f"[!!] 规则 {rule.name} 的 harness={value} 未注册（已注册: {sorted(known)}）")
                ok = False
    return 0 if ok else 1


def cmd_manifest(args, env):
    """从 adapter 生成插件清单，保证清单与代码不脱节。"""
    command = '"${CLAUDE_PLUGIN_ROOT}/bin/modelrc" hook'
    shared = []
    for adapter in adapters.ADAPTERS:
        for event in adapter.shared_events():
            if event not in shared:
                shared.append(event)
    hooks = {
        event: [{"hooks": [{"type": "command", "command": command}]}] for event in shared
    }
    print(json.dumps({"hooks": hooks}, indent=2, ensure_ascii=False))
    return 0


def _config_dir(args):
    return Path(args.config_dir).expanduser() if args.config_dir else default_config_dir()


def build_parser():
    parser = argparse.ArgumentParser(prog="modelrc", description="按模型向 coding agent 注入提示词")
    parser.add_argument("--config-dir", help="规则与提示词所在目录，默认 $MODELRC_CONFIG_DIR 或 ~/.config/modelrc")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("hook", help="作为 agent 的 hook 被调用，读 stdin JSON")
    p.add_argument("--harness", help="显式指定 agent 形态，省略则自动判别")
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("resolve", help="干跑：给定条件，打印会注入什么")
    p.add_argument("--harness", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--cwd")
    p.add_argument("--harness-config-dir", help="被匹配的 agent 配置目录（对应 match.config_dir）")
    p.add_argument("--event", default=SESSION_START)
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("doctor", help="自检：配置目录、规则、提示词文件")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("manifest", help="从 adapter 生成共用 hooks.json 内容")
    p.set_defaults(func=cmd_manifest)

    return parser


def main(argv=None, env=None):
    import os

    args = build_parser().parse_args(argv)
    return args.func(args, env if env is not None else os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
