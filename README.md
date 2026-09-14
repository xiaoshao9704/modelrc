# modelrc

按**当前会话模型**向 coding agent 注入提示词的 hook 框架。同一个插件同时支持 Claude Code 与 Codex。

解决的问题：写在 `CLAUDE.md` / `AGENTS.md` 里的规则对所有会话生效，无法「只在某个模型下生效」。本插件在会话启动时读取 agent 传给 hook 的模型名，匹配规则后把对应提示词注入上下文。

**规则和提示词不在本仓库内**，放用户配置目录。本仓库只提供框架。

## 安装

```bash
claude plugin marketplace add https://github.com/xiaoshao9704/modelrc.git
claude plugin install modelrc@modelrc

codex plugin marketplace add https://github.com/xiaoshao9704/modelrc.git
codex plugin add modelrc@modelrc
```

装完还要建配置目录，否则不会注入任何内容（`modelrc doctor` 会提示）。见下方「配置」。

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

### 排查 hook 入参

hook 的 stdin 平时完全不可见。给 agent 进程设 `MODELRC_DEBUG_DUMP=<文件路径>`
（hook 子进程会继承），每次触发都会把真实入参与归一化后的上下文追加到该文件：

```bash
MODELRC_DEBUG_DUMP=/tmp/modelrc.jsonl claude -p "..." 
```

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
- 每个字段的值可以是字符串或字符串数组，数组是**任一命中**，空数组不命中
- 通配用 `fnmatch` 语义，`*` 会跨越 `/`，所以 `*/work/*` 匹配任意深度
- 模型名为空时，带 `model` 约束的规则不命中
- **多条规则命中会全部拼接**（按文件名与数组顺序），用空行分隔
- `prompt_file` 相对配置目录解析

可匹配字段：`model`、`harness`、`config_dir`、`cwd`、`event`。

### resume 起来的会话

实测（claude-code 2.1.258）：`resume` / `fork` 起来的会话**会**触发 `SessionStart`，
但入参里的 `model` 是**空的**。若不处理，带 `model` 约束的规则在 resume 时会静默不命中。

Claude adapter 因此在 `model` 为空时，从 `transcript_path` 末尾回溯取上一次实际使用的
模型名。若 resume 时切换了模型，`PostModelSwitch`（其 source 枚举包含 `resume`）
会带 `to_model` 再触发一次，为新模型追加规则。历史上下文中的旧提示词不会被撤销。

Codex `SessionStart` 在 CLI 0.153.4 与桌面版内置 0.154.0-alpha.6.2 的启动与 resume 入参中
已实测有 `model`。若宿主未提供模型名，模型规则不命中，不读取旧 transcript 猜测当前模型。

回退依赖 `transcript_path`。**在与原会话不同的目录里 resume 时**，Claude Code 会按当前
cwd 推导 project 目录，`transcript_path` 因此指向一个不存在的文件，回退取不到模型名，
带 `model` 约束的规则不会命中（不会报错，也不会注入）。同目录 resume 不受影响。

`config_dir` 指的是 **agent 自己的配置目录**（`CLAUDE_CONFIG_DIR` / `CODEX_HOME`，取不到时用默认值），
用于区分同机多套配置。它来自 hook 进程继承的环境变量，不在 hook 入参里。

## 命令

```bash
modelrc doctor                                   # 自检：配置目录、规则、提示词文件
modelrc resolve --harness claude --model sonnet-example-x # 干跑：打印会注入什么
modelrc manifest --harness claude                # 生成 Claude SessionStart 清单
modelrc manifest --harness codex                 # 生成 Codex SessionStart 清单
modelrc hook                                     # 供 agent 调用，读 stdin JSON
```

hook 任何异常都写 stderr 并以 0 退出，不会打断会话。

## 支持的宿主

| | 挂载事件 | 模型字段 | 配置目录来源 |
|---|---|---|---|
| Claude Code | `SessionStart`、`PostModelSwitch` | `model` / `to_model` | `CLAUDE_CONFIG_DIR` |
| Codex | `SessionStart` | `model` | `CODEX_HOME` |

两个宿主使用独立入口，命令显式传入 `--harness claude` / `--harness codex`：

- Claude 的 `SessionStart` 使用默认 `hooks/hooks.json`，`PostModelSwitch` 由 `.claude-plugin/plugin.json` 追加。
- Codex 的 `.codex-plugin/plugin.json` 显式指向 `./hooks/codex-hooks.json`。不要写 `"hooks": {}`，它会覆盖默认清单，导致没有 hook 被加载。
- 两边入参都可能包含 `permission_mode`、`transcript_path`，不能依靠这些字段区分宿主。手动调用未指定 `--harness` 时仅做环境与特有字段判别，无法区分就跳过。
- Codex 安装或更新后，需要在 hook 管理界面信任当前 hook 定义；`enabled = true` 不等于已经信任。确保 `[features].hooks` 未被关闭。
- Codex 当前只监听 `SessionStart`，不支持会话中途切模型时即时重选规则。注入内容是追加上下文，不会撤回历史规则。

官方协议：[Codex Hooks](https://learn.chatgpt.com/docs/hooks)。

### GPT-6 Astra 复用规则

在用户配置目录中新建一条规则，并提供适配 Codex 工具名与可用子模型的提示词：

```json
[
  {
    "name": "gpt-6-astra-orchestration",
    "match": {"model": ["gpt-6-astra", "gpt-6-astra-*"], "harness": "codex"},
    "prompt_file": "prompts/gpt-6-astra-orchestration.md"
  }
]
```

提示词仍放在用户配置目录中，不随插件分发。

## 新增一个宿主

1. 在 `src/modelrc/adapters/` 下新建一个 `Adapter` 子类，实现 `detect` / `parse` / `emit` / `native_events`
2. 在 `src/modelrc/adapters/__init__.py` 的 `ADAPTERS` 里注册
3. 在 `tests/test_adapters.py` 的 `SAMPLES` / `SAMPLE_ENVS` 里补上真实 payload 与环境样本

契约测试会自动覆盖新 adapter，包括**判别互斥性**（不能误认别家的 payload / 环境组合）。
核心的规则匹配逻辑不认识任何具体 agent，无需改动。

使用 `modelrc manifest --harness <宿主>` 生成独立清单，并在插件 manifest 中显式引用。
`manifest` 默认生成 Claude 的 SessionStart 清单；Claude 独有事件仍在插件 manifest 中声明。

## 开发

```bash
uv run --no-project --with pytest pytest
```

**不要在本仓库里建 venv。** `claude plugin install` / `codex plugin add` 会把整个目录
复制进各自的插件缓存，且**不看 `.gitignore`**——`.venv` 会让每次安装多出约 10MB，
里面还有一份指向源仓库的旧脚本，排查时容易误导。

两边安装时都是**把整个仓库复制**进各自的插件缓存，不是引用源目录，
所以改完代码必须重新安装才生效。

**发布**（改动已 push）：

```bash
claude plugin marketplace update modelrc && claude plugin update modelrc
codex plugin marketplace upgrade modelrc && codex plugin add modelrc@modelrc
```

`claude plugin update` 按版本号判断，所以**发布前要先在
`.claude-plugin/plugin.json` 与 `.codex-plugin/plugin.json` 里同步升版本号**，
否则它会认为已是最新而不重拷。

**本地迭代**（不想每次都 push）：临时把本地目录加成 marketplace，
但要注意它会覆盖同名的 Git 源，验完记得换回去。

```bash
claude plugin marketplace add ~/code/modelrc   # 本地路径源
# 验证完毕后换回 Git 源
claude plugin marketplace remove modelrc
claude plugin marketplace add https://github.com/xiaoshao9704/modelrc.git
```

注意 `codex plugin marketplace upgrade` **只刷新 Git 类型的 marketplace**，
本地路径源不适用，那种情况下只能 remove + add。
