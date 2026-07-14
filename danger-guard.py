#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 命令守卫 (PreToolUse Hook)
========================================
判定每条 Bash 命令的危险程度:
  - 核武器级(不可逆毁灭) → 响铃 + 直接拒绝(deny)
  - 命中白名单            → 静默放行(无输出),不响铃不确认 —— 见同目录 allowlist.txt
  - 危险(可能合理)        → 响铃 + 弹确认(ask)
  - 命中你的 deny 名单      → 交回(exit 0),让 settings 的静态 deny 按原语义处理
  - 安全(其余)            → 静默放行(无输出)

注意: 当前 Claude Code(含 auto 模式)只接受 hook 的 deny/ask;
      输出 permissionDecision:"allow" 会报 unsupported 并导致 PreToolUse failed。
      安全路径必须「不打印 JSON」,交给权限模式(auto / bypassPermissions)自行放行。

设计原则:
  1. 只拦「真正的系统级毁灭/高危」命令,其余一律放行,尽量不打断自主流程。
  2. 只匹配「命令本身」,不匹配引号内的数据。
     例如 `psql -c "DELETE FROM t"`、`git commit -m "remove reboot logic"`、
     `echo "rm -rf /"` 都是数据,不该被拦 —— 见 mask_strings()。
  3. 但 `bash -c "..."` / `eval "..."` 里的内容是会被执行的代码,仍会补扫 —— 见 extract_code()。
  4. 任何异常都"安全失败"(exit 0 不干预),绝不因脚本 bug 卡住命令。
  5. 白名单优先于 WARN/RETURN,但毁灭级 BLOCK 仍兜底拦截(防手滑)。

永久放行某类命令:在同目录 allowlist.txt 加一行正则(即时生效)。
"""

import sys
import os
import json
import re
import shlex
import subprocess

# ============================================================
# 可配置区
# ============================================================

SOUND_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chime.wav")
SOUND_VOLUME = "0.5"  # afplay 相对系统音量的比例(0~1); 0.5=一半

# 系统关键目录(chmod/chown 等仅当作用于这些目录时才视为危险)
_SYS = r"(?:/(?:etc|usr|bin|sbin|var|lib|lib64|boot|opt|root|System|Library|Applications)\b|\s/\s|\s/$|\s/\*)"

# WARN:危险但可能合理 → 响铃 + 弹确认(ask)
# 说明:只保留「系统级 / 难以撤销 / 对外发布」的操作。日常 dev 命令(kill、killall、
# rmdir、unlink、git branch -D、sudo 本身等)一律不在此列,避免误拦。
WARN_PATTERNS = [
    # 磁盘 / 分区
    (r"\bdiskutil\b[^\n]*\b(erase|partition|reformat|eraseVolume|eraseDisk)\b", "diskutil 抹盘/分区"),
    (r"\bfdisk\b",                                                              "fdisk 分区"),
    # 关机 / 重启
    (r"\bshutdown\b",                                                           "shutdown 关机"),
    (r"\breboot\b",                                                             "reboot 重启"),
    (r"\bhalt\b",                                                               "halt 停机"),
    (r"\bpoweroff\b",                                                           "poweroff 断电"),
    # 改系统目录权限/属主(仅作用于系统路径时)
    (r"\bchmod\b[^\n]*(?:-R|--recursive)[^\n]*" + _SYS,                         "chmod -R 改系统目录权限"),
    (r"\bchown\b[^\n]*(?:-R|--recursive)[^\n]*" + _SYS,                         "chown -R 改系统目录属主"),
    # 写系统配置
    (r">\s*/etc/",                                                             "写入 /etc 系统文件"),
    # 远程脚本直执
    (r"\bcurl\b[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b",                               "curl 管道执行远程脚本"),
    (r"\bwget\b[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b",                               "wget 管道执行远程脚本"),
    # git 破坏性 / 改远程历史
    (r"\bgit\s+push\b[^\n]*(--force\b|--force-with-lease\b|\s-f\b)",            "git 强制推送"),
    (r"\bgit\s+reset\b[^\n]*--hard\b",                                          "git reset --hard 丢弃改动"),
    (r"\bgit\s+clean\b[^\n]*\s-\w*f",                                           "git clean -f 删未跟踪文件"),
    # 对外发布
    (r"\bnpm\s+publish\b",                                                      "npm publish 发布包"),
    # 定时任务整表清空 / 删带数据卷的 docker 资源
    (r"\bcrontab\b[^\n]*\s-r\b",                                                "crontab -r 清空定时任务"),
    (r"\bdocker\b[^\n]*\bprune\b[^\n]*(--volumes|--all|\s-a\b)",                "docker prune 清理(含数据卷/全部)"),
]

# BLOCK:不可逆毁灭 → 响铃 + 直接拒绝(deny)
BLOCK_PATTERNS = [
    (r"\bmkfs(\.\w+)?\b",                                     "mkfs 格式化文件系统"),
    (r"\bdd\b[^\n]*\bof=/dev/r?(disk|sd|hd|nvme)",            "dd 写入物理磁盘"),
    (r">\s*/dev/r?(disk|sd|hd|nvme)",                         "重定向覆写物理磁盘"),
    (r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:&\s*\}\s*;\s*:",          "fork bomb 炸弹"),
    (r"\bdiskutil\b[^\n]*\beraseDisk\b",                      "diskutil 抹掉整盘"),
]

# RETURN:命中你 settings.json 的 deny 名单、但未被上面覆盖的命令 → 交回静态规则
RETURN_PATTERNS = [
    r"\brm\b",
    r"\bdd\b",
    r"\bdiskutil\b",
    r"\binit\s+0\b",
]


# ============================================================
# 预处理:屏蔽「数据」,补扫「会被执行的代码」
# ============================================================

def mask_strings(cmd):
    """把引号内字符串内容替换为空格,使命令中的"数据词"(SQL、commit 信息、echo 文本、
    参数值等)不再误触危险规则;保留引号本身及引号外的 shell 结构(管道、重定向)。"""
    out = []
    quote = None
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if quote:
            # 双引号内的反斜杠转义:跳过下一个字符
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
    """提取会被 shell 重新执行的内联代码(bash -c / sh -c / eval),作为危险扫描的补充输入,
    防止把真正危险命令藏在引号里绕过 mask_strings()。"""
    payloads = []
    for m in re.finditer(r"\b(?:ba|z|da|t?c|k|a)?sh\b[^\n;|&]*?\s-c\s+('[^']*'|\"[^\"]*\"|\S+)", cmd):
        payloads.append(m.group(1).strip("'\""))
    for m in re.finditer(r"\beval\s+('[^']*'|\"[^\"]*\"|[^\n;|&]+)", cmd):
        payloads.append(m.group(1).strip("'\""))
    return payloads


def build_scan_text(cmd):
    """用于危险匹配的文本 = 屏蔽数据后的命令 + 内联代码补扫。"""
    masked = mask_strings(cmd)
    payloads = extract_code(cmd)
    if payloads:
        return masked + "\n" + "\n".join(payloads)
    return masked


# ============================================================
# 逻辑
# ============================================================

def load_user_allow():
    """从同目录 allowlist.txt 读白名单(每行一个正则;# 注释;坏正则跳过;文件缺失忽略)。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "allowlist.txt")
    out = []
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
        pass
    return out


def play_sound(decision):
    """后台异步播放提示音,不阻塞决策返回。"""
    if decision not in ("deny", "ask"):
        return
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
    """按顶层 shell 分隔符切段；引号内的分隔符保留为参数内容。"""
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
    """删根/家/用户目录级 → block;删整个项目/系统路径 → warn;普通目录 → safe。"""
    if not re.search(r"\brm\b", text):
        return None
    has_r = bool(re.search(r"(?:^|\s)-\w*r", text, re.I)) or "--recursive" in text
    has_f = bool(re.search(r"(?:^|\s)-\w*f", text, re.I)) or "--force" in text
    if not (has_r and has_f):
        return None
    if re.search(r"(?:^|\s)(/|/\*|~|~/|~/\*|\$HOME|\$HOME/|\$HOME/\*|\$\{HOME\})(?:\s|$)", text):
        return "block"
    return classify_rm_targets(raw_cmd, cwd)


def decide(decision, reason):
    # allow 不能写回 permissionDecision:"allow":
    # Claude Code auto 模式会报 unsupported permissionDecision:allow,
    # 静默 exit 0 = 不干预,由 defaultMode(auto/bypass) 决定是否执行。
    if decision == "allow":
        return
    play_sound(decision)
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": "[命令守卫] " + reason,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def main():
    data = json.loads(sys.stdin.read())

    if data.get("tool_name") != "Bash":
        return
    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd or not cmd.strip():
        return

    # 用于危险匹配的文本:屏蔽引号内数据 + 补扫内联代码
    scan = build_scan_text(cmd)

    cwd = data.get("cwd") or os.getcwd()
    rm = classify_rm(scan, cmd, cwd)
    if rm == "block":
        decide("deny", "rm 递归删除根目录/家目录/整个用户目录/一级系统目录")
        return

    for pattern, reason in BLOCK_PATTERNS:
        if re.search(pattern, scan):
            decide("deny", reason)
            return

    # 白名单 → 直接放行(优先于 WARN/RETURN,但 BLOCK 已先拦)。按命令原文匹配。
    for pattern in load_user_allow():
        if re.search(pattern, cmd):
            decide("allow", "命中白名单,放行")
            return

    if rm == "warn":
        decide("ask", "rm -rf 删除整个项目/系统路径或目标不明")
        return

    for pattern, reason in WARN_PATTERNS:
        if re.search(pattern, scan):
            decide("ask", reason)
            return

    # safe:rm -rf 目标全部是普通目录/临时目录 → 静默放行,不交回静态规则
    if rm == "safe":
        decide("allow", "rm -rf 目标为普通目录,自动放行")
        return

    for pattern in RETURN_PATTERNS:
        if re.search(pattern, scan):
            return

    decide("allow", "未命中危险规则,自动放行")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
