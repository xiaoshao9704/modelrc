# modelrc

按**当前会话模型**向 coding agent 注入提示词的 hook 框架。同一个插件同时支持 Claude Code 与 Codex。

解决的问题：写在 `CLAUDE.md` / `AGENTS.md` 里的规则对所有会话生效，无法「只在某个模型下生效」。本插件在会话启动时读取 agent 传给 hook 的模型名，匹配规则后把对应提示词注入上下文。

**规则和提示词不在本仓库内**，放用户配置目录。本仓库只提供框架。

## 安装

```bash
claude plugin marketplace add ~/code/modelrc
codex  plugin marketplace add ~/code/modelrc
```

运行时只依赖一个 **python3 ≥ 3.9**，无第三方包。

`bin/modelrc` 是一层 POSIX sh 引导脚本，不用 `#!/usr/bin/env python3`——那会拿到 PATH 上
第一个 python3，可能是某个项目 venv 的、可能版本过低，而 hook 子进程继承的 PATH 还可能
被裁剪过。引导层按固定顺序探测并**校验版本**后再 exec，结果在任何机器上都可复现：

```
$MODELRC_PYTHON → python3 → /usr/bin/python3 → /opt/homebrew/bin/python3
→ /usr/local/bin/python3 → python3.14…3.9 → python
```

想固定用某个解释器就设 `MODELRC_PYTHON`。一个都找不到时会写 stderr 并以 0 退出，
不会打断 agent 会话。`modelrc doctor` 会打印当前实际使用的解释器。

## 配置

默认目录 `~/.config/modelrc/`，可用 `MODELRC_CONFIG_DIR` 覆盖。

```
~/.config/modelrc/
  rules.json          # 可选，先于 rules.d 生效
  rules.d/            # 按文件名排序
    10-sonnet-example.json
  prompts/
    sonnet-example-orchestration.md
```

规则文件是一个数组（或 `{"rules": [...]}`）：

```json
[
  {
    "name": "sonnet-example-orchestration",
    "match": {
      "model": "*sonnet-example*",
      "harness": ["claude", "codex"],
      "config_dir": "*/.claude-private",
      "cwd": "*/work/*"
    },
    "prompt_file": "prompts/sonnet-example-orchestration.md"
  }
]
```

- `match` 里所有字段都是**与**关系；缺省的字段不做约束；`match: {}` 匹配一切
- 每个字段的值可以是字符串或字符串数组，数组是**任一命中**
- 通配用 `fnmatch` 语义，`*` 会跨越 `/`，所以 `*/work/*` 匹配任意深度
- 模型名为空时，带 `model` 约束的规则不命中
- **多条规则命中会全部拼接**（按文件名与数组顺序），用空行分隔
- `prompt_file` 相对配置目录解析

可匹配字段：`model`、`harness`、`config_dir`、`cwd`、`event`。

`config_dir` 指的是 **agent 自己的配置目录**（`CLAUDE_CONFIG_DIR` / `CODEX_HOME`，取不到时用默认值），
用于区分同机多套配置。它来自 hook 进程继承的环境变量，不在 hook 入参里。

## 命令

```bash
modelrc doctor                                   # 自检：配置目录、规则、提示词文件
modelrc resolve --harness claude --model sonnet-example-x # 干跑：打印会注入什么
modelrc manifest                                 # 从 adapter 生成共用 hooks.json
modelrc hook                                     # 供 agent 调用，读 stdin JSON
```

hook 任何异常都写 stderr 并以 0 退出，不会打断会话。

## 支持的宿主

| | 挂载事件 | 模型字段 | 配置目录来源 |
|---|---|---|---|
| Claude Code | `SessionStart`、`PostModelSwitch` | `model` / `to_model` | `CLAUDE_CONFIG_DIR` |
| Codex | `SessionStart` | `model` | `CODEX_HOME` |

`PostModelSwitch` 是 Claude 独有的（切模型即时生效），因此不写进共用的 `hooks/hooks.json`，
而是由 `.claude-plugin/plugin.json` 单独声明，避免 Codex 读到不认识的事件名。

## 新增一个宿主

1. 在 `src/modelrc/adapters/` 下新建一个 `Adapter` 子类，实现 `detect` / `parse` / `emit` / `native_events`
2. 在 `src/modelrc/adapters/__init__.py` 的 `ADAPTERS` 里注册
3. 在 `tests/test_adapters.py` 的 `SAMPLES` 里补一份该宿主的样本 payload

契约测试会自动覆盖新 adapter，包括**判别互斥性**（不能误认别家的 payload）。
核心的规则匹配逻辑不认识任何具体 agent，无需改动。

如果新宿主的挂载事件与现有不同，跑 `modelrc manifest > hooks/hooks.json` 重新生成清单。

## 开发

```bash
uv run --no-project --with pytest pytest
```

**不要在本仓库里建 venv。** `claude plugin install` / `codex plugin add` 会把整个目录
复制进各自的插件缓存，且**不看 `.gitignore`**——`.venv` 会让每次安装多出约 10MB，
里面还有一份指向源仓库的旧脚本，排查时容易误导。

本地开发改完代码后，两边都需要重装才生效（都是拷贝，不是引用）：

```bash
claude plugin uninstall modelrc && claude plugin install modelrc@modelrc
codex plugin add modelrc@modelrc
```

`claude plugin update` 按版本号判断，版本没变不会重拷；
`codex plugin marketplace upgrade` 只刷新 Git 类型的 marketplace，本地目录不适用。
