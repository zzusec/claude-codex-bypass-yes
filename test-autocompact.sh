#!/usr/bin/env bash
# autocompact.sh 自测：在临时目录里跑，不碰真实 ~/.claude 和 ~/.codex
set -uo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export CLAUDE_CONFIG_DIR="$TMP/claude"
export CODEX_HOME="$TMP/codex"
mkdir -p "$CLAUDE_CONFIG_DIR" "$CODEX_HOME"

pass=0; fail=0
check() { # check <描述> <期望包含> <实际>
  if printf '%s' "$3" | grep -qF "$2"; then
    pass=$((pass+1)); echo "  ✅ $1"
  else
    fail=$((fail+1)); echo "  ❌ $1"; echo "     期望包含: $2"; echo "     实际: $3"
  fi
}

cat > "$CLAUDE_CONFIG_DIR/settings.json" <<'JSON'
{
  "model": "opus",
  "env": {"CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"},
  "permissions": {"defaultMode": "bypassPermissions"}
}
JSON

cat > "$CODEX_HOME/config.toml" <<'TOML'
model = "gpt-5.6-sol"
model_context_window = 1000000
model_auto_compact_token_limit = 900000

[projects."/tmp/x"]
trust_level = "trusted"
TOML

echo "[1] 安装 80%"
out="$(bash "$SRC_DIR/autocompact.sh" --pct 80 2>&1)"
check "Claude 写入 80" 'CLAUDE_AUTOCOMPACT_PCT_OVERRIDE = "80"' "$out"
check "Codex 换算 800000" "model_auto_compact_token_limit = 800000（窗口的 80%）" "$out"
check "Claude 保留原有 env" '"CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"' "$(cat "$CLAUDE_CONFIG_DIR/settings.json")"
check "Claude 保留原有 permissions" '"defaultMode": "bypassPermissions"' "$(cat "$CLAUDE_CONFIG_DIR/settings.json")"
check "Claude 开启 autoCompactEnabled" '"autoCompactEnabled": true' "$(cat "$CLAUDE_CONFIG_DIR/settings.json")"
check "Codex 未新增重复键" "1" "$(grep -c '^model_auto_compact_token_limit' "$CODEX_HOME/config.toml")"
check "Codex 保留 projects 表" 'trust_level = "trusted"' "$(cat "$CODEX_HOME/config.toml")"

echo "[2] 幂等：重复安装 70%"
out="$(bash "$SRC_DIR/autocompact.sh" --pct 70 2>&1)"
check "Codex 换算 700000" "model_auto_compact_token_limit = 700000" "$out"
check "Codex 仍只有一行" "1" "$(grep -c '^model_auto_compact_token_limit' "$CODEX_HOME/config.toml")"
check "Claude 写入 70" '"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "70"' "$(cat "$CLAUDE_CONFIG_DIR/settings.json")"

echo "[3] verify 不改配置"
before="$(cat "$CODEX_HOME/config.toml")"
out="$(bash "$SRC_DIR/autocompact.sh" --verify 2>&1)"
check "verify 显示 Claude 值" "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE = '70'" "$out"
check "verify 显示 Codex 占比" "约窗口的 70%" "$out"
check "verify 未改动文件" "$before" "$(cat "$CODEX_HOME/config.toml")"

echo "[4] Codex 缺 model_context_window 时不乱写"
cat > "$CODEX_HOME/config.toml" <<'TOML'
model = "gpt-5.6-sol"

[projects."/tmp/x"]
trust_level = "trusted"
TOML
out="$(bash "$SRC_DIR/autocompact.sh" --codex-only 2>&1)"
check "提示需要指定窗口" "无法把 80% 换算成 token 数" "$out"
check "未写入任何 limit" "0" "$(grep -c '^model_auto_compact_token_limit' "$CODEX_HOME/config.toml")"

echo "[5] --codex-window 手动指定窗口"
out="$(bash "$SRC_DIR/autocompact.sh" --codex-only --codex-window 272000 2>&1)"
check "换算 217600" "model_auto_compact_token_limit = 217600" "$out"
check "插在第一个 table 之前" "1" "$(awk '/^\[/{exit} /^model_auto_compact_token_limit/{n++} END{print n+0}' "$CODEX_HOME/config.toml")"

echo "[6] uninstall"
out="$(bash "$SRC_DIR/autocompact.sh" --uninstall 2>&1)"
check "Codex 移除 limit" "0" "$(grep -c '^model_auto_compact_token_limit' "$CODEX_HOME/config.toml")"
check "Claude 移除 override" "0" "$(grep -c 'CLAUDE_AUTOCOMPACT_PCT_OVERRIDE' "$CLAUDE_CONFIG_DIR/settings.json")"
check "Claude 其它 env 保留" '"CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"' "$(cat "$CLAUDE_CONFIG_DIR/settings.json")"

echo "[7] 参数校验"
out="$(bash "$SRC_DIR/autocompact.sh" --pct 120 2>&1)"; rc=$?
check "拒绝非法百分比" "需要 1-99 的整数" "$out"
check "非零退出码" "2" "$rc"

echo
echo "通过 $pass / 失败 $fail"
[ "$fail" -eq 0 ]
