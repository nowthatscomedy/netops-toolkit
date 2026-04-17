from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.app_state import AppState
from app.main_window import MainWindow
from app.version import __version__


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("NetOps Toolkit")
    app.setOrganizationName("NetOps Toolkit")
    app.setApplicationVersion(__version__)

    state = AppState()
    window = MainWindow(state)
    window.show()

    if not state.paths.config_dir.exists():
        QMessageBox.warning(
            window,
            "Config Error",
            "Configuration directory could not be initialized. Some features may be unavailable.",
        )

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
