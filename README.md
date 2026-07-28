# Claude Code / Codex 命令守卫

**主要作用：除危险命令外一律自动允许，减少反复点 Yes。**

给 Claude Code / Codex 加一层本地判断（仅 macOS）：

- 日常命令（`ls`、`git status`、`npm run`、装包、查日志…）→ **直接放行，不弹确认**
- 危险命令（`rm -rf …`、`git reset --hard`、`git push --force`…）→ **响铃 + 让你确认**
- 毁灭级（`rm -rf /`、`mkfs`、`dd` 写盘…）→ **响铃 + 直接拒绝**

`rm -rf` 按删除目标分级，**删普通目录不弹确认**：

- **直接放行**：项目内子目录/文件（`node_modules`、`dist`、`build`…）、临时目录（`/tmp/…`、`/private/tmp/…`）、家目录下两层以上的深层路径
- **弹确认**：「整个项目」级——git 仓库根、家目录直接子项（`~/xxx`）、当前所在目录（`.`/`..`/cwd 及其祖先）；系统路径（`/opt/…` 等）；以及变量、通配符、命令替换等看不清目标的写法（保守回落）
- **直接拒绝**：根目录、家目录、整个用户目录（`/Users/xxx`）、一级系统目录（`/etc`、`/usr`、`/tmp` 整删…）

组合命令里其它危险段（如 `rm -rf /tmp/x && git push --force`）照常拦。

目标体验：AI 能自己干活，你不用一直点 Yes；真正危险时才拦一下。

---

## Claude Code

### 安装

```bash
git clone https://github.com/zzusec/claude-codex-bypass-yes.git
cd claude-codex-bypass-yes
bash install.sh --bypass
```

- `install.sh --bypass`：装钩子 + 尽量少弹无用确认（推荐）
- 装完**重启 Claude Code**

### 验证

```bash
# 安全命令：应无输出（静默=放行；勿输出 allow，auto 模式会报 unsupported）
echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' \
  | /usr/bin/python3 ~/.claude/hooks/danger-guard.py

# 危险命令：应响铃，并输出 permissionDecision: "ask"
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/x"}}' \
  | /usr/bin/python3 ~/.claude/hooks/danger-guard.py

bash test.sh
```

### 升级

```bash
cd claude-codex-bypass-yes
git pull
bash install.sh --bypass
```

重启 Claude Code。

---

## Codex CLI

需要 Codex CLI ≥ 0.142（0.142.5 / 0.145.0 实测）。

### 安装

```bash
git clone https://github.com/zzusec/claude-codex-bypass-yes.git
cd claude-codex-bypass-yes
bash install-codex.sh
```

装完在 Codex 输入 `/hooks`，把 **PreToolUse**、**PermissionRequest** 两条 danger-guard **Trust** 一次。

### 验证

```bash
# 安全命令：应无输出（静默=放行）
echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' \
  | /usr/bin/python3 ~/.codex/hooks/danger-guard-codex.py PreToolUse

# 毁灭级：应响铃 + permissionDecision: "deny"
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' \
  | /usr/bin/python3 ~/.codex/hooks/danger-guard-codex.py PreToolUse

bash test-codex.sh
```

上面只验证脚本本身。要确认 **Codex 真的在调用钩子**（未 Trust 时 hooks 会静默不执行，看不出区别），跑一次端到端：

```bash
codex exec --full-auto "执行命令 mkfs.ext4 --help 并原样报告输出"
```

macOS 没有 `mkfs`，放行也无害。输出里出现下面两行即已生效：

```
hook: PreToolUse Blocked
Command blocked by PreToolUse hook: [命令守卫] mkfs 格式化文件系统
```

只出现 `hook: PreToolUse` / `Completed` 而命令照跑，说明还没 Trust（临时可加 `--dangerously-bypass-hook-trust`）。也可以查 `~/.codex/config.toml` 的 `[hooks.state]`，两条都应有 `trusted_hash` + `enabled = true`。

### 本守卫不管 MCP 工具弹窗

`hooks.json` 的 matcher 是 `"Bash"`，只拦 shell 命令。MCP 工具调用（如 `Allow the chrome-devtools MCP server to run tool "navigate_page"?`）走 Codex 自带的审批，守卫看不到，别往钩子上查。免弹窗在 `~/.codex/config.toml` 配：

```toml
[mcp_servers.chrome-devtools]
default_tools_approval_mode = "approve"   # auto | prompt | writes | approve
```

- 单个工具粒度：`[mcp_servers.<name>.tools.<tool>] approval_mode = "approve"`；也可用 `enabled_tools` / `disabled_tools` 收窄暴露面。
- 等效做法：弹窗时按 `3. Always allow`，Codex 会把同样的配置写进 `config.toml`。
- 改完要**重启 Codex TUI**；弹窗只出现在 TUI，`codex exec`（approval=never）本来就不弹，所以这项改动没法用 exec 验证。
- 忘了合法取值就故意填错让它报出来：`codex mcp list -c 'mcp_servers.x.default_tools_approval_mode="bogus"'`。

### 升级

```bash
cd claude-codex-bypass-yes
git pull
bash install-codex.sh
```

`hooks.json` 有变时，再 `/hooks` Trust 一次。

---

## 可选：某类危险命令也不想确认

```bash
echo '^\s*git\s+restore\b' >> ~/.claude/hooks/allowlist.txt
```

毁灭级（`rm -rf /`、`mkfs`、`dd` 写盘）不能白名单放行。

提示音默认是系统音量的一半（`SOUND_VOLUME=0.5`）；要再调，改 hooks 脚本里的 `SOUND_VOLUME`（0~1，相对系统音量）。

---

## 卸载

- Claude：删掉 `~/.claude/settings.json` 里指向 `danger-guard.py` 的 hooks
- Codex：删掉 `~/.codex/hooks.json` 相关条目，以及 `~/.codex/rules/danger-guard.rules`

## 许可

MIT
