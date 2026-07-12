# Claude Code / Codex 命令守卫 (danger-guard)

给 Claude Code 和 Codex CLI 加一道**安全网**:每条命令执行前自动判定危险程度——
**安全命令自动放行(不弹任何确认),危险命令响铃并弹确认,毁灭级命令直接拦下。**
纯本地正则判定:零延迟、离线、不调用 AI。仅 macOS(用 `afplay` 播放提示音)。

| 命令类型 | 示例 | 守卫动作 |
|---|---|---|
| **安全** | `ls`、`git status`、`npm run build`、`sudo apt install`、`kill -9 …`、`psql -c "DELETE …"` | 自动放行,无声、不弹框 |
| **危险** | `rm -rf …`、`git push --force`、`git reset --hard`、`curl … \| bash`、`shutdown` | 响铃 + 弹确认 |
| **毁灭级** | `rm -rf /`、`mkfs`、`dd of=/dev/disk`、`> /dev/disk`、fork bomb | 响铃 + 直接拒绝 |

匹配只看**命令本身**,不看引号里的数据:`git commit -m "remove reboot logic"`、
`psql -c "DELETE FROM logs"`、`echo "rm -rf /" > notes.txt` 都会正常放行;
而 `bash -c "..."` / `eval "..."` 里的内容会被 shell 真正执行,**仍会补扫**,危险照样拦得住。

装好后**不需要学任何新命令**,照常让 AI 干活即可。

- 用 **Claude Code** → 看 [第一部分](#第一部分claude-code)
- 用 **Codex CLI** → 看 [第二部分](#第二部分codex-cli)
- 两个都用 → 两部分都装,白名单等配置自动共享(见[通用配置](#通用配置))

---

## 第一部分:Claude Code

### 1. 安装

```bash
git clone https://github.com/zzusec/claude-codex-bypass-yes.git
cd claude-codex-bypass-yes
bash install.sh
```

`install.sh` 会:
1. 把 `danger-guard.py` 复制到 `~/.claude/hooks/`;
2. 往 `~/.claude/settings.json` **安全合并** `PreToolUse` hook 配置(先备份、保留你已有内容、不动任何密钥);
3. 询问是否把默认权限模式设为 `bypassPermissions`(消除 `.` source/eval 类内建弹窗,见下方说明;默认否)。

> 想在新机器一步到位、不逐个确认,直接:`bash install.sh --bypass`——装钩子、设好 `bypassPermissions`(含处理 `settings.local.json` 的优先级)、并写入**推荐 slim deny**(只硬拦毁灭级删除/磁盘;自动剔除 `Bash(sudo *)` 这类过宽规则)。加 `--no-bypass` 则明确只装钩子。
> 注意:`bypassPermissions` 只能写到你**本机**的 `~/.claude/settings.json`(用户级)才生效;提交进 git 仓库的项目级 `.claude/settings.json` 若设这个模式会被 Claude Code **故意忽略**(防恶意仓库 clone 即提权),所以“clone 即自动 bypass”做不到,得靠这个安装脚本。

<details>
<summary>不想跑脚本?点开看手动安装</summary>

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
</details>

### 2. 启用

1. **重启 Claude Code**(或在会话里输入 `/hooks` 确认已加载);
2. 按 **Shift+Tab** 切到 auto 模式(状态栏显示 `⏵⏵ auto mode on`)。

auto 模式下安全命令全自动执行,守卫负责给危险命令补上响铃+确认。以后新开的窗口自动带上,无需重复设置。

### 3. 验证

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/x"}}' \
  | /usr/bin/python3 ~/.claude/hooks/danger-guard.py
```

- 应打印一段 `permissionDecision: "ask"` 的 JSON 并**响一声铃**;
- 换成安全命令(如 `ls -la`)则**无任何输出**;
- 想跑全量回归:`bash test.sh`(30 个用例)。

### 日常体验

- **安全命令**(绝大多数):无声直接执行,你不会有任何感知;
- **危险命令**:响一声铃 + 弹确认框,看清命令内容再选允许或拒绝;
- **毁灭级命令**:响铃并直接拒绝,Claude 会收到拒绝原因自己换做法,无需你操作。

> 实测在 auto 模式 + `skipAutoPermissionPrompt: true` 下,`ask` 确认框正常弹出。
> 万一你的环境"响了铃却没弹确认",把 `danger-guard.py` 里危险档的 `"ask"` 改成 `"deny"` 即可——一样响铃,且一定拦得住。

### 钩子管不到的弹窗(`.` / `source` / `eval`)

弹窗原因若类似下面这句:

```text
'.' evaluates arguments as shell code
```

**不是** danger-guard 拦的,也**不是**白名单能放行的。

| 是什么 | 不是什么 |
|---|---|
| Claude Code **内建**静态安全检查 | 不是 hook / allowlist 能压掉的 |
| 触发命令:`.` / `source` / `eval` / `bash -c` 等 | 加 `Bash(*)` 白名单也没用 |

**怎么消掉:** 只能把权限模式改成 `bypassPermissions`。

#### 方法一:一条命令(推荐)

```bash
cd claude-codex-bypass-yes
bash install.sh --bypass
```

装钩子的同时,会把本机 `~/.claude/settings.json` 设为 `bypassPermissions`,并写上推荐的 slim deny。若本机已有 `settings.local.json`,也会一并同步。

#### 方法二:手工改配置

编辑 **`~/.claude/settings.json`**(用户级,本机配置,不要提交进 git 仓库):

```json
{
  "permissions": {
    "defaultMode": "bypassPermissions",
    "deny": [
      "Bash(rm -rf /*)",
      "Bash(rm -rf ~*)",
      "Bash(rm -rf /Users/*)",
      "Bash(mkfs *)",
      "Bash(dd if=* of=/dev/*)"
    ]
  },
  "skipDangerousModePermissionPrompt": true
}
```

改完后**新开会话 / 重启 Claude Code** 才生效。

#### 改完还在弹?先看这两个文件

| 文件 | 作用 |
|---|---|
| `~/.claude/settings.json` | **主开关**。日常改这个 |
| `~/.claude/settings.local.json` | 本机覆盖项。若存在且写了别的 `defaultMode`,可能把上面盖掉 |

常见踩坑:

1. 只改了 `settings.local.json` 成 `bypassPermissions`,但 `settings.json` 仍是 `"auto"` → **还是会弹**。两个文件都要是 `bypassPermissions`,或至少保证生效的那份是 bypass。
2. 改完没重启 / 没新开会话 → 旧模式还在用。
3. 把 `bypassPermissions` 写进**项目仓库**的 `.claude/settings.json` → Claude Code 会**故意忽略**(防恶意仓库 clone 即提权)。只能写用户级本机配置。

bypass 之后:`.` / `source` / `eval` 不再弹内建框;真正危险的命令仍由 **danger-guard 响铃确认** + 上面那几条 **毁灭级 deny** 兜底,安全网不丢。

---

## 第二部分:Codex CLI

需要 Codex CLI ≥ 0.142(hooks 已 stable)。因 Codex 的 PreToolUse hook **不支持 `ask`**,
「危险 → 弹确认」由三层组合实现(装完自动生效,不用理解也能用):

| 层 | 职责 |
|---|---|
| **PreToolUse hook** | 毁灭级 → 响铃 + 拒绝;安全/白名单 → 放行不弹框;危险 → 响铃后交给下层 |
| **rules(prompt 档)** | 危险命令前缀(`rm -rf`、`git reset --hard`、`shutdown` 等)→ 弹原生确认框 |
| **PermissionRequest hook** | 安全命令的沙箱提权请求自动点「允许」(bypass yes);危险留给用户;毁灭级拒绝 |

### 1. 安装

```bash
git clone https://github.com/zzusec/claude-codex-bypass-yes.git
cd claude-codex-bypass-yes
bash install-codex.sh
```

`install-codex.sh` 会:
1. 把 `danger-guard-codex.py` 和铃声复制到 `~/.codex/hooks/`;
2. 合并 `~/.codex/hooks.json`(先备份),注册 PreToolUse + PermissionRequest 两条 hook;
3. 安装危险确认规则 `~/.codex/rules/danger-guard.rules`;
4. 检测其他 `.rules` 文件里会压过弹确认的 `forbidden` 冲突条目并提示处理。

### 2. 启用(必做:信任 hooks)

Codex 强制要求用户级 hooks 经过**人工信任**才会运行(否则静默跳过):

1. 打开 Codex,输入 `/hooks`;
2. 会看到提示 `2 hooks need review`——进入 **PreToolUse** 行,选中 danger-guard 条目,选择 **Trust**;
3. 返回后对 **PermissionRequest** 行重复同样操作;
4. 列表两行变成 `Active 1、Review 0` 即生效。

只需做一次;以后 `hooks.json` 内容有变(如重跑安装脚本)才需重新信任,只改脚本内容/白名单不用。

> 无人值守自动化(脚本里跑 `codex exec`)不方便做信任时,可给命令加
> `--dangerously-bypass-hook-trust` 参数。

### 3. 验证

```bash
# 验证 hook:应打印 permissionDecision: "deny" 的 JSON 并响一声铃
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' \
  | /usr/bin/python3 ~/.codex/hooks/danger-guard-codex.py PreToolUse

# 验证 rules:应输出 decision: "prompt"
codex execpolicy check --rules ~/.codex/rules/danger-guard.rules --pretty -- git reset --hard HEAD~1
```

想跑全量回归:`bash test-codex.sh`(29 个用例)。
最直观的实测:让 Codex 跑 `ls`(应无任何弹框),再让它跑 `git reset --hard HEAD`(应弹确认框)。

### 日常体验

- **交互模式(`codex`)**:与 Claude 版一致——安全无感、危险响铃+弹确认、毁灭级直接拒绝;
- **非交互(`codex exec`,脚本/worker 自动化)**:没人能点确认框,**危险命令一律自动拒绝**,模型会拿到拒绝原因并如实汇报——对无人值守场景这正是想要的安全行为。

### 实测要点(codex-cli 0.142.5,自定义规则前必读)

- **rules 优先级高于 hook 的 allow**,多规则命中取最严格(`forbidden` > `prompt` > `allow`)。
  所以危险档规则只写具体形态(如 `["rm","-rf"]`),不能写整类 `["rm"]`,否则普通
  `rm foo.txt` 也会弹确认、在 exec 模式被拒;
- 白名单只影响 hook 层,**压不过** rules 的 `prompt/forbidden`——想让某条危险命令连确认都不弹,
  需编辑 `~/.codex/rules/danger-guard.rules` 删掉对应行。

---

## 通用配置

### 推荐权限:项目内最大权限,只拦毁灭级删除

目标体验:**日常构建/测试/sudo/运维自动放行**;`rm -rf` 非根/家目录等危险命令由守卫**响铃确认**;删根目录/家目录、格式化磁盘**直接拒绝**。

`bash install.sh --bypass` 会自动写入这套配置。也可手动把下面放进 **`~/.claude/settings.json`**。

> **先改哪个文件?** 主开关是 `~/.claude/settings.json`。若本机还有 `~/.claude/settings.local.json`,它的 `defaultMode` / `deny` 可能覆盖用户级配置——两个文件都检查一下,别只改一边(只改 local 而 user 仍是 `auto`,内建 `.` / `source` 弹窗还会继续出)。项目仓库里的 `.claude/settings.json` 写 `bypassPermissions` 无效,Claude Code 会忽略。

```json
{
  "permissions": {
    "defaultMode": "bypassPermissions",
    "deny": [
      "Bash(rm -rf /*)",
      "Bash(rm -rf ~*)",
      "Bash(rm -rf /Users/*)",
      "Bash(mkfs *)",
      "Bash(dd if=* of=/dev/*)"
    ]
  },
  "skipDangerousModePermissionPrompt": true
}
```

| 层 | 拦什么 | 不拦什么 |
|---|---|---|
| **settings `deny`** | 仅毁灭级:删 `/`/`~`/`/Users/*`、`mkfs`、`dd` 写盘 | `sudo`、普通 `rm`、项目内清理 |
| **danger-guard hook** | 危险 → 响铃确认;毁灭级 → 拒绝 | `ls`/`git status`/`npm run`/`sudo apt` 等 |

**切勿**在 `deny` 里写过宽规则,否则“最大权限”会失效:

| 错误示例 | 后果 |
|---|---|
| `Bash(sudo *)` | 所有 sudo 全拦,装包/服务重启全挂 |
| `Bash(git push -f *)` 等写进 **deny** | 变成硬拒绝,无法“确认后执行”;这类应留给守卫 `ask` 或白名单 |
| `Bash(*)` | 等于禁用 Bash |

分工原则:**硬 `deny` 只留给不可逆毁灭**;可商量的危险(force push、`git reset --hard`、`rm -rf /tmp/x`)交给守卫确认或白名单放行。完整示例见仓库 `settings.example.json`。

### 永久放行(白名单)

有些命令你确定安全、不想每次被拦:往白名单加一行正则,**命中即直接放行,不响铃、不确认,改完即时生效**。Claude 和 Codex **共享**两个白名单文件(`~/.claude/hooks/allowlist.txt` 和 `~/.codex/hooks/allowlist.txt`,都会读取):

```bash
# 例:以后 git restore 直接放行
echo '^\s*git\s+restore\b' >> ~/.claude/hooks/allowlist.txt
```

几个示例(每行一个正则,`#` 开头为注释):

```
\bgit\s+reset\s+--hard\b           # git reset --hard
\bgit\s+clean\b[^\n]*\s-\w*f       # git clean -f
\bdocker\b[^\n]*\bprune\b          # docker ... prune
\bgit\s+push\b[^\n]*--force\b      # git push --force
```

> 白名单优先级高于危险确认,但**毁灭级命令(`rm -rf /`、`mkfs`、`dd` 写盘)仍会兜底拦截**,白名单放不了,防手滑。Codex 侧另见上方「实测要点」。

### 自定义判定规则

编辑 `~/.claude/hooks/danger-guard.py` / `~/.codex/hooks/danger-guard-codex.py` 顶部:

- `SOUND_FILE` — 提示音(默认 `chime.wav`=经典 **QQ 消息滴滴声**);可换成任意 wav/aiff,或 `/System/Library/Sounds/` 下的 `Sosumi` / `Funk` / `Glass` / `Hero` 等;
- `WARN_PATTERNS` — 命中 → 响铃 + 弹确认;
- `BLOCK_PATTERNS` — 命中 → 响铃 + 直接拒绝。

脚本内容改动**即时生效**(每次执行都重新读取),无需重启。

### 更新

```bash
cd claude-codex-bypass-yes
git pull
bash install.sh          # Claude Code 版
bash install-codex.sh    # Codex 版
```

安装脚本可安全重复执行(覆盖脚本、去重合并配置)。注意 Codex 重装后 hooks.json 有变,需重新 `/hooks` 信任。

### 卸载

- **Claude Code**:删除 `~/.claude/settings.json` 里新增的 `hooks` 字段;
- **Codex**:删除 `~/.codex/hooks.json` 里指向 danger-guard-codex.py 的条目和 `~/.codex/rules/danger-guard.rules`。

### 工作原理

两边机制相同:执行 Bash 命令前触发 `PreToolUse` hook,命令以 JSON 送到脚本 stdin,
脚本按本地正则匹配后用 stdout 返回决策(`allow` 放行 / `deny` 拦截 / Claude 版另有 `ask` 弹确认;
无输出 = 不干预,走正常权限流程)。任何解析异常都"安全失败"(不干预),绝不因脚本 bug 卡住正常命令。
Codex 版因 hook 无 `ask`,弹确认由 rules `prompt` 档和 PermissionRequest hook 配合完成(见第二部分表格)。

## 许可

MIT
