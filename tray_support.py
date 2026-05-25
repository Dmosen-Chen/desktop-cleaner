"""系统托盘（可选）：需要 pip install pystray pillow"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

try:
    import pystray
    from PIL import Image, ImageDraw

    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False


def tray_supported() -> bool:
    return TRAY_AVAILABLE


def _build_icon_image():
    img = Image.new("RGBA", (64, 64), (40, 110, 210, 255))
    draw = ImageDraw.Draw(img)
    try:
        draw.rounded_rectangle(
            [10, 10, 54, 54], radius=8, outline=(255, 255, 255, 255), width=3
        )
    except AttributeError:
        draw.rectangle([10, 10, 54, 54], outline=(255, 255, 255, 255), width=3)
    draw.rectangle([22, 22, 42, 42], outline=(230, 240, 255, 200), width=2)
    return img


def start_tray(
    *,
    title: str,
    on_open: Callable[[], None],
    on_organize: Callable[[], None],
    on_toggle_overlay: Callable[[], None],
    on_toggle_startup: Callable[[], None],
    on_quit: Callable[[], None],
    overlay_checked: Callable[[], bool],
    startup_checked: Callable[[], bool],
) -> Optional[Any]:
    if not TRAY_AVAILABLE:
        return None

    icon_img = _build_icon_image()

    menu = pystray.Menu(
        pystray.MenuItem("打开主窗口", lambda: on_open()),
        pystray.MenuItem("一键整理桌面", lambda: on_organize()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "显示桌面工作区",
            lambda: on_toggle_overlay(),
            checked=lambda item: overlay_checked(),
        ),
        pystray.MenuItem(
            "开机自动启动",
            lambda: on_toggle_startup(),
            checked=lambda item: startup_checked(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", lambda: on_quit()),
    )

    icon = pystray.Icon("desktop_tidy", icon_img, title, menu)

    def run_icon() -> None:
        icon.run()

    threading.Thread(target=run_icon, daemon=True).start()
    return icon
