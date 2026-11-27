"""Everything 搜索：把盒子搜索框里的关键词交给 Everything 执行。"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import winreg

EXE_NAME = "Everything.exe"
DOWNLOAD_PAGE = "https://www.voidtools.com/zh-cn/downloads/"


def read_payload() -> dict:
    """读取盒子传入的参数 JSON；手动双击运行时返回空字典。"""
    if len(sys.argv) < 2:
        return {}
    try:
        with open(sys.argv[1], encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def read_keyword(payload: dict) -> str:
    values = payload.get("data", {}).get("keyword")
    if isinstance(values, list) and values:
        return str(values[0]).strip()
    if isinstance(values, str):
        return values.strip()
    return ""


def is_exe(path) -> bool:
    return bool(path) and isinstance(path, str) and path.lower().endswith(".exe") and os.path.isfile(path)


def to_exe(raw) -> str | None:
    """把注册表里的安装位置或 DisplayIcon 转成可执行文件路径。"""
    if not raw or not isinstance(raw, str):
        return None
    path = raw.strip().strip('"').split(",", 1)[0].strip().strip('"')
    if path.lower().endswith(".exe"):
        return path if is_exe(path) else None
    candidate = os.path.join(path, EXE_NAME)
    return candidate if is_exe(candidate) else None


def read_reg(root, key: str, value_name: str) -> str | None:
    try:
        with winreg.OpenKey(root, key) as handle:
            value, _ = winreg.QueryValueEx(handle, value_name)
            return value if isinstance(value, str) else None
    except OSError:
        return None


def list_subkeys(root, key: str):
    try:
        with winreg.OpenKey(root, key) as handle:
            index = 0
            while True:
                try:
                    yield winreg.EnumKey(handle, index)
                except OSError:
                    return
                index += 1
    except OSError:
        return


def from_env() -> str | None:
    return to_exe(os.environ.get("EVERYTHING_EXE"))


def from_path() -> str | None:
    return shutil.which(EXE_NAME)


def from_registry() -> str | None:
    candidates = []
    for root, key in (
        (winreg.HKEY_CURRENT_USER, r"Software\voidtools\Everything"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\voidtools\Everything"),
    ):
        for value_name in ("InstallLocation", "InstallPath", "ExePath", "Path"):
            candidates.append(read_reg(root, key, value_name))

    uninstall_keys = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for root, key in uninstall_keys:
        for sub in list_subkeys(root, key):
            display_name = read_reg(root, key + "\\" + sub, "DisplayName") or ""
            if "everything" not in display_name.lower():
                continue
            candidates.append(read_reg(root, key + "\\" + sub, "InstallLocation"))
            candidates.append(read_reg(root, key + "\\" + sub, "DisplayIcon"))

    for raw in candidates:
        exe = to_exe(raw)
        if exe:
            return exe
    return None


def from_common_dirs() -> str | None:
    bases = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramW6432"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    ]
    for base in bases:
        if not base:
            continue
        candidate = os.path.join(base, "Everything", EXE_NAME)
        if is_exe(candidate):
            return candidate
    return None


def bundled_exe(payload: dict) -> str | None:
    """盒子安装时下载的便携版路径，注入在 environment.binaries 里。"""
    binaries = payload.get("environment", {}).get("binaries", {})
    if not isinstance(binaries, dict):
        return None
    for commands in binaries.values():
        if isinstance(commands, dict):
            for path in commands.values():
                if is_exe(path):
                    return path
    return None


def find_everything(payload: dict) -> str | None:
    for finder in (from_env, from_path, from_registry, from_common_dirs):
        exe = finder()
        if is_exe(exe):
            return exe
    return bundled_exe(payload)


def needs_admin_notice(exe: str, payload: dict) -> bool:
    """便携版没有系统服务，首次启动要靠管理员建索引；建过索引就不再打扰。"""
    bundled = bundled_exe(payload)
    if not bundled or os.path.normcase(exe) != os.path.normcase(bundled):
        return False
    return not os.path.isfile(os.path.join(os.path.dirname(exe), "Everything.ini"))


def launch(exe: str, keyword: str) -> None:
    command = [exe, "-search", keyword] if keyword else [exe]
    subprocess.Popen(command, close_fds=True)


def alert(title: str, text: str, ask_open: bool = False) -> None:
    flags = 0x10 | (0x04 if ask_open else 0x00)
    answer = ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    if ask_open and answer == 6:
        ctypes.windll.shell32.ShellExecuteW(None, "open", DOWNLOAD_PAGE, None, None, 1)


def main() -> None:
    payload = read_payload()
    keyword = read_keyword(payload)
    exe = find_everything(payload)
    if not exe:
        alert(
            "未找到 Everything",
            "本脚本没有找到 Everything.exe。\n\n"
            "正常情况下，安装本脚本时盒子会自动下载便携版 Everything。\n"
            "如果它被清理掉了，请在盒子里更新或重装本脚本。\n\n"
            "要现在打开 Everything 官方下载页吗？",
            ask_open=True,
        )
        return
    if needs_admin_notice(exe, payload):
        alert(
            "首次使用 Everything 便携版",
            "盒子自带的便携版没有安装系统服务，第一次启动会请求管理员权限来建立 NTFS 索引。\n"
            "Windows 弹出授权窗口时点「是」即可，之后搜索就正常了。\n\n"
            "电脑上已经装过 Everything 的话，脚本会优先用已安装的版本，不会出现这个提示。",
        )
    try:
        launch(exe, keyword)
    except OSError as exc:
        alert("启动 Everything 失败", f"程序路径：{exe}\n错误信息：{exc}")


if __name__ == "__main__":
    main()
