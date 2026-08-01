#!/usr/bin/env bash
# Claude Code 命令守卫 — 安装脚本 (macOS)
# 1) 复制守卫脚本到 ~/.claude/hooks/,并安全合并 PreToolUse hook 到 settings.json；
# 2) 可选把默认权限模式设为 bypassPermissions,消除 . source/eval 类命令的内建弹窗。
#
# 3) 顺带把「上下文到 80% 自动 compact」配上(可用 --no-autocompact 跳过)。
#
# 用法:
#   bash install.sh              # 装钩子;交互时询问是否设 bypass(默认否)
#   bash install.sh --bypass     # 装钩子并直接设 bypass,不询问(新机一步到位)
#   bash install.sh --no-bypass  # 装钩子,明确跳过权限模式设置
#   bash install.sh --autocompact-pct 75   # 自动压缩阈值改 75%(默认 80)
#   bash install.sh --no-autocompact       # 不动自动压缩配置
set -euo pipefail

CLAUDE_DIR="${HOME}/.claude"
HOOKS_DIR="${CLAUDE_DIR}/hooks"
SETTINGS="${CLAUDE_DIR}/settings.json"
LOCAL_SETTINGS="${CLAUDE_DIR}/settings.local.json"
SCRIPT_SRC="$(cd "$(dirname "$0")" && pwd)/danger-guard.py"
SCRIPT_DST="${HOOKS_DIR}/danger-guard.py"

# 解析参数:BYPASS_MODE = ""(未定/交互问) | "yes" | "no"
BYPASS_MODE=""
AUTOCOMPACT=1
AUTOCOMPACT_PCT=80
prev=""
for arg in "$@"; do
  case "$arg" in
    --bypass|-y) BYPASS_MODE="yes" ;;
    --no-bypass) BYPASS_MODE="no" ;;
    --no-autocompact) AUTOCOMPACT=0 ;;
    --autocompact-pct=*) AUTOCOMPACT_PCT="${arg#*=}" ;;
    *) [ "$prev" = "--autocompact-pct" ] && AUTOCOMPACT_PCT="$arg" ;;
  esac
  prev="$arg"
done

echo "[1/5] 复制脚本与铃声 -> ${HOOKS_DIR}"
mkdir -p "${HOOKS_DIR}"
cp "${SCRIPT_SRC}" "${SCRIPT_DST}"
# 提示音与脚本同目录(danger-guard.py 按自身路径定位 chime.wav)
SOUND_SRC="$(cd "$(dirname "$0")" && pwd)/chime.wav"
if [ -f "${SOUND_SRC}" ]; then
  cp "${SOUND_SRC}" "${HOOKS_DIR}/chime.wav"
  echo "      已复制 chime.wav(经典 QQ 消息滴滴声)"
else
  echo "      警告: 仓库内缺少 chime.wav,危险命令将静音"
fi

echo "[2/5] 合并 PreToolUse hook -> ${SETTINGS}"
/usr/bin/python3 - "$SETTINGS" "$SCRIPT_DST" <<'PY'
import json, os, sys

settings_path, script_dst = sys.argv[1], sys.argv[2]

if os.path.exists(settings_path):
    with open(settings_path, encoding="utf-8") as f:
        data = json.load(f)
    bak = settings_path + ".bak.cmdguard"
    with open(bak, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("      已备份原配置 ->", bak)
else:
    data = {}

entry = {
    "matcher": "Bash",
    "hooks": [
        {"type": "command", "command": f"/usr/bin/python3 {script_dst}"}
    ],
}

hooks = data.setdefault("hooks", {})
pre = hooks.setdefault("PreToolUse", [])

# 去重:移除任何已指向 danger-guard.py 的旧条目,避免重复安装
def points_to_guard(e):
    return any("danger-guard.py" in h.get("command", "") for h in e.get("hooks", []))

pre[:] = [e for e in pre if not points_to_guard(e)]
pre.append(entry)

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("      已写入 PreToolUse hook")
PY

echo "[3/5] 权限模式(可选:消除 . source / eval 类命令的内建弹窗)"
# 说明:Claude Code 自带静态安全检查会对 . / source / eval / bash -c 强制弹确认,
# 且覆盖本钩子的 allow 与 Bash(*) 白名单,钩子层压不下去。只有 bypassPermissions
# 模式能免——bypass 下除 rm 危险操作外内建检查全自动放行,而本钩子 deny 档 +
# 你的 deny 列表仍兜底拦截真正危险的命令。此项为“放宽权限”,默认需你确认。
if [ -z "$BYPASS_MODE" ]; then
  if [ -t 0 ]; then
    printf '      把默认权限模式设为 bypassPermissions?(除危险命令外全自动,不再弹确认)\n'
    printf '      设置? [y/N] '
    read -r ans || ans=""
    case "$ans" in [yY]*) BYPASS_MODE="yes" ;; *) BYPASS_MODE="no" ;; esac
  else
    BYPASS_MODE="no"
    echo "      非交互环境,已跳过;需要时重跑并加 --bypass。"
  fi
fi

if [ "$BYPASS_MODE" = "yes" ]; then
  /usr/bin/python3 - "$SETTINGS" "$LOCAL_SETTINGS" <<'PY'
import json, os, sys
user_path, local_path = sys.argv[1], sys.argv[2]

# 推荐:项目内最大权限,只硬拦毁灭级删除/磁盘。
# 其余危险(rm -rf 非根/家、git reset --hard、curl|bash 等)交给 danger-guard 响铃确认。
# 切勿写 Bash(sudo *) / Bash(git *) 这类过宽 deny,否则日常运维会被误拦。
#
# ⚠ deny 的 * 会跨 / 匹配:"Bash(rm -rf /*)" 不是"只拦根目录",而是拦下所有绝对路径的
# rm -rf(连 /tmp/xxx、项目内 node_modules 都拦),且 deny 优先级最高、bypassPermissions
# 也压不住 -> 表现为 "Permission to use Bash ... has been denied"。
# 所以这里只写精确的毁灭级形态,路径分级判断交给 danger-guard.py(见 test.sh)。
RECOMMENDED_DENY = [
    "Bash(rm -rf /)",
    "Bash(rm -fr /)",
    "Bash(rm -rf /Users)",
    "Bash(rm -rf ~)",
    "Bash(mkfs *)",
    "Bash(dd if=* of=/dev/*)",
]
# 已知会误拦大量正常命令的过宽规则,装 bypass 时自动剔除。
# 这些场景 danger-guard 已按目标分级处理(临时/项目内子目录放行,项目级响铃确认,
# 根/家/整盘直接拒绝),留在 deny 里只会把 mktemp 清理、常规回滚这类操作一起硬拒,
# 且 deny 优先级高于一切,连 bypassPermissions 都压不住 -> 表现为 "Permission ... denied"。
OVERBROAD_DENY = {
    "Bash(sudo *)",
    "Bash(sudo*)",
    "Bash(*)",
    "Bash(rm -rf *)",
    "Bash(rm -r *)",
    "Bash(rm *)",
    "Bash(rm -rf /*)",      # * 跨 / 匹配 -> 实际拦下所有绝对路径删除
    "Bash(rm -rf ~*)",      # 同上,拦下家目录内一切删除
    "Bash(rm -rf /Users/*)",
    "Bash(git reset --hard *)",
    "Bash(git clean -f *)",
    "Bash(git push --force *)",
}

def load(p):
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None

def slim_deny(perm):
    """合并推荐毁灭级 deny,并去掉已知过宽条目;保留用户其它自定义 deny。"""
    old = list(perm.get("deny") or [])
    kept = [x for x in old if x not in OVERBROAD_DENY]
    removed = [x for x in old if x in OVERBROAD_DENY]
    for x in RECOMMENDED_DENY:
        if x not in kept:
            kept.append(x)
    perm["deny"] = kept
    return removed, kept

# 用户级 ~/.claude/settings.json:设 bypass + 免开机“确认危险模式”框 + 推荐 slim deny
u = load(user_path) or {}
perm_u = u.setdefault("permissions", {})
perm_u["defaultMode"] = "bypassPermissions"
u["skipDangerousModePermissionPrompt"] = True
removed_u, deny_u = slim_deny(perm_u)
with open(user_path, "w", encoding="utf-8") as f:
    json.dump(u, f, ensure_ascii=False, indent=2)
print("      已设置", user_path, "-> defaultMode=bypassPermissions")
print("      推荐 deny:", deny_u)
if removed_u:
    print("      已移除过宽 deny:", removed_u)

# 本地级 settings.local.json:若存在则同步 defaultMode + slim deny
# (其 defaultMode/deny 优先级可高于用户级;不存在则不无中生有创建文件)
# 本地级 settings.local.json:若已存在则同步 defaultMode + slim deny
# (其 defaultMode/deny 优先级可高于用户级;不存在则不无中生有创建文件)
l = load(local_path)
if isinstance(l, dict):
    perm_l = l.setdefault("permissions", {})
    perm_l["defaultMode"] = "bypassPermissions"
    removed_l, deny_l = slim_deny(perm_l)
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(l, f, ensure_ascii=False, indent=2)
    print("      已同步", local_path, "-> defaultMode=bypassPermissions")
    print("      local deny:", deny_l)
    if removed_l:
        print("      已移除 local 过宽 deny:", removed_l)
PY
else
  echo "      已跳过(保持现有权限模式)。"
fi

echo "[4/5] 上下文自动压缩阈值"
if [ "$AUTOCOMPACT" -eq 1 ]; then
  AUTOCOMPACT_EMBED=1 bash "$(cd "$(dirname "$0")" && pwd)/autocompact.sh" \
    --claude-only --pct "$AUTOCOMPACT_PCT" | sed 's/^/      /'
else
  echo "      已跳过(--no-autocompact)。"
fi

echo "[5/5] 完成 ✅"
echo
echo "请重启 Claude Code,或在会话内输入 /hooks 确认加载(权限模式改动也需重启生效)。"
echo "验证钩子:"
echo "  echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"rm -rf /tmp/x\"}}' | /usr/bin/python3 ${SCRIPT_DST}"
