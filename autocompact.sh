#!/usr/bin/env bash
# 上下文自动压缩阈值配置器 (macOS)
#
# 作用：让 Claude Code / Codex 在上下文用到设定百分比(默认 80%)时自动 compact，
# 不用等到快撑爆才压，也不用手动敲 /compact。
#
# 机制(都是官方原生能力，这里只做幂等配置)：
#   Claude Code : settings.json -> env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE = "80"
#                 + autoCompactEnabled = true
#                 实际阈值 = min(窗口 * 80%, 窗口 - 13000)
#   Codex CLI   : config.toml   -> model_auto_compact_token_limit = 窗口 * 80%
#                 (需要知道窗口大小：读 model_context_window，或用 --codex-window 指定)
#
# 用法:
#   bash autocompact.sh                    # Claude + Codex，阈值 80%
#   bash autocompact.sh --pct 75           # 自定义百分比(1-99)
#   bash autocompact.sh --claude-only      # 只配 Claude Code
#   bash autocompact.sh --codex-only       # 只配 Codex
#   bash autocompact.sh --codex-window 272000   # Codex 未写 model_context_window 时手动给窗口
#   bash autocompact.sh --verify           # 只查看当前生效值，不改配置
#   bash autocompact.sh --uninstall        # 撤销(移除本脚本写入的键)
set -euo pipefail

PCT=80
DO_CLAUDE=1
DO_CODEX=1
CODEX_WINDOW=""
MODE="install"   # install | verify | uninstall

while [ $# -gt 0 ]; do
  case "$1" in
    --pct) PCT="${2:-}"; shift 2 ;;
    --pct=*) PCT="${1#*=}"; shift ;;
    --claude-only) DO_CODEX=0; shift ;;
    --codex-only) DO_CLAUDE=0; shift ;;
    --codex-window) CODEX_WINDOW="${2:-}"; shift 2 ;;
    --codex-window=*) CODEX_WINDOW="${1#*=}"; shift ;;
    --verify) MODE="verify"; shift ;;
    --uninstall) MODE="uninstall"; shift ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "未知参数: $1（-h 看用法）" >&2; exit 2 ;;
  esac
done

case "$PCT" in
  ''|*[!0-9]*) echo "⛔ --pct 需要 1-99 的整数，当前: $PCT" >&2; exit 2 ;;
esac
if [ "$PCT" -lt 1 ] || [ "$PCT" -gt 99 ]; then
  echo "⛔ --pct 需要 1-99 的整数，当前: $PCT" >&2; exit 2
fi

CLAUDE_SETTINGS="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}/settings.json"
CODEX_CONFIG="${CODEX_HOME:-${HOME}/.codex}/config.toml"

# ---------------- Claude Code ----------------
if [ "$DO_CLAUDE" -eq 1 ]; then
  echo "[Claude Code] ${CLAUDE_SETTINGS}"
  /usr/bin/python3 - "$CLAUDE_SETTINGS" "$PCT" "$MODE" <<'PY'
import json, os, sys

path, pct, mode = sys.argv[1], sys.argv[2], sys.argv[3]
KEY = "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"

if os.path.exists(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {}

cur_pct = (data.get("env") or {}).get(KEY)
cur_on = data.get("autoCompactEnabled")

if mode == "verify":
    state = "开启" if cur_on is not False else "关闭"
    print(f"      autoCompactEnabled = {cur_on!r}（自动压缩{state}）")
    print(f"      {KEY} = {cur_pct!r}" + ("" if cur_pct else "  ← 未设置，走内置默认(窗口-13000)"))
    sys.exit(0)

bak = path + ".bak.autocompact"
if os.path.exists(path):
    with open(bak, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if mode == "uninstall":
    env = data.get("env") or {}
    env.pop(KEY, None)
    if env:
        data["env"] = env
    else:
        data.pop("env", None)
    print(f"      已移除 {KEY}（autoCompactEnabled 保留不动）")
else:
    data.setdefault("env", {})[KEY] = str(pct)
    data["autoCompactEnabled"] = True
    print(f"      env.{KEY} = \"{pct}\"")
    print(f"      autoCompactEnabled = true")

os.makedirs(os.path.dirname(path), exist_ok=True)
tmp = path + ".tmp.autocompact"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(tmp, path)
if os.path.exists(bak):
    print(f"      已备份原配置 -> {bak}")
PY
fi

# ---------------- Codex CLI ----------------
if [ "$DO_CODEX" -eq 1 ]; then
  echo "[Codex CLI]   ${CODEX_CONFIG}"
  /usr/bin/python3 - "$CODEX_CONFIG" "$PCT" "$MODE" "$CODEX_WINDOW" <<'PY'
import math, os, re, sys

path, pct, mode, forced_window = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
LIMIT_KEY = "model_auto_compact_token_limit"
WIN_KEY = "model_context_window"

if not os.path.exists(path):
    print(f"      跳过：{path} 不存在（Codex 未安装或未初始化）")
    sys.exit(0)

with open(path, encoding="utf-8") as f:
    lines = f.read().splitlines()

# 顶层键只能待在第一个 [table] 之前
first_table = next((i for i, l in enumerate(lines) if l.lstrip().startswith("[")), len(lines))

def find(key):
    pat = re.compile(rf"^\s*{key}\s*=")
    for i in range(first_table):
        if pat.match(lines[i]):
            return i
    return -1

def value_at(i):
    if i < 0:
        return None
    m = re.search(r"=\s*([0-9_]+)", lines[i])
    return int(m.group(1).replace("_", "")) if m else None

win_i, limit_i = find(WIN_KEY), find(LIMIT_KEY)
window = int(forced_window) if forced_window else value_at(win_i)
cur_limit = value_at(limit_i)

if mode == "verify":
    print(f"      {WIN_KEY} = {window if window else '未设置（用模型自带窗口）'}")
    if cur_limit is None:
        print(f"      {LIMIT_KEY} = 未设置 ← 走 Codex 内置默认")
    else:
        ratio = f"{cur_limit / window * 100:.0f}%" if window else "未知占比"
        print(f"      {LIMIT_KEY} = {cur_limit}（约窗口的 {ratio}）")
    sys.exit(0)

bak = path + ".bak.autocompact"
with open(bak, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

if mode == "uninstall":
    if limit_i < 0:
        print(f"      {LIMIT_KEY} 本就不存在，无需改动")
        sys.exit(0)
    del lines[limit_i]
    print(f"      已移除 {LIMIT_KEY}")
else:
    if not window:
        print(f"      ⛔ 跳过：config.toml 没有 {WIN_KEY}，无法把 {pct}% 换算成 token 数")
        print(f"         请指定窗口后重跑，例如： bash autocompact.sh --codex-only --codex-window 272000")
        sys.exit(0)
    limit = int(math.floor(window * pct / 100))
    new_line = f"{LIMIT_KEY} = {limit}"
    if limit_i >= 0:
        lines[limit_i] = new_line
    else:
        insert_at = win_i + 1 if win_i >= 0 else first_table
        lines.insert(insert_at, new_line)
    print(f"      {WIN_KEY} = {window}")
    print(f"      {LIMIT_KEY} = {limit}（窗口的 {pct}%）")

tmp = path + ".tmp.autocompact"
with open(tmp, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
os.replace(tmp, path)
print(f"      已备份原配置 -> {bak}")
PY
fi

# 被 install.sh / install-codex.sh 内嵌调用时，尾部总结由调用方统一打印
[ -n "${AUTOCOMPACT_EMBED:-}" ] && exit 0

echo
case "$MODE" in
  verify) echo "以上为当前配置（未做改动）。" ;;
  uninstall) echo "已撤销 ✅ 重启 Claude Code / Codex 生效。" ;;
  *) echo "完成 ✅ 重启 Claude Code / Codex 后，上下文到 ${PCT}% 会自动压缩。"
     echo "查看生效值： bash autocompact.sh --verify" ;;
esac
