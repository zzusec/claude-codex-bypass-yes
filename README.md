# Claude Code 命令守卫 (danger-guard)

给 Claude Code 加一道**安全网**:每条命令执行前自动判定危险程度——
**安全命令自动放行,危险命令响铃并弹确认,毁灭级命令直接拦下。**

> 也支持 **Codex CLI**(≥0.142):同一套判定引擎,见下方 [Codex CLI 支持](#codex-cli-支持)。

基于 Claude Code 官方的 [PreToolUse Hook](https://code.claude.com/docs/en/hooks),
比"截屏监控窗口 + 模拟回车"可靠得多:能拿到命令原文精确判定、全局对所有会话生效、
无需辅助功能权限。仅 macOS(用 `afplay` 播放提示音)。

> **前提:开启 auto 模式**(状态栏显示 `⏵⏵ auto mode on`)。

## 效果

| 命令类型 | 示例 | 守卫动作 |
|---|---|---|
| **安全** | `ls`、`git status`、`npm run build`、`sudo apt install`、`kill -9 …`、`psql -c "DELETE …"` | 自动放行(`allow`),无声、不弹框 |
| **危险** | `rm -rf …`、`git push --force`、`git reset --hard`、`curl … \| bash`、`shutdown` | 响铃 + 弹确认 |
| **毁灭级** | `rm -rf /`、`mkfs`、`dd of=/dev/disk`、`> /dev/disk`、fork bomb | 响铃 + 直接拒绝 |

> **默认:非危险命令自动放行(`allow`),连确认框都不弹。** 危险命令响铃+确认,毁灭级直接拒绝。
> 为避免 `allow` 架空你 `settings.json` 里的 `deny` 黑名单,命中 deny 名单的命令会"交回"静态规则按原语义处理,不会被自动放行。

### 只拦「真危险」,不拦「数据」

守卫只针对**真正系统级、难撤销、对外发布**的操作。`sudo`、`kill -9`、`killall`、`pkill`、`rmdir`、
`unlink`、`git branch -D`、`chmod 777 ./x` 等日常命令**不再拦截**。

更关键:匹配只看**命令本身**,不看引号里的数据。以下都属于安全放行 ——

```bash
git commit -m "remove unlink and reboot logic"   # commit 信息里的危险词
psql -c "DELETE FROM logs"                        # SQL 语句
echo "rm -rf / is dangerous" > notes.txt          # echo/写文件的文本内容
```

而 `bash -c "..."` / `eval "..."` 里的内容会被 shell 真正执行,**仍会补扫**,危险照样拦得住。

### 跑测试

```bash
bash test.sh   # 30 个用例覆盖「误报放行 / 真危险 ask / 毁灭级 deny」
```

## 前提条件

需要开启 **auto 模式**(状态栏显示 `⏵⏵ auto mode on`,按 **Shift+Tab** 切换)。auto 模式会自动放行命令,本工具给其中的危险命令补上响铃 + 确认。

## 安装

```bash
git clone https://github.com/zzusec/claude-bypass-yes.git
cd claude-bypass-yes
bash install.sh
```

`install.sh` 会:
1. 把 `danger-guard.py` 复制到 `~/.claude/hooks/`;
2. 往 `~/.claude/settings.json` **安全合并** `PreToolUse` hook 配置(先备份、保留你已有内容、不动任何密钥)。

装完**重启 Claude Code**(或在会话里输入 `/hooks` 确认加载)即可生效。以后新开的窗口自动带上。

### 手动安装

```bash
mkdir -p ~/.claude/hooks
cp danger-guard.py ~/.claude/hooks/
```

然后在 `~/.claude/settings.json` 顶层加入(参考 `settings.example.json`,把路径换成你的真实绝对路径):

```json
"hooks": {
  "PreToolUse": [
    {
      "matcher": "Bash",
      "hooks": [
        { "type": "command", "command": "/usr/bin/python3 /Users/你的用户名/.claude/hooks/danger-guard.py" }
      ]
    }
  ]
}
```

## 更新

装过之后,更新只需拉取最新代码再跑一次安装脚本(可安全重复执行:会覆盖脚本、去重合并配置):

```bash
cd claude-bypass-yes
git pull
bash install.sh
```

脚本逻辑改动**即时生效**(hook 每次执行都会重新读取脚本文件),无需重启 Claude Code。

## 验证

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/x"}}' \
  | /usr/bin/python3 ~/.claude/hooks/danger-guard.py
```

应打印一段 `permissionDecision: "ask"` 的 JSON 并响一声。安全命令(如 `ls -la`)则**无任何输出**。

## 自定义

编辑 `~/.claude/hooks/danger-guard.py` 顶部即可:

- `SOUND_FILE` — 提示音,可换成 `/System/Library/Sounds/` 下的 `Sosumi` / `Funk` / `Glass` / `Hero` 等。
- `WARN_PATTERNS` — 命中 → 响铃 + 弹确认(`ask`)。
- `BLOCK_PATTERNS` — 命中 → 响铃 + 直接拒绝(`deny`)。

> 实测在 `auto` 模式 + `skipAutoPermissionPrompt: true` 下,`ask` 确认框正常弹出。
> 万一你的环境出现"响了铃却没弹确认",把危险档的 `"ask"` 改成 `"deny"` 即可——一样响铃,且一定拦得住。

## 永久放行(白名单)

有些命令你确定安全、不想每次被拦,可加进白名单:**命中即直接放行,不响铃、不确认**。
白名单是 `~/.claude/hooks/allowlist.txt`,每行一个正则,`#` 开头为注释,**改完即时生效**(无需重启)。

```bash
# 例:以后 git restore 直接放行
echo '^\s*git\s+restore\b' >> ~/.claude/hooks/allowlist.txt
```

或直接编辑该文件。几个示例:

```
\bgit\s+reset\s+--hard\b           # git reset --hard
\bgit\s+clean\b[^\n]*\s-\w*f       # git clean -f
\bdocker\b[^\n]*\bprune\b          # docker ... prune
\bgit\s+push\b[^\n]*--force\b      # git push --force
```

> 白名单优先级高于危险确认,但**毁灭级命令(`rm -rf /`、`mkfs`、`dd` 写盘)仍会兜底拦截**,白名单放不了,防手滑。

## 工作原理

Claude Code 执行 Bash 工具前触发 `PreToolUse` hook,把命令以 JSON 送到脚本 stdin。
脚本读取 `.tool_input.command`,按本地正则匹配后用 stdout 返回决策:

- `permissionDecision: "allow"` → 自动放行,跳过确认框
- `permissionDecision: "deny"` → 拦截
- `permissionDecision: "ask"`  → 强制弹确认
- 无输出 + `exit 0` → 不干预(交回 deny 名单等),走正常权限流程

匹配是**纯本地正则**:零延迟、离线、不调用 AI。任何解析异常都"安全失败"(放行),
绝不会因脚本问题卡住正常命令。

## Codex CLI 支持

同一套判定引擎已适配 Codex CLI(需 ≥0.142,hooks 已 stable)。因 Codex 的 PreToolUse hook
**不支持 `ask`**,「危险 → 弹确认」由三层组合实现:

| 层 | 职责 |
|---|---|
| **PreToolUse hook** | 毁灭级 → 响铃 + deny;安全/白名单 → allow(不弹框);危险 → 响铃后不干预,交给下层 |
| **rules(prompt 档)** | 危险命令前缀(`rm -rf`、`git reset --hard`、`shutdown` 等)→ 弹原生确认框 |
| **PermissionRequest hook** | 安全命令的沙箱提权请求自动点「允许」(bypass yes);危险沉默留给用户;毁灭级拒绝 |

### 安装

```bash
bash install-codex.sh
```

会复制 `danger-guard-codex.py` 到 `~/.codex/hooks/`、合并 `~/.codex/hooks.json`(先备份)、
安装 `~/.codex/rules/danger-guard.rules`,并检测其他 `.rules` 文件里会压过 prompt 的
`forbidden` 冲突条目。

> **必做一步:信任 hooks。** Codex 要求用户级 hooks 经过审查信任才会运行——
> 在 Codex TUI 里输入 `/hooks` 信任守卫(一次即可;`hooks.json` 内容变更后需重新信任)。
> 无人值守自动化可给 `codex exec` 加 `--dangerously-bypass-hook-trust`。

### 实测要点(codex-cli 0.142.5)

- **rules 优先级高于 hook 的 allow**,多规则命中取最严格(`forbidden` > `prompt` > `allow`)。
  所以危险档规则只写具体形态(如 `["rm","-rf"]`),不能写整类 `["rm"]`,否则普通
  `rm foo.txt` 也会弹确认、在 exec 模式被拒。
- `codex exec`(审批=Never)下 `prompt` 档 = **直接拒绝**,模型会拿到拒绝原因并如实汇报——
  对无人值守 worker 这正是想要的安全行为。
- 白名单**与 Claude 版共享**:`~/.codex/hooks/allowlist.txt` 和 `~/.claude/hooks/allowlist.txt`
  都会读取,放行一次两边生效。但注意白名单只影响 hook,压不过 rules 的 `prompt/forbidden`。

### 测试

```bash
bash test-codex.sh   # 29 个用例:误报放行 / 危险沉默交后手 / 毁灭级 deny / 提权自动允许
```

### 卸载(Codex)

删除 `~/.codex/hooks.json` 里指向 danger-guard-codex.py 的条目和
`~/.codex/rules/danger-guard.rules` 即可。

## 卸载

删除 `~/.claude/settings.json` 里新增的 `hooks` 字段即可(其余配置不受影响)。

## 许可

MIT
