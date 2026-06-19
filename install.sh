#!/usr/bin/env bash
# Claude Code 命令守卫 — 安装脚本 (macOS)
# 复制脚本到 ~/.claude/hooks/,并安全合并 PreToolUse hook 到 settings.json。
set -euo pipefail

CLAUDE_DIR="${HOME}/.claude"
HOOKS_DIR="${CLAUDE_DIR}/hooks"
SETTINGS="${CLAUDE_DIR}/settings.json"
SCRIPT_SRC="$(cd "$(dirname "$0")" && pwd)/danger-guard.py"
SCRIPT_DST="${HOOKS_DIR}/danger-guard.py"

echo "[1/3] 复制脚本 -> ${SCRIPT_DST}"
mkdir -p "${HOOKS_DIR}"
cp "${SCRIPT_SRC}" "${SCRIPT_DST}"

echo "[2/3] 合并 PreToolUse hook -> ${SETTINGS}"
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

echo "[3/3] 完成 ✅"
echo
echo "请重启 Claude Code,或在会话内输入 /hooks 确认加载。"
echo "验证:"
echo "  echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"rm -rf /tmp/x\"}}' | /usr/bin/python3 ${SCRIPT_DST}"
