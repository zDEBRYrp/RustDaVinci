#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap, QPainter, QColor
from PyQt5.QtWidgets import (
    QDialog,
    QApplication,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from PyQt5.QtCore import QSettings

import pyautogui
import time


class _ClickableLabel(QLabel):
    """QLabel, которая пробрасывает клик наружу по изображению."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._click_callback = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(QSize(800, 450))
        self.setScaledContents(False)
        self.setFrameShape(QLabel.Panel)
        self.setFrameShadow(QLabel.Sunken)
        self.setStyleSheet("background-color: #202020; color: #AAAAAA;")
        self.setText(
            "Сделайте скриншот игровой палитры (PrintScreen),\n"
            "затем нажмите «Вставить фото» и кликните по точкам."
        )

    def set_click_callback(self, callback):
        self._click_callback = callback

    def mousePressEvent(self, event):
        if self._click_callback is None:
            return
        if self.pixmap() is None:
            return
        self._click_callback(
            event.pos(),
            self.size(),
            self.pixmap().size(),
        )


class BrushCoordsDialog(QDialog):
    """
    Окно настроек координат и значений кисти для внешней палитры.

    Позволяет:
    - задать координаты полей «Размер», «Интервал», «Прозрачность» и HEX;
      координаты берутся кликом по скриншоту, как в CoordinateSettings из GarticBot;
    - ввести нужные значения и по кнопке «Применить в игре» бот сам кликнет
      по указанным координатам и «напечатает» числа/HEX в активном окне.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Координаты кисти / HEX")
        self.settings = QSettings()
        self._current_point_key = None
        self._background_pixmap = None

        self._coord_edits = {}
        self._value_edits = {}
        self._marker_positions = {}

        self._init_ui()
        self._load_coords()

    # ---------------- UI ----------------

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # Координаты полей в игре
        coords_group = QGroupBox("Координаты полей в игре")
        coords_grid = QGridLayout()

        point_defs = [
            ("size", "Размер"),
            ("interval", "Интервал"),
            ("opacity", "Прозрачность"),
            ("hex", "HEX цвет"),
        ]

        for row, (key, label_text) in enumerate(point_defs):
            label = QLabel(label_text)
            select_btn = QPushButton("X")
            select_btn.setFixedWidth(26)
            x_edit = QLineEdit()
            x_edit.setPlaceholderText("X")
            x_edit.setFixedWidth(70)
            y_edit = QLineEdit()
            y_edit.setPlaceholderText("Y")
            y_edit.setFixedWidth(70)

            self._coord_edits[key] = {"x": x_edit, "y": y_edit}

            select_btn.clicked.connect(lambda _, k=key: self._on_select_point_clicked(k))

            coords_grid.addWidget(label, row, 0)
            coords_grid.addWidget(select_btn, row, 1)
            coords_grid.addWidget(x_edit, row, 2)
            coords_grid.addWidget(y_edit, row, 3)

        coords_group.setLayout(coords_grid)
        main_layout.addWidget(coords_group)

        # Скриншот палитры для выбора точек
        screenshot_group = QGroupBox("Скриншот палитры")
        screenshot_layout = QVBoxLayout()

        self._image_label = _ClickableLabel(self)
        self._image_label.set_click_callback(self._on_image_clicked)

        buttons_layout = QHBoxLayout()
        self._paste_btn = QPushButton("Вставить фото")
        buttons_layout.addWidget(self._paste_btn)
        buttons_layout.addStretch(1)

        self._paste_btn.clicked.connect(self._on_paste_clicked)

        screenshot_layout.addWidget(self._image_label)
        screenshot_layout.addLayout(buttons_layout)
        screenshot_group.setLayout(screenshot_layout)
        main_layout.addWidget(screenshot_group)

        # Кнопка сохранения координат
        save_layout = QHBoxLayout()
        save_layout.addStretch(1)
        self._save_btn = QPushButton("Сохранить координаты")
        self._save_btn.clicked.connect(self._on_save_clicked)
        save_layout.addWidget(self._save_btn)
        main_layout.addLayout(save_layout)

        # Значения, которые нужно установить
        values_group = QGroupBox("Значения для установки")
        values_grid = QGridLayout()

        value_defs = [
            ("size", "Размер"),
            ("interval", "Интервал"),
            ("opacity", "Прозрачность"),
            ("hex", "HEX цвет"),
        ]

        for row, (key, label_text) in enumerate(value_defs):
            value_label = QLabel(label_text + ":")
            edit = QLineEdit()
            self._value_edits[key] = edit
            values_grid.addWidget(value_label, row, 0)
            values_grid.addWidget(edit, row, 1)

        self._apply_btn = QPushButton("Применить в игре")
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        values_grid.addWidget(self._apply_btn, len(value_defs), 0, 1, 2)

        values_group.setLayout(values_grid)
        main_layout.addWidget(values_group)

        self.setLayout(main_layout)
        # большое окно для удобного выбора точек
        self.resize(900, 700)

    # ---------------- Settings helpers ----------------

    @property
    def _coord_keys(self):
        # соответствие логического имени и ключей в QSettings
        return {
            "size": ("brush_size_x", "brush_size_y"),
            "interval": ("brush_interval_x", "brush_interval_y"),
            "opacity": ("brush_opacity_x", "brush_opacity_y"),
            "hex": ("brush_hex_x", "brush_hex_y"),
        }

    def _load_coords(self):
        for key, (key_x, key_y) in self._coord_keys.items():
            x_val = self.settings.value(key_x, "0")
            y_val = self.settings.value(key_y, "0")
            self._coord_edits[key]["x"].setText(str(x_val))
            self._coord_edits[key]["y"].setText(str(y_val))
        value_keys = {"size": "brush_size", "interval": "brush_interval", "opacity": "brush_opacity"}
        value_defaults = {"size": "15", "interval": "0.01", "opacity": "1.0"}
        for key, setting_key in value_keys.items():
            saved = self.settings.value(setting_key, value_defaults[key])
            self._value_edits[key].setText("" if saved is None else str(saved))

    # ---------------- Coordinate selection ----------------

    def _on_select_point_clicked(self, key):
        """Активировать выбор точки по скриншоту (без скрытия окна)."""
        self._current_point_key = key
        self.setWindowTitle(f"Кликните по точке на скриншоте для: {key}")

    def _on_image_clicked(self, pos, label_size, pixmap_size):
        """Обработка клика по скриншоту, пересчёт в координаты экрана.

        Логика повторяет CoordinateSettings из GarticBot:
        1) переводим клик в координаты внутри изображения,
        2) масштабируем их к текущему размеру экрана.
        """
        if self._current_point_key is None:
            return
        if self._background_pixmap is None:
            return

        w_c = float(label_size.width()) if label_size.width() > 0 else 1.0
        h_c = float(label_size.height()) if label_size.height() > 0 else 1.0

        # координаты клика относительно QLabel
        label_w = w_c
        label_h = h_c

        scaled_w = float(pixmap_size.width()) if pixmap_size.width() > 0 else 1.0
        scaled_h = float(pixmap_size.height()) if pixmap_size.height() > 0 else 1.0

        # учёт отступов (картинка по центру внутри QLabel)
        offset_x = (label_w - scaled_w) / 2.0
        offset_y = (label_h - scaled_h) / 2.0

        x_in_scaled = pos.x() - offset_x
        y_in_scaled = pos.y() - offset_y

        if x_in_scaled < 0 or y_in_scaled < 0 or x_in_scaled > scaled_w or y_in_scaled > scaled_h:
            # кликнули вне изображения
            return

        # шаг 1 — координаты клика в системе координат оригинального скриншота
        orig_w = float(self._background_pixmap.width()) if self._background_pixmap.width() > 0 else 1.0
        orig_h = float(self._background_pixmap.height()) if self._background_pixmap.height() > 0 else 1.0

        x_in_image = (x_in_scaled / scaled_w) * orig_w
        y_in_image = (y_in_scaled / scaled_h) * orig_h

        # шаг 2 — экранные координаты (скриншот сделан с экрана 1:1)
        unscaled_x = int(x_in_image)
        unscaled_y = int(y_in_image)

        # сохраняем экранные координаты в поля
        edits = self._coord_edits.get(self._current_point_key)
        if edits:
            edits["x"].setText(str(unscaled_x))
            edits["y"].setText(str(unscaled_y))

        # и запоминаем положение маркера в координатах QLabel
        self._marker_positions[self._current_point_key] = (pos.x(), pos.y())
        self._refresh_image_with_markers()

        self._current_point_key = None
        self.setWindowTitle("Координаты кисти / HEX")

    # ---------------- Screenshot handling ----------------

    def _on_paste_clicked(self):
        """Взять скриншот из буфера обмена и отобразить."""
        clipboard = QApplication.clipboard()
        image = clipboard.image()
        if image.isNull():
            QMessageBox.warning(
                self,
                "Буфер обмена пуст",
                "В буфере обмена нет изображения.\n"
                "Сделайте скриншот (PrintScreen) и скопируйте его.",
            )
            return

        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            QMessageBox.warning(
                self,
                "Ошибка",
                "Не удалось прочитать изображение из буфера обмена.",
            )
            return

        self._background_pixmap = pixmap
        self._refresh_image_with_markers()

    def _refresh_image_with_markers(self):
        """Перерисовать скрин с точками, как в GarticBot."""
        if self._background_pixmap is None:
            self._image_label.setPixmap(QPixmap())
            return

        target_size = self._image_label.size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            scaled = self._background_pixmap
        else:
            scaled = self._background_pixmap.scaled(
                target_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )

        pix = QPixmap(scaled)
        painter = QPainter(pix)

        color_map = {
            "size": QColor(0, 255, 0),        # зелёный
            "interval": QColor(255, 255, 0),  # жёлтый
            "opacity": QColor(0, 255, 255),   # голубой
            "hex": QColor(255, 0, 0),         # красный
        }

        radius = 2
        for key, pos in self._marker_positions.items():
            if pos is None:
                continue
            cx, cy = pos
            painter.setBrush(color_map.get(key, QColor(255, 255, 255)))
            painter.setPen(QColor(0, 0, 0))
            painter.drawEllipse(int(cx) - radius, int(cy) - radius, radius * 2, radius * 2)

        painter.end()
        self._image_label.setPixmap(pix)

    # ---------------- Saving ----------------

    def _on_save_clicked(self):
        """Сохранить координаты в QSettings."""
        for key, (key_x, key_y) in self._coord_keys.items():
            edits = self._coord_edits[key]
            self.settings.setValue(key_x, edits["x"].text())
            self.settings.setValue(key_y, edits["y"].text())

        QMessageBox.information(self, "Сохранено", "Координаты успешно сохранены.")

    # ---------------- Automation ----------------

    @staticmethod
    def _safe_coord(value):
        try:
            if value is None:
                return 0
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, str):
                value = value.strip()
                if value == "":
                    return 0
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    def _coord_from_fields(self, coord_key):
        """Координаты из полей диалога (fallback — QSettings). (0,0) = не задано."""
        key_x, key_y = self._coord_keys[coord_key]
        edits = self._coord_edits.get(coord_key)
        x_txt = edits["x"].text().strip() if edits else ""
        y_txt = edits["y"].text().strip() if edits else ""
        if x_txt and y_txt:
            x = self._safe_coord(x_txt)
            y = self._safe_coord(y_txt)
        else:
            x = self._safe_coord(self.settings.value(key_x, 0))
            y = self._safe_coord(self.settings.value(key_y, 0))
        if x == 0 or y == 0:
            return None
        return x, y

    def _type_at_coord(self, coord_key, text, press_enter=False):
        """Кликнуть по координате и набрать текст руками (через typewrite).

        Используется для числовых полей (Размер, Интервал, Прозрачность).
        """
        if not text:
            return False

        point = self._coord_from_fields(coord_key)
        if point is None:
            return False
        x, y = point

        # Один клик с небольшой паузой для фокуса
        pyautogui.click(x, y)
        time.sleep(0.2)

        # гарантированно очищаем поле перед вводом,
        # чтобы HEX и числа не «сдвигались»
        try:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.05)
            pyautogui.press("backspace")
            time.sleep(0.1)
        except Exception:
            pass

        # просто печатаем текст, как будто руками
        pyautogui.typewrite(text)
        if press_enter:
            pyautogui.press("enter")
        return True

    def _type_hex_at_coord(self, text):
        """Специальный ввод HEX: клик -> Backspace -> typewrite (без Ctrl+A)."""
        if not text:
            return False
        text = text.strip().upper()

        point = self._coord_from_fields("hex")
        if point is None:
            return False
        x, y = point

        # Один клик по полю HEX
        pyautogui.click(x, y)
        time.sleep(0.2)

        # Удалить текущее значение
        try:
            pyautogui.press("backspace")
            time.sleep(0.1)
        except Exception:
            pass

        # Вписать HEX вручную
        pyautogui.typewrite(text)
        return True

    def _apply_brush_value(self, coord_key):
        """Применить числовое значение кисти (размер/интервал/прозрачность)."""
        text = self._value_edits[coord_key].text().strip().replace(",", ".")
        if not text:
            return True
        try:
            number = float(text)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Некорректное число: %s" % text)
            return False
        limits = {"size": (1, 100), "interval": (0.01, 1.0), "opacity": (0.01, 1.0)}
        minimum, maximum = limits[coord_key]
        if not minimum <= number <= maximum:
            QMessageBox.warning(
                self, "Ошибка",
                "Значение вне диапазона %s–%s: %s" % (minimum, maximum, text),
            )
            return False
        if self._type_at_coord(coord_key, text):
            self.settings.setValue({"size": "brush_size", "interval": "brush_interval", "opacity": "brush_opacity"}[coord_key], text)
            return True
        QMessageBox.warning(self, "Ошибка", "Сначала задайте координаты поля (кнопка X).")
        return False

    def _on_apply_clicked(self):
        """Применить значения кисти и HEX в игре."""
        for coord_key in ("size", "interval", "opacity"):
            if not self._apply_brush_value(coord_key):
                return
        hex_txt = self._value_edits["hex"].text().strip()
        if hex_txt:
            if hex_txt.startswith("#"):
                hex_txt = hex_txt[1:]
            if len(hex_txt) != 6 or any(c not in "0123456789ABCDEFabcdef" for c in hex_txt):
                QMessageBox.warning(self, "Ошибка", "HEX должен быть вида RRGGBB: %s" % hex_txt)
                return
            if not self._type_hex_at_coord(hex_txt):
                QMessageBox.warning(self, "Ошибка", "Сначала задайте координаты поля HEX (кнопка X).")


