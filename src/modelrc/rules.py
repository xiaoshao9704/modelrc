"""规则的加载与匹配。这一层完全不认识具体 agent，只吃 HookContext。"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path

from .context import HookContext

#: 允许出现在 match 里的字段，与 HookContext 的同名属性对应。
MATCH_FIELDS = ("harness", "model", "config_dir", "cwd", "event")

#: 多条规则命中时，按顺序拼接，用空行分隔。
JOIN = "\n\n"


class RuleError(ValueError):
    """规则文件写错了。带上出处，便于定位。"""


@dataclass(frozen=True)
class Rule:
    name: str
    match: dict
    prompt_file: str
    source: Path

    def matches(self, ctx: HookContext) -> bool:
        for field_name, pattern in self.match.items():
            value = getattr(ctx, field_name, "")
            if not _match_value(value, pattern):
                return False
        return True

    def render(self, config_dir: Path) -> str:
        path = Path(self.prompt_file).expanduser()
        if not path.is_absolute():
            path = config_dir / path
        if not path.is_file():
            raise RuleError(f"规则 {self.name}（{self.source}）指向的提示词文件不存在: {path}")
        return path.read_text(encoding="utf-8").strip()


def _match_value(value: str, pattern) -> bool:
    """glob 匹配。列表表示"任一命中"。路径字段先展开 ~ 再比。

    用 fnmatch 语义：``*`` 会跨越 ``/``，所以 ``*/work/*`` 能匹配任意深度。
    """
    patterns = pattern if isinstance(pattern, list) else [pattern]
    if not patterns:
        return True
    candidates = {value or ""}
    if value and ("/" in value or value.startswith("~")):
        candidates.add(str(Path(value).expanduser()))
    for pat in patterns:
        expanded = str(Path(pat).expanduser()) if pat.startswith("~") else pat
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, expanded):
                return True
    return False


def _parse_rules(payload, source: Path) -> list[Rule]:
    if isinstance(payload, dict):
        payload = payload.get("rules", [])
    if not isinstance(payload, list):
        raise RuleError(f"{source}: 顶层应是规则数组，或含 rules 数组的对象")

    rules = []
    for index, item in enumerate(payload):
        where = f"{source}[{index}]"
        if not isinstance(item, dict):
            raise RuleError(f"{where}: 规则应是对象")
        prompt_file = item.get("prompt_file")
        if not prompt_file:
            raise RuleError(f"{where}: 缺少 prompt_file")
        match = item.get("match", {})
        if not isinstance(match, dict):
            raise RuleError(f"{where}: match 应是对象")
        unknown = set(match) - set(MATCH_FIELDS)
        if unknown:
            raise RuleError(
                f"{where}: match 含未知字段 {sorted(unknown)}，可用字段 {list(MATCH_FIELDS)}"
            )
        rules.append(
            Rule(
                name=item.get("name") or f"{source.stem}#{index}",
                match=match,
                prompt_file=prompt_file,
                source=source,
            )
        )
    return rules


def load_rules(config_dir: Path) -> list[Rule]:
    """读 rules.json 与 rules.d/*.json。后者按文件名排序，决定拼接顺序。"""
    rules: list[Rule] = []
    main = config_dir / "rules.json"
    if main.is_file():
        rules += _parse_rules(json.loads(main.read_text(encoding="utf-8")), main)
    rules_d = config_dir / "rules.d"
    if rules_d.is_dir():
        for path in sorted(rules_d.glob("*.json")):
            rules += _parse_rules(json.loads(path.read_text(encoding="utf-8")), path)
    return rules


def resolve(ctx: HookContext, config_dir: Path) -> tuple[str, list[Rule]]:
    """返回 (要注入的文本, 命中的规则)。没命中就是空串。"""
    hits = [rule for rule in load_rules(config_dir) if rule.matches(ctx)]
    if not hits:
        return "", []
    return JOIN.join(rule.render(config_dir) for rule in hits), hits
