# Claude Code / Codex 命令守卫

给 Claude Code 和 Codex CLI 加一层命令安全网（仅 macOS）：

| 类型 | 例子 | 行为 |
|---|---|---|
| 安全 | `ls`、`git status`、`npm run build` | 自动放行，不弹窗 |
| 危险 | `rm -rf …`、`git reset --hard`、`git push --force` | 响铃 + 弹确认 |
| 毁灭级 | `rm -rf /`、`mkfs`、`dd` 写盘 | 响铃 + 直接拒绝 |

装好后照常用 AI 即可，不用学新命令。

---

## Claude Code

### 安装

```bash
git clone https://github.com/zzusec/claude-codex-bypass-yes.git
cd claude-codex-bypass-yes
bash install.sh --bypass
```

- `install.sh`：只装钩子  
- `install.sh --bypass`：装钩子 + 设 `bypassPermissions`（推荐，少弹无用确认）  
- 装完**重启 Claude Code**

### 验证

```bash
# 危险命令：应响铃，并输出 permissionDecision: "ask"
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/x"}}' \
  | /usr/bin/python3 ~/.claude/hooks/danger-guard.py

# 全量测试
bash test.sh
```

或在 Claude 里让它跑 `ls`（应无弹窗），再跑 `git reset --hard HEAD`（应响铃并确认）。

### 升级

```bash
cd claude-codex-bypass-yes
git pull
bash install.sh --bypass
```

然后重启 Claude Code。

---

## Codex CLI

需要 Codex CLI ≥ 0.142。

### 安装

```bash
git clone https://github.com/zzusec/claude-codex-bypass-yes.git
cd claude-codex-bypass-yes
bash install-codex.sh
```

装完后在 Codex 里输入 `/hooks`，把 **PreToolUse** 和 **PermissionRequest** 两条 danger-guard **Trust** 一次。

### 验证

```bash
# 毁灭级：应响铃，并输出 permissionDecision: "deny"
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' \
  | /usr/bin/python3 ~/.codex/hooks/danger-guard-codex.py PreToolUse

# 全量测试
bash test-codex.sh
```

### 升级

```bash
cd claude-codex-bypass-yes
git pull
bash install-codex.sh
```

若 `hooks.json` 有变化，再在 Codex 里 `/hooks` 重新 Trust 一次。

---

## 可选：永久放行某类危险命令

不想每次确认时，往白名单加一行正则（改完即时生效）：

```bash
echo '^\s*git\s+restore\b' >> ~/.claude/hooks/allowlist.txt
```

毁灭级命令（`rm -rf /`、`mkfs`、`dd` 写盘）**不能**被白名单放行。

---

## 卸载

- **Claude Code**：删掉 `~/.claude/settings.json` 里指向 `danger-guard.py` 的 hooks 配置  
- **Codex**：删掉 `~/.codex/hooks.json` 里相关条目，以及 `~/.codex/rules/danger-guard.rules`

## 许可

MIT
