import sys

from PySide6.QtWidgets import QApplication

from jarvis_os.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("J.A.R.V.I.S. OS")
    app.setApplicationVersion("0.1.0")
    window = MainWindow()
    window.showFullScreen()
    return app.exec()
