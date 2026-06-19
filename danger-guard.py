#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 命令守卫 (PreToolUse Hook)
========================================
作用:每条 Bash 命令执行前判定危险程度
  - 核武器级(不可逆毁灭) → 响铃(两声,急促) + 直接拒绝(deny)
  - 危险(可能合理)        → 响铃(一声) + 弹确认(ask),由你当场决定
  - 命中你的 deny 名单      → 交回(exit 0),让 settings 里的静态 deny 按原语义直接拒绝
  - 安全(其余一切)        → 自动放行(allow),连确认框都不弹

设计原则:
  1. 任何解析异常都"安全失败"(exit 0 不干预),绝不因脚本 bug 卡住正常命令。
  2. allow 会绕过整个权限系统(含你的 deny 黑名单),所以命中 deny 名单的命令绝不 allow,
     而是交回静态规则处理 —— 见 RETURN_PATTERNS。

要增删规则,直接改下面的 WARN_PATTERNS / BLOCK_PATTERNS / RETURN_PATTERNS 即可。
"""

import sys
import json
import re
import subprocess

# ============================================================
# 可配置区
# ============================================================

# 提示音(可换成 /System/Library/Sounds/ 下任意: Sosumi/Funk/Glass/Hero/Ping...)
SOUND_WARN = "/System/Library/Sounds/Basso.aiff"    # 危险(ask):响一声
SOUND_BLOCK = "/System/Library/Sounds/Sosumi.aiff"  # 毁灭级(deny):急促两声

# WARN:危险但可能合理 → 响铃 + 弹确认(ask)。 (正则, 中文说明)
WARN_PATTERNS = [
    (r"\bsudo\b",                                              "sudo 提权"),
    (r"\brmdir\b",                                             "rmdir 删除目录"),
    (r"\bfind\b[^\n]*\s-delete\b",                             "find -delete 批量删除"),
    (r"\bunlink\b",                                            "unlink 删除文件"),
    (r"\bdiskutil\b[^\n]*\b(erase|partition|reformat|eraseDisk|eraseVolume)\b", "diskutil 抹盘/分区"),
    (r"\bfdisk\b",                                             "fdisk 分区"),
    (r">\s*/dev/(disk|rdisk|sd|hd|nvme)",                      "重定向写入磁盘设备"),
    (r"\bchmod\b[^\n]*(-R|777)",                               "chmod 大范围改权限"),
    (r"\bchown\b",                                             "chown 改所有者"),
    (r"\bshutdown\b",                                          "shutdown 关机"),
    (r"\breboot\b",                                            "reboot 重启"),
    (r"\bhalt\b",                                              "halt 停机"),
    (r"\bpoweroff\b",                                          "poweroff 断电"),
    (r"\bkill\b\s+-9\b",                                       "kill -9 强杀进程"),
    (r"\bkillall\b",                                           "killall 批量杀进程"),
    (r"\bpkill\b",                                             "pkill 批量杀进程"),
    (r"\bcrontab\b[^\n]*\s-r\b",                               "crontab -r 清空定时任务"),
    (r"\bcurl\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b",                 "curl 管道执行远程脚本"),
    (r"\bwget\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b",                 "wget 管道执行远程脚本"),
    (r"\bgit\s+push\b[^\n]*(--force\b|--force-with-lease\b|\s-f\b)", "git 强制推送"),
    (r"\bgit\s+reset\b[^\n]*--hard\b",                         "git reset --hard 丢弃改动"),
    (r"\bgit\s+clean\b[^\n]*\s-\w*f",                          "git clean -f 删未跟踪文件"),
    # —— 以下为贴合常用开发场景补充的危险命令 ——
    (r"\bgit\s+restore\b",                                    "git restore 丢弃工作区改动"),
    (r"\bgit\s+checkout\b[^\n]*\s--(\s|$)",                    "git checkout -- 丢弃文件改动"),
    (r"\bgit\s+checkout\b\s+\.\s*$",                           "git checkout . 丢弃全部改动"),
    (r"\bgit\s+branch\b[^\n]*\s-D\b",                          "git branch -D 强制删分支"),
    (r"\bgit\s+stash\b[^\n]*\b(clear|drop)\b",                 "git stash 丢弃储藏"),
    (r"\bnpm\s+publish\b",                                     "npm publish 发布包"),
    (r"\bdocker\b[^\n]*\bprune\b",                             "docker prune 清理资源"),
    (r"\bdefaults\s+delete\b",                                 "defaults delete 删 macOS 偏好"),
    (r"\blaunchctl\b[^\n]*\b(unload|remove|bootout)\b",        "launchctl 卸载服务"),
    (r">\s*/etc/",                                             "写入 /etc 系统文件"),
    (r"(?i)\bDROP\s+(TABLE|DATABASE)\b",                       "SQL DROP"),
    (r"(?i)\bTRUNCATE\b",                                      "SQL TRUNCATE"),
    (r"(?i)\bDELETE\s+FROM\b",                                 "SQL DELETE FROM"),
]

# BLOCK:不可逆毁灭 → 响铃 + 直接拒绝(deny)。 (正则, 中文说明)
BLOCK_PATTERNS = [
    (r"\bmkfs(\.\w+)?\b",                                      "mkfs 格式化文件系统"),
    (r"\bdd\b[^\n]*\bof=/dev/r?(disk|sd|hd|nvme)",             "dd 写入物理磁盘"),
    (r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",        "fork bomb 炸弹"),
    (r"\bdiskutil\b[^\n]*\beraseDisk\b",                       "diskutil 抹掉整盘"),
]

# RETURN:命中你 settings.json 的 deny 名单、但未被上面 WARN/BLOCK 覆盖的命令。
# 这类不自动放行(allow),而是"交回"(exit 0),让静态 deny 按你原本的"直接拒绝"语义处理。
# 若你改了 settings 的 deny 名单,这里同步增减即可。
RETURN_PATTERNS = [
    r"\brm\b",                  # 你 deny 了所有 rm(含非 -rf);交回让 deny 生效
    r"\bdd\b",                  # 你 deny 了所有 dd
    r"\bdiskutil\b",            # 你 deny 了所有 diskutil
    r"\binit\s+0\b",            # 你 deny 了 init 0
    r"\bcat\b[^\n]*>\s*/dev/",  # 你 deny 了 cat 重定向到 /dev/
]


# ============================================================
# 逻辑
# ============================================================

def play_sound(decision):
    """后台异步播放提示音,不阻塞决策返回。
    deny → 两声 Sosumi(急促醒目);ask → 一声 Basso。
    """
    try:
        if decision == "deny":
            # 顺序两声,用 shell 串联(路径无空格,安全)
            subprocess.Popen(
                "afplay {0} ; afplay {0}".format(SOUND_BLOCK),
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif decision == "ask":
            subprocess.Popen(
                ["afplay", SOUND_WARN],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


def classify_rm(cmd):
    """rm 专项:返回 'block' / 'warn' / None。
    - 带 -r 且 -f,且目标是根/家目录整体 → block
    - 带 -r 且 -f(其它目标)             → warn
    """
    if not re.search(r"\brm\b", cmd):
        return None
    has_r = bool(re.search(r"(?:^|\s)-\w*r", cmd, re.I)) or "--recursive" in cmd
    has_f = bool(re.search(r"(?:^|\s)-\w*f", cmd, re.I)) or "--force" in cmd
    if not (has_r and has_f):
        return None
    # 目标恰为 根 / 家目录(整体),例如 / , /* , ~ , ~/ , ~/* , $HOME , $HOME/*
    if re.search(r"(?:^|\s)(/|/\*|~|~/|~/\*|\$HOME|\$HOME/|\$HOME/\*|\$\{HOME\})(?:\s|$)", cmd):
        return "block"
    return "warn"


def decide(decision, reason):
    """输出 PreToolUse 决策 JSON;deny/ask 档同时响铃。"""
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

    # 只管 Bash 命令;其它工具不干预
    if data.get("tool_name") != "Bash":
        return
    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd or not cmd.strip():
        return

    # 1) rm 根/家目录删除 → 直接拒绝
    rm = classify_rm(cmd)
    if rm == "block":
        decide("deny", "rm 递归删除根目录/家目录")
        return

    # 2) BLOCK 清单 → 直接拒绝
    for pattern, reason in BLOCK_PATTERNS:
        if re.search(pattern, cmd):
            decide("deny", reason)
            return

    # 3) rm -rf(其它目标) → 弹确认
    if rm == "warn":
        decide("ask", "rm -rf 递归强制删除")
        return

    # 4) WARN 清单 → 弹确认
    for pattern, reason in WARN_PATTERNS:
        if re.search(pattern, cmd):
            decide("ask", reason)
            return

    # 5) 命中你的 deny 名单(未被上面覆盖)→ 交回静态 deny,不自动放行
    for pattern in RETURN_PATTERNS:
        if re.search(pattern, cmd):
            return

    # 6) 其余安全命令 → 自动放行(连确认框都不弹)
    decide("allow", "未命中危险规则,自动放行")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 安全失败:任何异常都不干预,避免卡住正常命令
        sys.exit(0)
