"""XDG autostart entry management."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from civitai_widget import config


def entry_path() -> Path:
    return config.config_dir() / "autostart" / f"{config.APP_ID}.desktop"


def launcher_command() -> str:
    launcher = shutil.which(config.APP_ID) or str(Path.home() / ".local" / "bin" / config.APP_ID)
    if Path(launcher).exists():
        return launcher
    return f"{sys.executable} -m civitai_widget"


def is_enabled() -> bool:
    return entry_path().exists()


def set_enabled(enabled: bool) -> None:
    path = entry_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Civitai Widget\n"
        "Comment=Trending AI art from Civitai on your desktop\n"
        f"Exec={launcher_command()}\n"
        f"Icon={config.APP_ID}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )
