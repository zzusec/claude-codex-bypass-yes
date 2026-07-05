#!/usr/bin/env bash
# Codex CLI 命令守卫 — 安装脚本 (macOS)
# 复制脚本/铃声到 ~/.codex/hooks/,合并 hooks.json,安装 danger-guard.rules,
# 并检测其他 .rules 文件里会压过 prompt 的 forbidden 冲突条目。
set -euo pipefail

CODEX_DIR="${CODEX_HOME:-${HOME}/.codex}"
HOOKS_DIR="${CODEX_DIR}/hooks"
RULES_DIR="${CODEX_DIR}/rules"
HOOKS_JSON="${CODEX_DIR}/hooks.json"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_DST="${HOOKS_DIR}/danger-guard-codex.py"

echo "[1/4] 复制脚本与铃声 -> ${HOOKS_DIR}"
mkdir -p "${HOOKS_DIR}" "${RULES_DIR}"
cp "${SRC_DIR}/danger-guard-codex.py" "${SCRIPT_DST}"
cp "${SRC_DIR}/chime.wav" "${HOOKS_DIR}/chime.wav"

echo "[2/4] 合并 PreToolUse + PermissionRequest hook -> ${HOOKS_JSON}"
/usr/bin/python3 - "$HOOKS_JSON" "$SCRIPT_DST" <<'PY'
import json, os, sys

hooks_path, script_dst = sys.argv[1], sys.argv[2]

if os.path.exists(hooks_path):
    with open(hooks_path, encoding="utf-8") as f:
        data = json.load(f)
    bak = hooks_path + ".bak.cmdguard"
    with open(bak, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("      已备份原配置 ->", bak)
else:
    data = {}

hooks = data.setdefault("hooks", {})

def entry(event):
    return {
        "matcher": "Bash",
        "hooks": [
            {"type": "command",
             "command": f"/usr/bin/python3 {script_dst} {event}",
             "timeout": 10}
        ],
    }

def points_to_guard(e):
    return any("danger-guard-codex.py" in h.get("command", "") for h in e.get("hooks", []))

for event in ("PreToolUse", "PermissionRequest"):
    lst = hooks.setdefault(event, [])
    lst[:] = [e for e in lst if not points_to_guard(e)]
    lst.append(entry(event))

with open(hooks_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("      已写入 PreToolUse + PermissionRequest hook")
PY

echo "[3/4] 安装危险确认规则 -> ${RULES_DIR}/danger-guard.rules"
cp "${SRC_DIR}/danger-guard.rules" "${RULES_DIR}/danger-guard.rules"

echo "[4/4] 检查其他 .rules 文件的 forbidden 冲突(会压过 prompt 弹确认)"
conflict=0
for f in "${RULES_DIR}"/*.rules; do
  [ "$(basename "$f")" = "danger-guard.rules" ] && continue
  if grep -nE 'decision="forbidden"' "$f" | grep -E '"rm"|"git"' >/dev/null 2>&1; then
    conflict=1
    echo "      ⚠ ${f} 中以下 forbidden 条目会压过弹确认(rules 取最严格),建议改为 prompt 或删除:"
    grep -nE 'decision="forbidden"' "$f" | grep -E '"rm"|"git"' | sed 's/^/        /'
  fi
done
[ "$conflict" -eq 0 ] && echo "      无冲突"

echo
echo "完成 ✅ 请重启 Codex(新会话生效)。"
echo "验证 hook:"
echo "  echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"rm -rf /\"}}' | /usr/bin/python3 ${SCRIPT_DST} PreToolUse"
echo "验证 rules:"
echo "  codex execpolicy check --rules ${RULES_DIR}/danger-guard.rules --pretty -- git reset --hard HEAD~1"
