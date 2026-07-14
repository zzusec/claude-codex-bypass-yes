#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codex CLI 命令守卫 (PreToolUse + PermissionRequest Hook)
==========================================================
danger-guard.py 的 Codex 版。判定逻辑(正则引擎、白名单、rm 分级)与 Claude 版完全一致,
差异只在决策通道:Codex PreToolUse 对决策几乎是「只认 deny」——
  输出 permissionDecision:allow / ask 会被当成 unsupported 报错(Codex ≥0.144 实测)。
  所以「危险 → 弹确认」由三层配合完成:

  - 核武器级(不可逆毁灭) → PreToolUse 响铃 + 输出 deny(+reason)
  - 命中白名单 / 安全      → PreToolUse 静默(无输出)=放行,不弹框不响铃
  - 危险(可能合理)        → PreToolUse 响铃 + 无输出,交给 rules 的 prompt 档
                            或沙箱提权流程弹出原生确认框
  - PermissionRequest 事件 → 安全命令的提权请求自动点「允许」(bypass yes),
                            危险命令保持沉默让确认框弹出,毁灭级直接拒绝

配套文件:
  - ~/.codex/hooks.json          注册本脚本(PreToolUse + PermissionRequest)
  - ~/.codex/rules/danger-guard.rules  危险命令前缀 → prompt(弹确认)
  - allowlist.txt(本脚本同目录) 白名单正则,每行一条;同时兼读
    ~/.claude/hooks/allowlist.txt,两边共享放行规则

事件名通过 argv[1] 传入(hooks.json 里写死),缺省回退读 stdin JSON 的 hook_event_name。
任何异常都"安全失败"(exit 0 不干预),绝不因脚本 bug 卡住命令。
"""

import sys
import os
import json
import re
import shlex
import subprocess

# ============================================================
# 可配置区(与 danger-guard.py 保持一致)
# ============================================================

SOUND_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chime.wav")
SOUND_VOLUME = "0.5"  # afplay 相对系统音量的比例(0~1); 0.5=一半

_SYS = r"(?:/(?:etc|usr|bin|sbin|var|lib|lib64|boot|opt|root|System|Library|Applications)\b|\s/\s|\s/$|\s/\*)"

WARN_PATTERNS = [
    (r"\bdiskutil\b[^\n]*\b(erase|partition|reformat|eraseVolume|eraseDisk)\b", "diskutil 抹盘/分区"),
    (r"\bfdisk\b",                                                              "fdisk 分区"),
    (r"\bshutdown\b",                                                           "shutdown 关机"),
    (r"\breboot\b",                                                             "reboot 重启"),
    (r"\bhalt\b",                                                               "halt 停机"),
    (r"\bpoweroff\b",                                                           "poweroff 断电"),
    (r"\bchmod\b[^\n]*(?:-R|--recursive)[^\n]*" + _SYS,                         "chmod -R 改系统目录权限"),
    (r"\bchown\b[^\n]*(?:-R|--recursive)[^\n]*" + _SYS,                         "chown -R 改系统目录属主"),
    (r">\s*/etc/",                                                             "写入 /etc 系统文件"),
    (r"\bcurl\b[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b",                               "curl 管道执行远程脚本"),
    (r"\bwget\b[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b",                               "wget 管道执行远程脚本"),
    (r"\bgit\s+push\b[^\n]*(--force\b|--force-with-lease\b|\s-f\b)",            "git 强制推送"),
    (r"\bgit\s+reset\b[^\n]*--hard\b",                                          "git reset --hard 丢弃改动"),
    (r"\bgit\s+clean\b[^\n]*\s-\w*f",                                           "git clean -f 删未跟踪文件"),
    (r"\bnpm\s+publish\b",                                                      "npm publish 发布包"),
    (r"\bcrontab\b[^\n]*\s-r\b",                                                "crontab -r 清空定时任务"),
    (r"\bdocker\b[^\n]*\bprune\b[^\n]*(--volumes|--all|\s-a\b)",                "docker prune 清理(含数据卷/全部)"),
]

BLOCK_PATTERNS = [
    (r"\bmkfs(\.\w+)?\b",                                     "mkfs 格式化文件系统"),
    (r"\bdd\b[^\n]*\bof=/dev/r?(disk|sd|hd|nvme)",            "dd 写入物理磁盘"),
    (r">\s*/dev/r?(disk|sd|hd|nvme)",                         "重定向覆写物理磁盘"),
    (r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:&\s*\}\s*;\s*:",          "fork bomb 炸弹"),
    (r"\bdiskutil\b[^\n]*\beraseDisk\b",                      "diskutil 抹掉整盘"),
]


# ============================================================
# 预处理:屏蔽「数据」,补扫「会被执行的代码」(与 Claude 版一致)
# ============================================================

def mask_strings(cmd):
    """把引号内字符串内容替换为空格,使命令中的"数据词"不误触危险规则。"""
    out = []
    quote = None
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if quote:
            if quote == '"' and c == '\\' and i + 1 < n:
                out.append('  ')
                i += 2
                continue
            if c == quote:
                out.append(c)
                quote = None
            else:
                out.append('\n' if c == '\n' else ' ')
            i += 1
        else:
            if c in ('"', "'"):
                quote = c
            out.append(c)
            i += 1
    return ''.join(out)


def extract_code(cmd):
    """提取 bash -c / eval 里会被 shell 重新执行的内联代码,补扫防绕过。"""
    payloads = []
    for m in re.finditer(r"\b(?:ba|z|da|t?c|k|a)?sh\b[^\n;|&]*?\s-c\s+('[^']*'|\"[^\"]*\"|\S+)", cmd):
        payloads.append(m.group(1).strip("'\""))
    for m in re.finditer(r"\beval\s+('[^']*'|\"[^\"]*\"|[^\n;|&]+)", cmd):
        payloads.append(m.group(1).strip("'\""))
    return payloads


def build_scan_text(cmd):
    masked = mask_strings(cmd)
    payloads = extract_code(cmd)
    if payloads:
        return masked + "\n" + "\n".join(payloads)
    return masked


# ============================================================
# 白名单 / 提示音 / rm 分级
# ============================================================

def load_user_allow():
    """白名单正则:本脚本同目录 allowlist.txt + ~/.claude/hooks/allowlist.txt(两边共享)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(here, "allowlist.txt"),
        os.path.expanduser("~/.claude/hooks/allowlist.txt"),
    ]
    out = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    try:
                        re.compile(s)
                        out.append(s)
                    except re.error:
                        continue
        except Exception:
            continue
    return out


def play_sound():
    try:
        subprocess.Popen(
            ["afplay", "-v", SOUND_VOLUME, SOUND_FILE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


TEMP_ROOTS = ("/tmp", "/private/tmp")


def shell_segments(cmd):
    """按顶层 shell 分隔符切段;引号内的分隔符保留为参数内容。"""
    out, buf = [], []
    quote = None
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            buf.append(c)
            if quote == '"' and c == "\\" and i + 1 < len(cmd):
                buf.append(cmd[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
            buf.append(c)
        elif c in ";|&\n":
            if "".join(buf).strip():
                out.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    if quote:
        return []
    if "".join(buf).strip():
        out.append("".join(buf))
    return out


def rm_target_level(path, cwd, home):
    """单个 rm -rf 目标的级别:
    block = 根/家目录/整个用户目录/一级系统目录;
    ask   = 整个项目级(git 仓库根、家目录直接子项、当前所在目录)、系统路径、看不清的目标;
    allow = 普通目录/文件(项目内子目录、临时目录等)。"""
    if re.search(r"[$`*?\[]", path):
        return "ask"
    if path == "~":
        p = home
    elif path.startswith("~/"):
        p = os.path.join(home, path[2:])
    elif path.startswith("/"):
        p = path
    elif cwd:
        p = os.path.join(cwd, path)
    else:
        return "ask"
    p = os.path.normpath(p)

    if p == "/" or p == home:
        return "block"
    parts = p.strip("/").split("/")
    if len(parts) == 1:
        return "block"  # /etc、/usr、/tmp 等一级目录整删
    if parts[0] == "Users" and len(parts) == 2:
        return "block"  # 整个用户目录

    if cwd:
        ncwd = os.path.normpath(cwd)
        if p == ncwd or ncwd.startswith(p + "/"):
            return "ask"  # 删当前所在目录(所在项目)或其祖先
    inside_home = p.startswith(home + "/")
    if inside_home and "/" not in p[len(home) + 1:]:
        return "ask"  # 家目录直接子项,多半是整个项目/重要目录
    try:
        if os.path.isdir(os.path.join(p, ".git")):
            return "ask"  # git 仓库根 = 整个项目
    except Exception:
        return "ask"

    if inside_home or any(p.startswith(root + "/") for root in TEMP_ROOTS):
        return "allow"
    return "ask"  # 系统路径、其他用户、外接卷等,交人确认


def classify_rm_targets(cmd, cwd):
    """解析原始命令里所有直接执行的 rm -rf 目标,聚合为 block/warn/safe;解析不了一律 warn。"""
    if "$(" in cmd or "`" in cmd:
        return "warn"

    home = os.path.expanduser("~")
    found = False
    worst = "safe"
    for segment in shell_segments(cmd):
        try:
            args = shlex.split(segment, posix=True)
        except ValueError:
            return "warn"
        if not args or args[0] != "rm":
            continue

        has_r = has_f = False
        operands = []
        end_options = False
        for arg in args[1:]:
            if not end_options and arg == "--":
                end_options = True
            elif not end_options and arg.startswith("-") and arg != "-":
                has_r = has_r or arg == "--recursive" or "r" in arg[1:].lower()
                has_f = has_f or arg == "--force" or "f" in arg[1:].lower()
            else:
                operands.append(arg)

        if has_r and has_f:
            found = True
            if not operands:
                return "warn"
            for path in operands:
                level = rm_target_level(path, cwd, home)
                if level == "block":
                    return "block"
                if level == "ask":
                    worst = "warn"

    if not found:
        return "warn"
    return worst


def classify_rm(text, raw_cmd, cwd):
    if not re.search(r"\brm\b", text):
        return None
    has_r = bool(re.search(r"(?:^|\s)-\w*r", text, re.I)) or "--recursive" in text
    has_f = bool(re.search(r"(?:^|\s)-\w*f", text, re.I)) or "--force" in text
    if not (has_r and has_f):
        return None
    if re.search(r"(?:^|\s)(/|/\*|~|~/|~/\*|\$HOME|\$HOME/|\$HOME/\*|\$\{HOME\})(?:\s|$)", text):
        return "block"
    return classify_rm_targets(raw_cmd, cwd)


# ============================================================
# 分级 + 按事件输出决策
# ============================================================

def classify(cmd, cwd=""):
    """返回 (级别, 理由):block / allowlist / warn / safe。"""
    scan = build_scan_text(cmd)
    rm = classify_rm(scan, cmd, cwd)
    if rm == "block":
        return "block", "rm 递归删除根目录/家目录/整个用户目录/一级系统目录"
    for pattern, reason in BLOCK_PATTERNS:
        if re.search(pattern, scan):
            return "block", reason
    for pattern in load_user_allow():
        if re.search(pattern, cmd):
            return "allowlist", "命中白名单,放行"
    if rm == "warn":
        return "warn", "rm -rf 删除整个项目/系统路径或目标不明"
    for pattern, reason in WARN_PATTERNS:
        if re.search(pattern, scan):
            return "warn", reason
    return "safe", "未命中危险规则,自动放行"


def out_pretooluse(decision, reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": "[命令守卫] " + reason,
        }
    }, ensure_ascii=False))


def out_permission(behavior, message=None):
    decision = {"behavior": behavior}
    if message:
        decision["message"] = "[命令守卫] " + message
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": decision,
        }
    }, ensure_ascii=False))


def get_command(data):
    cmd = (data.get("tool_input") or {}).get("command", "")
    if isinstance(cmd, list):
        cmd = " ".join(str(x) for x in cmd)
    return cmd if isinstance(cmd, str) else ""


def main():
    data = json.loads(sys.stdin.read())
    event = (sys.argv[1] if len(sys.argv) > 1 else "") or data.get("hook_event_name", "") or "PreToolUse"

    tool = data.get("tool_name", "")
    if tool and tool not in ("Bash", "shell", "local_shell"):
        return
    cmd = get_command(data)
    if not cmd.strip():
        return

    level, reason = classify(cmd, data.get("cwd") or os.getcwd())

    if event == "PermissionRequest":
        # 提权/审批请求:安全 → 自动点「允许」;危险 → 沉默让确认框弹出;毁灭级 → 拒绝
        if level == "block":
            play_sound()
            out_permission("deny", reason)
        elif level in ("allowlist", "safe"):
            out_permission("allow")
        # warn → 不输出(PreToolUse 已响过铃,这里让原生确认框弹出)
        return

    # PreToolUse
    # Codex 只支持 permissionDecision:deny(+非空 reason);allow/ask 会报
    # "unsupported permissionDecision:..." 并记为 hook failed。
    # 放行方式:exit 0 且不输出决策 JSON(静默=继续执行)。
    if level == "block":
        play_sound()
        out_pretooluse("deny", reason)
    elif level in ("allowlist", "safe"):
        return  # 静默放行
    else:
        # warn:不支持 ask → 响铃提醒,不输出决策,
        # 交给 rules 的 prompt 档或沙箱提权流程弹原生确认框
        play_sound()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
