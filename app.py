#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PyQt5 import QtCore
from PyQt5 import QtWidgets

import sys
import signal

from ui.views.main_styled import MainWindow


def run():

    # Set some application settings for QSettings
    QtCore.QCoreApplication.setOrganizationName("RustDaVinci")
    QtCore.QCoreApplication.setApplicationName("RustDaVinci")

    # Setup the application and start
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet("""
        * {
            color: #FFFFFF;
        }
        QWidget {
            background-color: #1E1E1E;
        }
        QLabel, QCheckBox, QRadioButton, QGroupBox, QTabBar::tab, QMenu, QMenuBar, QStatusBar {
            color: #FFFFFF;
        }
        QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QComboBox, QSpinBox, QTabWidget::pane {
            background-color: #2A2A2A;
            color: #FFFFFF;
            border: 1px solid #4A4A4A;
            selection-background-color: #4A90E2;
            selection-color: #FFFFFF;
        }
        QMessageBox, QMessageBox QWidget, QMessageBox QLabel, QMessageBox QTextEdit, QMessageBox QAbstractButton {
            background-color: #1E1E1E;
            color: #FFFFFF;
        }
        QMessageBox QPushButton {
            min-width: 90px;
            min-height: 28px;
            color: #FFFFFF;
            background-color: #333333;
            border: 1px solid #5A5A5A;
        }
    """)

    # Allow Ctrl+C in терминале to close the app gracefully
    def handle_sigint(signum, frame):
        app.quit()

    signal.signal(signal.SIGINT, handle_sigint)
    
    # Добавляем таймер для обработки Ctrl+C в Windows
    timer = QtCore.QTimer()
    timer.start(500)  # Проверяем каждые 500мс
    timer.timeout.connect(lambda: None)  # Позволяет Python обрабатывать сигналы

    main = MainWindow()
    main.show()

    exit_code = app.exec_()
    sys.exit(exit_code)


if __name__ == "__main__":
    run()
