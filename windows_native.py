"""Windows 专用：工作区尺寸、启动项快捷方式（无第三方依赖）。"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


SPI_GETWORKAREA = 48


def primary_work_area() -> tuple[int, int, int, int]:
    """主显示器工作区 (left, top, width, height)，不含任务栏区域。"""
    rect = RECT()
    ok = ctypes.windll.user32.SystemParametersInfoW(
        SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
    )
    if not ok:
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        return 0, 0, w, h
    left, top = rect.left, rect.top
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    return left, top, width, height


def startup_folder() -> Path:
    appdata = os_environ_appdata()
    return Path(appdata) / r"Microsoft\Windows\Start Menu\Programs\Startup"


def os_environ_appdata() -> str:
    import os

    return os.environ.get("APPDATA") or str(Path.home())


def startup_shortcut_path() -> Path:
    return startup_folder() / "DesktopTidy.lnk"


def _escape_ps_single(s: str) -> str:
    return s.replace("'", "''")


def resolve_launch_target() -> tuple[str, str, str]:
    """
    返回 (TargetPath, Arguments, WorkingDirectory)，用于创建开机启动快捷方式。
    """
    import os

    cwd = str(Path(__file__).resolve().parent)
    if getattr(sys, "frozen", False):
        exe = str(Path(sys.executable).resolve())
        return exe, "", cwd
    py_exe = Path(sys.executable).resolve()
    pythonw = py_exe.parent / "pythonw.exe"
    launcher = str(pythonw if pythonw.is_file() else py_exe)
    script = str(Path(__file__).resolve().parent / "main.py")
    return launcher, f'"{script}"', cwd


def is_startup_enabled() -> bool:
    return startup_shortcut_path().is_file()


def set_startup_enabled(want: bool) -> tuple[bool, str]:
    """创建或删除「启动」文件夹中的快捷方式。"""
    path = startup_shortcut_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not want:
        try:
            if path.is_file():
                path.unlink()
            return True, "已关闭开机启动。"
        except OSError as e:
            return False, str(e)

    target, args, workdir = resolve_launch_target()
    t = _escape_ps_single(target)
    a = _escape_ps_single(args)
    w = _escape_ps_single(workdir)
    sp = _escape_ps_single(str(path))
    ps = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{sp}'); "
        f"$sc.TargetPath = '{t}'; "
        f"$sc.Arguments = '{a}'; "
        f"$sc.WorkingDirectory = '{w}'; "
        f"$sc.Save()"
    )
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return True, "已启用开机启动（当前用户启动文件夹）。"
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or "").strip() or str(e)
        return False, err
