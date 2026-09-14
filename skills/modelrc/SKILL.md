---
name: modelrc
description: 配置和排查 modelrc 插件的按模型提示词注入。用户要新增、修改或复制模型规则，检查提示词为何未生效，或了解 modelrc 的安装更新与使用方式时使用。
---

# Modelrc 使用说明

modelrc 根据宿主传入的当前模型、工作目录等条件，选择用户自己的提示词文件并通过 hook 注入上下文。它不负责选择模型、切换 API 提供商或执行提示词里的任务。

## 找到实际入口与配置

本 skill 所在目录的 `../..` 是插件根目录。使用该目录下 `bin/modelrc` 的绝对路径；插件安装不会保证 `modelrc` 出现在 PATH。调用 shell 引导入口，不绕过它直接执行 Python 文件。

区分两种配置目录：

| 目录 | 查找顺序 / 用途 |
|---|---|
| modelrc 规则目录 | 命令行全局参数 `--config-dir` → `MODELRC_CONFIG_DIR` → `$XDG_CONFIG_HOME/modelrc` → `~/.config/modelrc` |
| 宿主配置目录 | Codex 使用 `CODEX_HOME`，默认 `~/.codex`；Claude 使用 `CLAUDE_CONFIG_DIR`，默认 `~/.claude`。这是规则里 `match.config_dir` 匹配的值 |

排查现用环境时，检查实际启动入口及其导出的变量。CLI wrapper 和桌面进程可能使用不同配置，不能只凭当前 shell 推断桌面行为。不要通过迁移宿主目录解决规则问题。

后面的命令中，`MODELRC_BIN`、`MODELRC_RULES_DIR`、`MODELRC_AGENT_CONFIG` 分别设为已核实的可执行入口、规则目录、宿主配置目录的绝对路径。

## 新增、修改或复制规则

先查看现有 `rules.json`、`rules.d/*.json` 及本次涉及的提示词文件。个人规则放在用户配置目录，不放进插件缓存或仓库；框架更新会替换缓存。

- `rules.json` 最先加载，其后按文件名排序加载 `rules.d/*.json`，每个文件内按数组顺序处理。
- 规则文件接受数组，或 `{"rules": [...]}`。多条命中会全部拼接，不会按名称覆盖，也不是第一条命中即停止。
- `match` 支持 `model`、`harness`、`config_dir`、`cwd`、`event`。字段之间为 AND；字符串数组内部为 OR；空数组不命中。
- 缺省字段不限制，`match: {}` 匹配所有上下文。模型名为空时，任何带 `model` 条件的规则均不命中，包括 `"*"`。
- 匹配使用 glob / `fnmatch`，不是正则；`*` 会跨越 `/`，路径模式中的 `~` 会展开。
- `event` 使用归一化值 `session_start` 或 `model_switch`，不是宿主事件名 `SessionStart`。
- `prompt_file` 相对规则目录解析，也支持绝对路径或 `~`；内容按 UTF-8 读取并去掉首尾空白。

例如，仅为 Codex 中的 GPT-6 Astra 及其版本后缀注入一份提示词：

```json
[
  {
    "name": "astra-conventions",
    "match": {
      "harness": "codex",
      "model": ["gpt-6-astra", "gpt-6-astra-*"]
    },
    "prompt_file": "prompts/astra-conventions.md"
  }
]
```

复制已有模型规则时，保留原规则，给新规则独立名称并调整模型匹配；其余目录、宿主限制按用户目标保留或调整。提示词若包含旧模型自称、专属工具名或子模型别名，改成目标宿主实际支持的名称。只有内容完全通用且用户希望联动维护时才共享原提示词文件。示例不代表默认启用 Astra 或子 agent 编排。

## 验证配置与输出

改完先执行自检，再用目标上下文干跑。`--config-dir` 是全局参数，必须放在子命令前：

```bash
"$MODELRC_BIN" --config-dir "$MODELRC_RULES_DIR" doctor
"$MODELRC_BIN" --config-dir "$MODELRC_RULES_DIR" resolve \
  --harness codex --model gpt-6-astra \
  --cwd "$PWD" --harness-config-dir "$MODELRC_AGENT_CONFIG" \
  --event session_start
```

`resolve` 不会从宿主环境自动填充 `--harness-config-dir`；检查带 `config_dir` 限制的规则时要显式传入。再选一个不应命中的模型或目录验证边界；复制规则后也检查原规则仍然命中。

需要检查 stdout 协议时，将捕获的真实 payload 输入 `hook --harness codex` 或 `hook --harness claude`，并使用对应宿主环境。成功注入会输出 `hookSpecificOutput.additionalContext`。空 stdout 可能是未命中，也可能是错误；hook 运行异常通常写 stderr 并返回 0，所以不能用退出码单独证明成功。

`doctor` 与 `resolve` 只能证明本地配置及匹配结果。宣称宿主注入成功，还需要观察真实 hook 执行及模型可见上下文或实际请求。

## 提示词未生效时

沿最短链路定位：

1. 确认实际使用的已安装插件路径、版本与启用状态。源码改了不代表缓存同步更新。
2. Codex 检查 `hooks/list` 或 hook 管理界面的加载、启用和信任状态；`enabled` 不等于 `trusted`。只在用户授权的启用或更新范围内处理当前插件的信任，不批量信任其他 hook。
3. 检查清单和命令：Codex manifest 应指向 `./hooks/codex-hooks.json`，不能用 `"hooks": {}`；命令应带 `--harness codex`。Claude 的 `hooks/hooks.json` 和插件声明中的 `PostModelSwitch` 应带 `--harness claude`。共享的 `permission_mode`、`transcript_path` 无法区分宿主。
4. 按需给目标宿主进程设置 `MODELRC_DEBUG_DUMP` 为诊断文件路径，再触发新建或恢复会话。日志包含 `payload` 与归一化 `ctx`，据此检查真实模型、宿主、目录、事件。仅给一次手动 hook 设置变量不能证明目标宿主调用过它；完成后移除临时诊断设置。
5. 用日志里的上下文重新 `resolve`，检查拼写、glob、文件路径、UTF-8 与 stderr。如果解释器有问题，用 `doctor` 查看实际版本，必要时设置 `MODELRC_PYTHON`。

当前事件边界：

- Codex 监听 `SessionStart`，中途切模型不会立即重选规则；恢复时使用宿主提供的模型，不从旧 transcript 猜测。
- Claude 还监听 `PostModelSwitch`；`SessionStart` 缺模型时从 transcript 尾部回退，跨目录 resume 可能因 transcript 路径不存在而失败。
- 提示词是追加上下文，更新或删除规则不会撤销已有会话中的旧内容。验证新规则时优先用新会话。

## 安装、更新与维护

用户仅要求配置规则时，直接更新用户配置，无需重装插件。只有框架或插件内容改变才需要更新缓存。安装、发布命令及解释器细节按需查看插件根目录的 [README](../../README.md)。

插件目录会被整体复制到缓存，不要在仓库建立 `.venv`。发布前同步插件 manifest 与包版本；本地临时安装不要永久替换原有 Marketplace 来源。仅请求使用说明、规则修改或诊断，不代表要求发布、推送或重装。
