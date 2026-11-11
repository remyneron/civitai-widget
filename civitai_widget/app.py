"""Application entry point: platform setup, logging, single-instance guard."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from civitai_widget import __version__, config


def _setup_platform() -> None:
    # A desktop widget has to remember its position and stay on top, which native Wayland
    # windows cannot do on GNOME. Prefer XWayland there, but never override an explicit choice.
    if "QT_QPA_PLATFORM" not in os.environ and os.environ.get("XDG_SESSION_TYPE") == "wayland":
        if os.environ.get("DISPLAY"):
            os.environ["QT_QPA_PLATFORM"] = "xcb"


def _setup_logging(debug: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        directory = config.state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(directory / "widget.log", maxBytes=200_000, backupCount=1, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=config.APP_ID, description="Trending AI art from Civitai on your desktop.")
    parser.add_argument("--version", action="version", version=f"{config.APP_ID} {__version__}")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    args, qt_args = parser.parse_known_args(sys.argv[1:] if argv is None else argv)

    _setup_platform()
    _setup_logging(args.debug)

    from PySide6.QtGui import QFont
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from civitai_widget import icons, styles
    from civitai_widget.window import CivitaiWindow

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(config.APP_ID)
    app.setApplicationDisplayName("Civitai Widget")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(config.APP_ID)
    app.setWindowIcon(icons.app_icon())
    app.setQuitOnLastWindowClosed(False)  # the widget can be hidden to the tray
    font = QFont()
    font.setFamilies(styles.FONT_FAMILIES)
    font.setPointSize(10)
    app.setFont(font)

    # Single instance: a second launch just brings the running widget to the front.
    server_name = f"{config.APP_ID}-{os.getuid()}"
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return 0
    QLocalServer.removeServer(server_name)  # stale socket left by a crash
    server = QLocalServer()
    server.listen(server_name)

    window = CivitaiWindow()

    def on_new_connection() -> None:
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.disconnected.connect(connection.deleteLater)
        window.bring_to_front()

    server.newConnection.connect(on_new_connection)
    window.show()
    code = app.exec()
    server.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
