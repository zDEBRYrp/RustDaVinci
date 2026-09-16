#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PyQt5.QtCore import QRect, QSettings, QSize, Qt
from PyQt5.QtGui import QPixmap, QImage, QPalette, QBrush, QFont, QIcon
from PyQt5.QtWidgets import (
    QLabel, QFrame, QMainWindow, QPushButton, QFileDialog, 
    QMessageBox, QApplication, QLineEdit, QCheckBox, QSpinBox,
    QComboBox, QTextEdit, QProgressBar
)

from PIL import Image
from pathlib import Path
import numpy


def _pil_to_qimage(image):
    """PIL Image -> QImage без временных файлов.

    Pillow >= 10 строит ImageQt только под Qt6, поэтому конвертируем
    вручную через RGBA-буфер. .copy() отвязывает QImage от bytes.
    """
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, QImage.Format_RGBA8888)
    return qimage.copy()

from ui.settings.settings import Settings
from lib.rustDaVinci import rustDaVinci
from ui.dialogs.brush_coords.brush_coords import BrushCoordsDialog

try:
    import ui.resources.icons_rc
except ImportError:
    pass  # Icons resource file not found, will use file paths instead

class MainWindow(QMainWindow):

    def __init__(self, parent=None):
        """ Main window init """
        super(MainWindow, self).__init__(parent)

        # Setup settings object
        self.settings = QSettings()

        # Setup rustDaVinci object
        self.rustDaVinci = rustDaVinci(self)

        # Setup UI
        self.setupUI()

        # Лимит цветов — общая настройка с движком: восстановить в спинбокс.
        try:
            saved_max_colors = int(self.settings.value("paint_max_colors", 0))
        except (TypeError, ValueError):
            saved_max_colors = 0
        self.maxColors_SpinBox.setValue(max(0, min(saved_max_colors, 256)))

        # Connect UI modules
        self.connectAll()

        # Update the rustDaVinci module
        self.rustDaVinci.update()


    def setupUI(self):
        """ Setup the UI with GarticBot style """
        self.setWindowTitle("RustDaVinci")
        self.setFixedSize(390, 590)
        
        # Установить иконку
        icon_path = Path(__file__).resolve().parents[2] / "ui" / "resources" / "icons" / "RustDaVinci-icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Тёмная тема окна.
        self.setStyleSheet("background-color: #2B2B2B;")
        
        # URL поле
        self.imageUrl_LineEdit = QLineEdit(self)
        self.imageUrl_LineEdit.setGeometry(10, 10, 370, 32)
        self.imageUrl_LineEdit.setPlaceholderText("Введите URL картинки...")
        self.imageUrl_LineEdit.setStyleSheet("""
            QLineEdit {
                border: 2px solid #4A90E2;
                border-radius: 5px;
                padding: 5px;
                background: white;
                color: #222;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 2px solid #5BA3F5;
                background: #FAFAFA;
            }
        """)
        
        # Кнопки загрузки
        btn_style = """
            QPushButton {
                background-color: #4A90E2;
                color: white;
                border: 2px solid #357ABD;
                border-radius: 5px;
                font-weight: bold;
                font-size: 11px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #5BA3F5;
                border: 2px solid #4A90E2;
            }
            QPushButton:pressed {
                background-color: #357ABD;
            }
        """
        
        self.loadFromUrl_PushButton = QPushButton("URL", self)
        self.loadFromUrl_PushButton.setGeometry(10, 50, 40, 32)
        self.loadFromUrl_PushButton.setStyleSheet(btn_style)
        self.loadFromUrl_PushButton.setToolTip("Загрузить из URL")
        
        self.loadFromFile_PushButton = QPushButton("FILE", self)
        self.loadFromFile_PushButton.setGeometry(56, 50, 40, 32)
        self.loadFromFile_PushButton.setStyleSheet(btn_style)
        self.loadFromFile_PushButton.setToolTip("Загрузить из файла")
        
        self.loadFromClipboard_PushButton = QPushButton("CLIP", self)
        self.loadFromClipboard_PushButton.setGeometry(102, 50, 40, 32)
        self.loadFromClipboard_PushButton.setStyleSheet(btn_style)
        self.loadFromClipboard_PushButton.setToolTip("Загрузить из буфера обмена")
        
        # Кнопка "Поверх окон"
        self.onTop_PushButton = QPushButton("Поверх окон", self)
        self.onTop_PushButton.setGeometry(260, 50, 120, 32)
        self.onTop_PushButton.setCheckable(True)
        self.onTop_PushButton.setStyleSheet("""
            QPushButton {
                background-color: #666;
                color: white;
                border: 2px solid #555;
                border-radius: 5px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:checked {
                background-color: #4CAF50;
                border: 2px solid #45A049;
            }
            QPushButton:hover {
                background-color: #777;
            }
            QPushButton:checked:hover {
                background-color: #5BC05F;
            }
        """)
        
        # Общий стиль для кнопок-чекбоксов
        checkbox_button_style = """
            QPushButton {
                background-color: #666;
                color: white;
                border: 2px solid #555;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10px;
                text-align: left;
                padding-left: 5px;
            }
            QPushButton:checked {
                background-color: #4A90E2;
                border: 2px solid #357ABD;
            }
            QPushButton:hover {
                background-color: #777;
            }
            QPushButton:checked:hover {
                background-color: #5BA3F5;
            }
        """
        
        # Кнопка режима одного цвета (как чекбокс)
        self.blackwhite_CheckBox = QPushButton("☐ РЕЖИМ ОДНОГО ЦВЕТА", self)
        self.blackwhite_CheckBox.setGeometry(10, 90, 220, 28)
        self.blackwhite_CheckBox.setCheckable(True)
        self.blackwhite_CheckBox.setStyleSheet(checkbox_button_style)
        # Подключаем обработчик для скрытия/показа поля цветов
        self.blackwhite_CheckBox.clicked.connect(self.on_blackwhite_changed)
        self.blackwhite_CheckBox.clicked.connect(self.update_button_text)
        
        # Кнопка пропуска фонового цвета (под режимом одного цвета)
        self.skipBackground_CheckBox = QPushButton("☑ ПРОПУСКАТЬ ФОН", self)
        self.skipBackground_CheckBox.setGeometry(10, 123, 220, 28)
        self.skipBackground_CheckBox.setCheckable(True)
        self.skipBackground_CheckBox.setChecked(True)  # По умолчанию включено
        self.skipBackground_CheckBox.setStyleSheet(checkbox_button_style)
        self.skipBackground_CheckBox.clicked.connect(self.update_button_text)
        
        # Лейбл и спинбокс цветов
        self.label_colors = QLabel("Цвета:", self)
        self.label_colors.setGeometry(10, 158, 60, 20)
        self.label_colors.setStyleSheet("color: white; font-weight: bold; font-size: 12px; background: transparent;")
        
        self.maxColors_SpinBox = QSpinBox(self)
        self.maxColors_SpinBox.setGeometry(70, 156, 60, 24)
        self.maxColors_SpinBox.setRange(0, 256)  # 0 = авто
        self.maxColors_SpinBox.setValue(0)  # По умолчанию авто
        self.maxColors_SpinBox.setSpecialValueText("Авто")  # Показывать "Авто" вместо 0
        self.maxColors_SpinBox.setStyleSheet("""
            QSpinBox {
                border: 2px solid #4A90E2;
                border-radius: 3px;
                padding: 2px;
                background: white;
                color: #222;
                font-weight: bold;
            }
            QSpinBox:focus {
                border: 2px solid #5BA3F5;
            }
        """)
        
        # Кнопка для установки координат HEX кода
        self.hexCoords_PushButton = QPushButton("Координаты HEX", self)
        self.hexCoords_PushButton.setGeometry(140, 156, 120, 28)
        self.hexCoords_PushButton.setStyleSheet(btn_style)
        self.hexCoords_PushButton.setToolTip("Установить координаты поля HEX кода")
        
        # Кнопка настроек
        self.settings_PushButton = QPushButton("Настройки", self)
        self.settings_PushButton.setGeometry(260, 90, 120, 32)
        self.settings_PushButton.setStyleSheet(btn_style)

        # Кнопка захвата панели: авто (OpenCV) / вручную (2 клика)
        self.captureCtrlAuto_PushButton = QPushButton("Панель: авто", self)
        self.captureCtrlAuto_PushButton.setGeometry(260, 123, 120, 28)
        self.captureCtrlAuto_PushButton.setStyleSheet(btn_style)
        self.captureCtrlAuto_PushButton.setToolTip("Найти панель инструментов через OpenCV")

        self.captureCtrlManual_PushButton = QPushButton("Панель: вручную", self)
        self.captureCtrlManual_PushButton.setGeometry(260, 156, 120, 28)
        self.captureCtrlManual_PushButton.setStyleSheet(btn_style)
        self.captureCtrlManual_PushButton.setToolTip("Указать панель двумя кликами")
        
        # Область предпросмотра
        self.preview_Label = QLabel("Предпросмотр", self)
        self.preview_Label.setGeometry(10, 190, 370, 240)
        self.preview_Label.setFrameShape(QFrame.Panel)
        self.preview_Label.setFrameShadow(QFrame.Sunken)
        self.preview_Label.setAlignment(Qt.AlignCenter)
        self.preview_Label.setStyleSheet("""
            QLabel {
                background-color: #1A1A1A;
                color: #888;
                border: 3px solid #4A90E2;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        
        # Прогресс-бар
        self.progress_ProgressBar = QProgressBar(self)
        self.progress_ProgressBar.setGeometry(10, 435, 370, 10)
        self.progress_ProgressBar.setValue(0)
        self.progress_ProgressBar.setTextVisible(False)
        self.progress_ProgressBar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #4A90E2;
                background-color: #E0E0E0;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)
        
        # Кнопка начать рисование
        self.paint_image_PushButton = QPushButton("НАЧАТЬ РИСОВАНИЕ", self)
        self.paint_image_PushButton.setGeometry(10, 450, 370, 45)
        self.paint_image_PushButton.setEnabled(False)
        self.paint_image_PushButton.setStyleSheet("""
            QPushButton {
                background-color: #E74C3C;
                color: white;
                border: 3px solid #C0392B;
                border-radius: 8px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover:enabled {
                background-color: #FF5744;
                border: 3px solid #E74C3C;
            }
            QPushButton:pressed:enabled {
                background-color: #C0392B;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
                border: 3px solid #444;
            }
        """)
        
        # Лог
        self.log_TextEdit = QTextEdit(self)
        self.log_TextEdit.setGeometry(10, 505, 370, 70)
        self.log_TextEdit.setReadOnly(True)
        self.log_TextEdit.setStyleSheet("""
            QTextEdit {
                background-color: #F5F5F5;
                color: #222;
                border: 2px solid #4A90E2;
                border-radius: 5px;
                padding: 5px;
                font-size: 11px;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)


    def connectAll(self):
        """ Connect all the buttons """
        self.loadFromUrl_PushButton.clicked.connect(self.load_image_URL_clicked)
        self.loadFromFile_PushButton.clicked.connect(self.load_image_file_clicked)
        self.loadFromClipboard_PushButton.clicked.connect(self.load_image_clipboard_clicked)
        
        self.onTop_PushButton.clicked.connect(self.on_top_clicked)
        self.settings_PushButton.clicked.connect(self.settings_clicked)
        self.captureCtrlAuto_PushButton.clicked.connect(self.capture_ctrl_auto_clicked)
        self.captureCtrlManual_PushButton.clicked.connect(self.capture_ctrl_manual_clicked)
        self.paint_image_PushButton.clicked.connect(self.paint_image_clicked)
        self.hexCoords_PushButton.clicked.connect(self.hex_coords_clicked)
        
        # Подключаем обновление предпросмотра при изменении параметров
        self.maxColors_SpinBox.valueChanged.connect(self.on_max_colors_changed)
        self.blackwhite_CheckBox.clicked.connect(self.on_preview_settings_changed)
        self.skipBackground_CheckBox.clicked.connect(self.on_preview_settings_changed)

    def on_max_colors_changed(self, value):
        """Лимит цветов — общая настройка: persist + превью."""
        self.settings.setValue("paint_max_colors", int(value))
        self.on_preview_settings_changed()


    def on_preview_settings_changed(self):
        """ Обработчик изменения настроек предпросмотра """
        if self.rustDaVinci.org_img is not None:
            self.update_preview()


    def update_button_text(self):
        """ Обновить текст кнопок-чекбоксов с символами ☐/☑ """
        # Обновить текст кнопки режима одного цвета
        if self.blackwhite_CheckBox.isChecked():
            self.blackwhite_CheckBox.setText("☑ РЕЖИМ ОДНОГО ЦВЕТА")
        else:
            self.blackwhite_CheckBox.setText("☐ РЕЖИМ ОДНОГО ЦВЕТА")
        
        # Обновить текст кнопки пропуска фона
        if self.skipBackground_CheckBox.isChecked():
            self.skipBackground_CheckBox.setText("☑ ПРОПУСКАТЬ ФОН")
        else:
            self.skipBackground_CheckBox.setText("☐ ПРОПУСКАТЬ ФОН")


    def on_blackwhite_changed(self):
        """ Обработчик изменения кнопки режима одного цвета """
        if self.blackwhite_CheckBox.isChecked():
            # Скрыть поле выбора цветов в режиме одного цвета
            self.label_colors.hide()
            self.maxColors_SpinBox.hide()
        else:
            # Показать поле выбора цветов в цветном режиме
            self.label_colors.show()
            self.maxColors_SpinBox.show()


    def _after_image_loaded(self, log_text=None):
        """После загрузки: кнопку решает движок, превью — по настройке."""
        if log_text:
            self.log_TextEdit.append(log_text)

    def load_image_file_clicked(self):
        """ Load image from file """
        self.rustDaVinci.load_image_from_file()
        self._after_image_loaded()

    def load_image_URL_clicked(self):
        """ Load image from URL """
        url = self.imageUrl_LineEdit.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Введите URL изображения")
            return

        self.rustDaVinci.load_image_from_url(url)
        self._after_image_loaded()


    def load_image_clipboard_clicked(self):
        """ Load image from clipboard """
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        
        if mime_data.hasImage():
            qimage = clipboard.image()
            if not qimage.isNull():
                # QImage -> PIL без временных файлов.
                buffer = qimage.convertToFormat(qimage.Format_RGBA8888)
                width, height = buffer.width(), buffer.height()
                ptr = buffer.bits()
                ptr.setsize(width * height * 4)
                pil_image = Image.frombuffer("RGBA", (width, height), ptr, "raw", "RGBA", 0, 1).copy()

                self.rustDaVinci.org_img_template = pil_image.convert("RGBA")
                self.rustDaVinci.org_img = self.rustDaVinci.org_img_template.copy()

                # Создаем pixmap
                self.rustDaVinci.org_img_pixmap = QPixmap.fromImage(qimage)

                self.rustDaVinci.convert_transparency()
                self.rustDaVinci.org_img_ok = True
                self.rustDaVinci.update()

                self._after_image_loaded("Изображение загружено из буфера обмена")
            else:
                QMessageBox.warning(self, "Ошибка", "Буфер обмена не содержит изображение")
        else:
            QMessageBox.warning(self, "Ошибка", "Буфер обмена не содержит изображение")


    def update_preview(self):
        """ Update preview image with all settings applied (numpy, без циклов)."""
        if not self.rustDaVinci.org_img:
            return

        try:
            # Настройки превью — локальные для окна (движок их не читает).
            blackwhite_mode = self.blackwhite_CheckBox.isChecked()
            skip_background = self.skipBackground_CheckBox.isChecked()
            max_colors = self.maxColors_SpinBox.value()

            # Создаем копию изображения для обработки
            preview_img = self.rustDaVinci.org_img.copy()

            if blackwhite_mode:
                # Режим одного цвета - конвертируем в ч/б
                gray = preview_img.convert("L")
                arr = numpy.asarray(gray)
                bw = numpy.where(arr < 128, 0, 255).astype("uint8")
                preview_img = Image.fromarray(bw, mode="L").convert("RGB")

                # Если включен пропуск фона, делаем белый цвет прозрачным
                if skip_background:
                    rgba = preview_img.convert("RGBA")
                    data = numpy.asarray(rgba)
                    mask = (data[..., 0] == 255) & (data[..., 1] == 255) & (data[..., 2] == 255)
                    data[mask, 3] = 0
                    preview_img = Image.fromarray(data, mode="RGBA")
            else:
                # Цветной режим - применяем квантизацию
                quantized = self.rustDaVinci.quantize_to_palette(preview_img, True, 0)

                if quantized:
                    if max_colors > 0:
                        colors = quantized.getcolors(maxcolors=quantized.width * quantized.height) or []
                        if len(colors) > max_colors:
                            colors.sort(key=lambda item: item[0], reverse=True)

                            bg_color_idx = colors[0][1] if skip_background else None
                            selected_colors = []
                            for _count, idx in colors:
                                if skip_background and idx == bg_color_idx:
                                    continue
                                selected_colors.append(idx)
                                if len(selected_colors) >= max_colors:
                                    break
                            if not selected_colors:
                                selected_colors = [colors[0][1]]

                            idx_arr = numpy.asarray(quantized)
                            keep = numpy.isin(idx_arr, numpy.asarray(selected_colors))
                            idx_arr = numpy.where(keep, idx_arr, selected_colors[0])
                            palette = self.rustDaVinci.palette_data.getpalette()
                            quantized = Image.fromarray(idx_arr.astype("uint8"), mode="P")
                            quantized.putpalette(palette)

                    if skip_background:
                        colors = quantized.getcolors(maxcolors=quantized.width * quantized.height) or []
                        if colors:
                            bg_color_idx = max(colors, key=lambda item: item[0])[1]
                            quantized_rgb = quantized.convert("RGB")
                            rgb_arr = numpy.asarray(quantized_rgb)
                            idx_arr = numpy.asarray(quantized)
                            bg_mask = idx_arr == bg_color_idx
                            bg_rgb = tuple(int(v) for v in rgb_arr[bg_mask][0]) if numpy.any(bg_mask) else (255, 255, 255)
                            rgba = quantized_rgb.convert("RGBA")
                            rgba_arr = numpy.asarray(rgba)
                            hit = (rgb_arr[..., 0] == bg_rgb[0]) & (rgb_arr[..., 1] == bg_rgb[1]) & (rgb_arr[..., 2] == bg_rgb[2])
                            rgba_arr[hit, 3] = 0
                            preview_img = Image.fromarray(rgba_arr, mode="RGBA")
                        else:
                            preview_img = quantized.convert("RGB")
                    else:
                        preview_img = quantized.convert("RGB")
                else:
                    preview_img = self.rustDaVinci.org_img

            # PIL -> QPixmap без временных файлов.
            pixmap = QPixmap.fromImage(_pil_to_qimage(preview_img))

            # Масштабируем для отображения
            scaled_pixmap = pixmap.scaled(
                370, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.preview_Label.setPixmap(scaled_pixmap)

        except Exception:
            # В случае ошибки показываем оригинальное изображение
            if self.rustDaVinci.org_img_pixmap:
                pixmap = self.rustDaVinci.org_img_pixmap.scaled(
                    370, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.preview_Label.setPixmap(pixmap)


    def on_top_clicked(self):
        """ Toggle window on top """
        if self.onTop_PushButton.isChecked():
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()


    def hex_coords_clicked(self):
        """ Open dialog to set HEX field coordinates """
        dialog = BrushCoordsDialog(self)
        dialog.exec_()


    def paint_image_clicked(self):
        """ Start the painting process """
        # Лимит цветов превью — единственный общий ключ с движком.
        max_colors = self.maxColors_SpinBox.value()
        self.settings.setValue("paint_max_colors", max_colors)

        self.rustDaVinci.start_painting()

    def capture_ctrl_auto_clicked(self):
        """Автопоиск панели инструментов через OpenCV."""
        self.rustDaVinci.locate_control_area_automatically()

    def capture_ctrl_manual_clicked(self):
        """Ручной захват панели двумя кликами."""
        self.rustDaVinci.locate_control_area_manually()

    def settings_clicked(self):
        """ Create an instance of a settings window """
        settings = Settings(self)
        settings.exec_()


    def show(self):
        """ Show the main window """
        super(MainWindow, self).show()


    def hide(self):
        """ Hide the main window """
        super(MainWindow, self).hide()
