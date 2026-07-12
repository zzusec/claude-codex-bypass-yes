# Claude Code / Codex 命令守卫

**主要作用：除危险命令外一律自动允许，减少反复点 Yes。**

给 Claude Code / Codex 加一层本地判断（仅 macOS）：

- 日常命令（`ls`、`git status`、`npm run`、装包、查日志…）→ **直接放行，不弹确认**
- 危险命令（`rm -rf …`、`git reset --hard`、`git push --force`…）→ **响铃 + 让你确认**
- 毁灭级（`rm -rf /`、`mkfs`、`dd` 写盘…）→ **响铃 + 直接拒绝**

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

需要 Codex CLI ≥ 0.142。

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
echo '^\s*git\s+restore' >> ~/.claude/hooks/allowlist.txt
```

毁灭级（`rm -rf /`、`mkfs`、`dd` 写盘）不能白名单放行。

提示音默认是系统音量的一半（`SOUND_VOLUME=0.5`）；要再调，改 hooks 脚本里的 `SOUND_VOLUME`（0~1，相对系统音量）。

---

## 卸载

- Claude：删掉 `~/.claude/settings.json` 里指向 `danger-guard.py` 的 hooks
- Codex：删掉 `~/.codex/hooks.json` 相关条目，以及 `~/.codex/rules/danger-guard.rules`

## 许可

MIT
