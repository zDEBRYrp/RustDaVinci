#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PyQt5.QtCore import QSettings, Qt, QRect, QDir, QThread, QObject, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QMessageBox, QInputDialog, QFileDialog, QApplication, QLabel

from pynput import keyboard
from PIL import Image

import urllib.request
import pyautogui
import datetime
import numpy
import time
import cv2
import os

from lib.rustPaletteData import rust_palette
from lib.captureArea import capture_area, capture_point
from lib.color_functions import hex_to_rgb, rgb_to_hex, closest_color
from ui.dialogs.captureDialog import CaptureAreaDialog
from ui.settings.default_settings import default_settings


def _pil_to_qimage(image):
    """PIL Image -> QImage без временных файлов (копия отвязана от bytes)."""
    from PyQt5.QtGui import QImage

    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    return QImage(data, rgba.width, rgba.height, QImage.Format_RGBA8888).copy()


def _pil_to_qpixmap(image):
    return QPixmap.fromImage(_pil_to_qimage(image))


class PaintingWorker(QThread):
    """Поток рисования: держит GUI отзывчивым, прогресс/лог — через сигналы."""

    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(int)
    aborted = pyqtSignal(int)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine

    def run(self):
        try:
            self.engine.paint_loop(
                on_progress=self.progress.emit,
                on_log=self.log.emit,
            )
            self.engine.shutdown_from_thread()
            if self.engine.abort:
                self.aborted.emit(int(time.time() - self.engine.paint_start_time))
            else:
                self.finished_ok.emit(int(time.time() - self.engine.paint_start_time))
        except Exception as exc:  # noqa: BLE001 - пробрасываем ошибку в лог GUI
            self.log.emit("Ошибка рисования: " + str(exc))
            self.aborted.emit(int(time.time() - self.engine.paint_start_time))


class _UiBridge(QObject):
    """QObject-посредник: сигналы воркера гарантированно идут в GUI-поток очередью."""

    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished_ok = pyqtSignal(int)
    aborted = pyqtSignal(int)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self.log.connect(engine._append_log, Qt.QueuedConnection)
        self.progress.connect(engine._set_progress, Qt.QueuedConnection)
        self.finished_ok.connect(lambda elapsed: engine.shutdown(engine.paint_listener, engine.paint_start_time, 0), Qt.QueuedConnection)
        self.aborted.connect(lambda elapsed: engine.shutdown(engine.paint_listener, engine.paint_start_time, 1), Qt.QueuedConnection)


class rustDaVinci():

    def __init__(self, parent):
        """ RustDaVinci class init """
        self.parent = parent
        self.settings = QSettings()

        # PIL.Image images original/ quantized
        self.org_img_template = None
        self.org_img = None
        self.quantized_img = None
        self.palette_data = None
        self.updated_palette = None

        # Pixmaps
        self.org_img_pixmap = None

        # Booleans
        self.org_img_ok = False
        self.use_double_click = False
        self.use_hidden_colors = False

        # Keyboard interrupt variables
        self.pause_key = None
        self.skip_key = None
        self.abort_key = None
        self.paused = False
        self.skip_current_color = False
        self.abort = False

        # Painting control tools
        self.ctrl_remove = 0
        self.ctrl_update = 0
        self.ctrl_size = []
        self.ctrl_brush = []
        self.ctrl_opacity = []
        self.ctrl_color = []
        self.current_ctrl_size = None
        self.current_ctrl_brush = None
        self.current_ctrl_opacity = None
        self.current_ctrl_color = None

        # Canvas coordinates/ ratio
        self.canvas_x = 0
        self.canvas_y = 0
        self.canvas_w = 0
        self.canvas_h = 0

        # Statistics
        self.img_colors = []
        self.tot_pixels = 0
        self.pixels = 0
        self.lines = 0
        self.estimated_time = 0

        # Delays
        self.click_delay = 0
        self.line_delay = 0
        self.ctrl_area_delay = 0
        self.use_double_click = False

        self.background_color = None
        self.skip_colors = None

        # Hotkey display QLabel
        self.hotkey_label = None

        # Флаг: использовать ли внешнее HEX-поле (координаты задаются в диалоге кисти)
        self.use_external_hex = False

        # Поток рисования и состояние цикла
        self.paint_thread = None
        self.ui_bridge = None
        self.paint_start_time = 0
        self.paint_listener = None
        self.prefer_lines = False

        # Init functions
        if not (self._setting_int("ctrl_w", default_settings["ctrl_w"]) == 0 or self._setting_int("ctrl_h", default_settings["ctrl_h"])):
            self.calculate_ctrl_tools_positioning()


    def update(self):
        """ Updates pyauogui delays, booleans and paint image button"""
        self.click_delay = float(self._setting_int("click_delay", default_settings["click_delay"]) / 1000)
        self.line_delay = float(self._setting_int("line_delay", default_settings["line_delay"]) / 1000)
        self.ctrl_area_delay = float(self._setting_int("ctrl_area_delay", default_settings["ctrl_area_delay"]) / 1000)
        self.use_double_click = self._setting_bool("double_click", default_settings["double_click"])

        # Update the pyautogui delay
        pyautogui.PAUSE = self.click_delay

        # External HEX palette is активен, если задано поле HEX
        hex_x = self._setting_int("brush_hex_x", 0)
        hex_y = self._setting_int("brush_hex_y", 0)
        self.use_external_hex = not (hex_x == 0 or hex_y == 0)

        if self._setting_int("ctrl_w", default_settings["ctrl_w"]) == 0 or self._setting_int("ctrl_h", default_settings["ctrl_h"]) == 0:
            self._set_widget_enabled("paint_image_PushButton", False)
        elif self.org_img_ok and self._setting_int("ctrl_w", default_settings["ctrl_w"]) != 0 and self._setting_int("ctrl_h", default_settings["ctrl_h"]) != 0:
            self._set_widget_enabled("paint_image_PushButton", True)


    def _get_widget(self, name):
        """Виджет из styled-окна (parent.*)."""
        if hasattr(self.parent, name):
            return getattr(self.parent, name)
        return None


    @staticmethod
    def _to_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
        return default

    def _setting_bool(self, name, default):
        return self._to_bool(self.settings.value(name, default), bool(default))

    def _setting_int(self, name, default):
        try:
            raw = self.settings.value(name, default)
            if isinstance(raw, bool):
                return int(raw)
            if isinstance(raw, str):
                raw = raw.strip()
                if raw == "":
                    return int(default)
            return int(float(raw)) if isinstance(raw, str) and "." in raw else int(raw)
        except (TypeError, ValueError):
            return int(default)

    def _set_widget_enabled(self, name, enabled):
        widget = self._get_widget(name)
        if widget is not None and hasattr(widget, "setEnabled"):
            widget.setEnabled(enabled)


    def _clear_log_and_progress(self):
        log = self._get_widget("log_TextEdit")
        progress = self._get_widget("progress_ProgressBar")
        if log is not None and hasattr(log, "clear"):
            log.clear()
        if progress is not None and hasattr(progress, "setValue"):
            progress.setValue(0)


    def _append_log(self, text):
        log = self._get_widget("log_TextEdit")
        if log is not None and hasattr(log, "append"):
            log.append(text)


    def _set_progress(self, value):
        progress = self._get_widget("progress_ProgressBar")
        if progress is not None and hasattr(progress, "setValue"):
            progress.setValue(value)


    def _set_main_controls_enabled(self, enabled):
        self._set_widget_enabled("loadFromFile_PushButton", enabled)
        self._set_widget_enabled("loadFromUrl_PushButton", enabled)
        self._set_widget_enabled("loadFromClipboard_PushButton", enabled)
        self._set_widget_enabled("captureCtrlAuto_PushButton", enabled)
        self._set_widget_enabled("captureCtrlManual_PushButton", enabled)
        self._set_widget_enabled("paint_image_PushButton", enabled)
        self._set_widget_enabled("settings_PushButton", enabled)


    def _style_error_box(self, msg):
        msg.setStyleSheet(
            "QMessageBox { background-color: #1E1E1E; }"
            "QLabel { color: #FFFFFF; }"
            "QTextEdit { color: #FFFFFF; background-color: #1E1E1E; border: none; }"
            "QPushButton { background-color: #333333; color: #FFFFFF; min-width: 80px; }"
        )


    def _show_preview_if_supported(self):
        """Show preview for the styled main window."""
        if hasattr(self.parent, "update_preview"):
            try:
                self.parent.update_preview()
            except Exception:
                pass


    def _set_image_loaded(self, template):
        """Общий финал загрузки: шаблон -> org_img -> превью. Кнопку решает update()."""
        self.org_img_template = template
        self.org_img = template.copy()
        self.org_img_pixmap = _pil_to_qpixmap(self.org_img)
        self.convert_transparency()
        self.org_img_ok = True
        if self._setting_bool("show_preview_load", default_settings["show_preview_load"]):
            self._show_preview_if_supported()
        self._clear_log_and_progress()

    def load_image_from_file(self):
        """ Load image from a file """
        title = "Выберите изображение для рисования"
        fileformats = "Изображения (*.png *.jpg *.jpeg *.gif *.bmp)"
        folder_path = self.settings.value("folder_path", QDir.homePath())
        folder_path = os.path.dirname(os.path.abspath(folder_path))
        if not os.path.exists(folder_path):
            folder_path = QDir.homePath()

        path = QFileDialog.getOpenFileName(self.parent, title, folder_path, fileformats)[0]

        if path.endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
            try:
                self.settings.setValue("folder_path", path)
                with Image.open(path) as opened:
                    template = opened.convert("RGBA")
                self._set_image_loaded(template)

            except Exception as e:
                self.org_img = None
                self.org_img_ok = False
                msg = QMessageBox(self.parent)
                msg.setIcon(QMessageBox.Critical)
                msg.setText("Ошибка! Не удалось загрузить выбранное изображение...")
                msg.setInformativeText(str(e))
                self._style_error_box(msg)
                msg.exec_()

        self.update()


    def load_image_from_url(self, url=None):
        """ Load image from url.

        Supports both call styles:
        - load_image_from_url()          -> asks URL via dialog
        - load_image_from_url(url_str)   -> uses provided URL
        """
        if url is None:
            dialog = QInputDialog(self.parent)
            dialog.setInputMode(QInputDialog.TextInput)
            dialog.setLabelText("Загрузить изображение по URL:")
            dialog.resize(500,100)
            ok_clicked = dialog.exec_()
            url = dialog.textValue()
            if not ok_clicked:
                return

        if isinstance(url, str):
            url = url.strip()

        if url != "":
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) RustDaVinci/1.0'}
                request = urllib.request.Request(url, None, headers)
                with urllib.request.urlopen(request, timeout=15) as response:
                    with Image.open(response) as opened:
                        opened.load()
                        template = opened.convert("RGBA")
                self._set_image_loaded(template)

            except Exception as e:
                self.org_img = None
                self.org_img_ok = False
                msg = QMessageBox(self.parent)
                msg.setIcon(QMessageBox.Critical)
                msg.setText("Ошибка! Не удалось загрузить выбранное изображение...")
                msg.setInformativeText(str(e))
                self._style_error_box(msg)
                msg.exec_()

        self.update()


    def convert_transparency(self):
        """ Paste the org_img on top of an image with background color """
        try:
            background_rgb = hex_to_rgb(self.settings.value("background_color", default_settings["background_color"]))
            background_rgb = closest_color(background_rgb)
        except (TypeError, ValueError):
            background_rgb = rust_palette[0]
        # Set transparency in image to default background
        try:
            self.org_img = self.org_img_template.copy()
            temp_org_img = Image.new("RGBA", self.org_img.size, color=background_rgb + (255,))
            temp_org_img.paste(self.org_img, (0, 0), mask=self.org_img)
            self.org_img = temp_org_img.convert("RGB")
        except Exception:
            self.org_img = self.org_img_template.convert("RGB")


    def convert_img(self):
        """ Convert the image to fit the canvas and quantize the image.
        Updates:    quantized_img,
                    x_correction,
                    y_correction
        Returns:    False, if the image type is invalid.
        """
        if self.org_img is None or self.canvas_w <= 0 or self.canvas_h <= 0:
            self.quantized_img = None
            self.org_img_ok = False
            return False
        org_img_w = self.org_img.size[0]
        org_img_h = self.org_img.size[1]

        wpercent = (self.canvas_w / float(org_img_w))
        hpercent = (self.canvas_h / float(org_img_h))

        hsize = int((float(org_img_h) * float(wpercent)))
        wsize = int((float(org_img_w) * float(hpercent)))

        x_correction = 0
        y_correction = 0

        # Use high-quality downsampling filter compatible with new Pillow
        try:
            resample_filter = Image.Resampling.LANCZOS
        except AttributeError:
            resample_filter = Image.LANCZOS

        if hsize <= self.canvas_h:
            resized_img = self.org_img.resize((self.canvas_w, hsize), resample_filter)
            y_correction = int((self.canvas_h - hsize)/2)
        elif wsize <= self.canvas_w:
            resized_img = self.org_img.resize((wsize, self.canvas_h), resample_filter)
            x_correction = int((self.canvas_w - wsize)/2)
        else:
            resized_img = self.org_img.resize((self.canvas_w, self.canvas_h), resample_filter)

        self.quantized_img = self.quantize_to_palette(resized_img)
        if self.quantized_img is None:
            self.org_img = None
            self.quantized_img = None
            self.org_img_ok = False
            return False

        self.canvas_x += x_correction
        self.canvas_y += y_correction
        self.canvas_w = self.quantized_img.size[0]
        self.canvas_h = self.quantized_img.size[1]
        return True


    def _background_rgb(self):
        """Фоновый цвет из настроек, привязанный к палитре Rust.

        hex_to_rgb падает на мусоре, а index — на цвете вне палитры,
        поэтому снаппим через closest_color. Используется и в
        update_palette, и в update_skip_colors, чтобы фон скипался
        консистентно.
        """
        try:
            raw = hex_to_rgb(self.settings.value("background_color", default_settings["background_color"]))
        except (TypeError, ValueError, AttributeError):
            raw = rust_palette[0]
        try:
            return closest_color(tuple(raw))
        except (TypeError, ValueError):
            return rust_palette[0]

    def update_palette(self, rgb_background):
        """Build the effective palette for quantize().

        Возвращает (palette_image, updated_palette, background_color).
        Состояние также дублируется в self для совместимости.

        Индексы фона для замены вычисляются по той же колоночной логике,
        что и update_skip_colors: столбец col = rust_index % 64,
        варианты прозрачности — col + 64*b (hidden) или b*64 + col
        для видимых столбцов (col < 20).
        """
        use_hidden_colors = self._setting_bool("hidden_colors", default_settings["hidden_colors"])
        use_brush_opacities = self._setting_bool("brush_opacities", default_settings["brush_opacities"])
        skip_background = self._setting_bool("skip_background_color", default_settings["skip_background_color"])

        try:
            rgb_background = closest_color(tuple(rgb_background))
        except (TypeError, ValueError):
            rgb_background = rust_palette[0]

        visible_count = 64 if use_hidden_colors else 20

        # rust_palette-индексы, которые заменяем фоновым цветом.
        # Видимая палитра использует записи [0..19] и opacity-блоки
        # [64..83], [128..147], [192..211]: столбец col = rust_index % 64
        # встречается в каждом блоке один раз (индексы start + col).
        # Hidden-палитра — col + 64*block.
        replace_idx = set()
        if skip_background and rgb_background in rust_palette:
            col = rust_palette.index(rgb_background) % 64
            if use_hidden_colors:
                if use_brush_opacities:
                    replace_idx = {col + 64 * block for block in range(4)}
                else:
                    replace_idx = {col}  # палитра — первые 64 записи
            elif col < 20:
                if use_brush_opacities:
                    # В эффективной палитре visible-блоки идут подряд:
                    # rust [0..19] -> позиции 0..19, [64..83] -> 20..39 и т.д.
                    # Цикл ниже идёт по rust_palette, поэтому заменяем
                    # rust-индексы (0, 64, 128, 192)[block] + col.
                    replace_idx = {(0, 64, 128, 192)[block_i] + col for block_i in range(4)}
                else:
                    replace_idx = {col}
            # Скрытый фон при видимой палитре: заменять нечего.

        # Select the palette to be used
        palette_image = Image.new("P", (1, 1))
        palette = ()
        updated_palette = []

        # Choose how many colors in the palette
        if use_hidden_colors:
            if use_brush_opacities:
                for i, color in enumerate(rust_palette):
                    if i in replace_idx:
                        palette = palette + rgb_background
                        updated_palette.append(rgb_background)
                    else:
                        palette = palette + color
                        updated_palette.append(color)
            else:
                for i, color in enumerate(rust_palette):
                    if i == 64:
                        palette = palette + (2, 2, 2) * 192
                        break
                    if i in replace_idx:
                        palette = palette + rgb_background
                        updated_palette.append(rgb_background)
                    else:
                        palette = palette + color
                        updated_palette.append(color)
        else:
            if use_brush_opacities:
                for i, color in enumerate(rust_palette):
                    if (i >= 0 and i <= 19) or (i >= 64 and i <= 83) or (i >= 128 and i <= 147) or (i >= 192 and i <= 211):
                        if i in replace_idx:
                            palette = palette + rgb_background
                            updated_palette.append(rgb_background)
                        else:
                            palette = palette + color
                            updated_palette.append(color)
                palette = palette + (2, 2, 2) * 176
            else:
                for i, color in enumerate(rust_palette):
                    if i == 20:
                        palette = palette + (2, 2, 2) * 236
                        break
                    if i in replace_idx:
                        palette = palette + rgb_background
                        updated_palette.append(rgb_background)
                    else:
                        palette = palette + color
                        updated_palette.append(color)


        if rgb_background in updated_palette:
            background_color = updated_palette.index(rgb_background) % visible_count
        else:
            background_color = None

        palette_image.putpalette(palette)

        self.palette_data = palette_image
        self.updated_palette = updated_palette
        self.background_color = background_color
        return palette_image, updated_palette, background_color


    def quantize_to_palette(self, image, pixmap=False, pixmap_q=0):
        """Convert an RGB/RGBA/L image to the Rust palette via Image.quantize().

        Не мутирует self.org_img: работает с копией. Возвращает P-изображение.
        """
        try:
            rgb = hex_to_rgb(self.settings.value("background_color", default_settings["background_color"]))
        except (TypeError, ValueError, AttributeError):
            rgb = rust_palette[0]
        palette_image, _, _ = self.update_palette(rgb)

        work = image.copy()
        work.load()
        if work.mode in ("RGBA", "LA"):
            background = Image.new("RGB", work.size, rgb)
            alpha = work.split()[-1]
            background.paste(work.convert("RGB"), mask=alpha)
            work = background
        elif work.mode != "RGB":
            work = work.convert("RGB")

        if not pixmap:
            quality = self._setting_int("quality", default_settings["quality"])
            dither = Image.Dither.FLOYDSTEINBERG if quality == 1 else Image.Dither.NONE
        else:
            dither = Image.Dither.FLOYDSTEINBERG if pixmap_q == 1 else Image.Dither.NONE

        return work.quantize(palette=palette_image, dither=dither)


    def clear_image(self):
        """ Clear the image """
        self.org_img = None
        self.quantized_img = None
        self.org_img_ok = False
        self.update()


    def locate_canvas_area(self):
        """ Locate the coordinates/ ratio of the canvas area.
        Updates:    self.canvas_x,
                    self.canvas_y,
                    self.canvas_w,
                    self.canvas_h
        """
        dialog = CaptureAreaDialog(self.parent, 0)
        ans = dialog.exec_()
        if ans == 0: return False

        self.parent.hide()
        canvas_area = capture_area()
        self.parent.show()

        if canvas_area == False:
            return False
        elif canvas_area[2] == 0 or canvas_area[3] == 0:
            msg = QMessageBox(self.parent)
            msg.setIcon(QMessageBox.Critical)
            msg.setText("Неверные координаты и соотношение. Перетащите от левого верхнего угла холста к правому нижнему.")
            msg.exec_()
            return False

        msg = QMessageBox(self.parent)
        msg.setIcon(QMessageBox.Information)
        msg.setText("Координаты:\n" +
                    "X =\t\t" + str(canvas_area[0]) + "\n" +
                    "Y =\t\t" + str(canvas_area[1]) + "\n" +
                    "Ширина =\t" + str(canvas_area[2]) + "\n" +
                    "Высота =\t" + str(canvas_area[3]))
        msg.exec_()

        self.canvas_x = canvas_area[0]
        self.canvas_y = canvas_area[1]
        self.canvas_w = canvas_area[2]
        self.canvas_h = canvas_area[3]
        return True


    def locate_control_area_manually(self):
        """Locate control area coordinates manually using two clicks (top-left and bottom-right)."""
        # Простая текстовая инструкция, без прямоугольника и перетаскивания
        msg = QMessageBox(self.parent)
        msg.setIcon(QMessageBox.Information)
        msg.setText(
            "Сейчас нужно указать область панели элементов управления.\n\n"
            "1) Кликните ЛКМ по ЛЕВОМУ ВЕРХНЕМУ углу панели.\n"
            "2) Затем кликните ЛКМ по ПРАВОМУ НИЖНЕМУ углу панели.\n\n"
            "Нажмите любую клавишу вместо клика, чтобы отменить."
        )
        msg.exec_()

        # Прячем окно приложения, чтобы не перекрывать область
        self.parent.hide()
        QApplication.processEvents()

        first = capture_point()
        if not first:
            self.parent.show()
            QApplication.processEvents()
            self.update()
            return False

        second = capture_point()
        self.parent.show()
        QApplication.processEvents()

        if not second:
            self.update()
            return False

        x1, y1 = first
        x2, y2 = second

        if x2 <= x1 or y2 <= y1:
            msg = QMessageBox(self.parent)
            msg.setIcon(QMessageBox.Critical)
            msg.setText(
                "Неверные координаты.\n"
                "Сначала кликните по левому верхнему, затем по правому нижнему углу панели."
            )
            msg.exec_()
            self.update()
            return False

        ctrl_area = (x1, y1, x2 - x1, y2 - y1)

        btn = QMessageBox.question(
            self.parent,
            None,
            "Координаты:\n"
            "X =\t\t" + str(ctrl_area[0]) + "\n"
            "Y =\t\t" + str(ctrl_area[1]) + "\n"
            "Ширина =\t" + str(ctrl_area[2]) + "\n"
            "Высота =\t" + str(ctrl_area[3]) + "\n\n"
            "Обновить координаты области элементов управления рисованием?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if btn == QMessageBox.Yes:
            self._append_log("Координаты области управления обновлены...")
            self.settings.setValue("ctrl_x", str(ctrl_area[0]))
            self.settings.setValue("ctrl_y", str(ctrl_area[1]))
            self.settings.setValue("ctrl_w", str(ctrl_area[2]))
            self.settings.setValue("ctrl_h", str(ctrl_area[3]))

        self.update()


    def locate_control_area_automatically(self):
        """"""
        self.parent.hide()
        ctrl_area = self.locate_control_area_opencv()
        self.parent.show()

        msg = QMessageBox(self.parent)
        if ctrl_area == False:
            msg.setIcon(QMessageBox.Critical)
            msg.setText("Не удалось автоматически найти область элементов управления... Попробуйте захватить её вручную.")
            msg.exec_()
        else:
            btn = QMessageBox.question(self.parent, None,
                "Координаты:\n" +
                "X =\t\t" + str(ctrl_area [0]) + "\n" +
                "Y =\t\t" + str(ctrl_area [1]) + "\n" +
                "Ширина =\t" + str(ctrl_area [2]) + "\n" +
                "Высота =\t" + str(ctrl_area [3]) + "\n\n" +
                "Обновить координаты области элементов управления рисованием?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if btn == QMessageBox.Yes:
                self._append_log("Координаты области управления обновлены...")
                self.settings.setValue("ctrl_x", str(ctrl_area[0]))
                self.settings.setValue("ctrl_y", str(ctrl_area[1]))
                self.settings.setValue("ctrl_w", str(ctrl_area[2]))
                self.settings.setValue("ctrl_h", str(ctrl_area[3]))

            self.update()


    def _screenshot_active_monitor(self):
        """Скриншот выбранного в настройках монитора (смещение = левый верхний угол)."""
        from PyQt5.QtWidgets import QApplication

        monitor_index = self._setting_int("monitor_index", 0)
        try:
            screens = QApplication.screens()
        except Exception:
            screens = []
        if not screens:
            return pyautogui.screenshot()
        monitor_index = max(0, min(monitor_index, len(screens) - 1))
        geometry = screens[monitor_index].geometry()
        shot = pyautogui.screenshot(region=(geometry.x(), geometry.y(), geometry.width(), geometry.height()))
        shot.monitor_offset = (geometry.x(), geometry.y())
        return shot

    @staticmethod
    def _to_absolute(point, screenshot):
        """Локальные координаты скриншота -> абсолютные экранные."""
        offset = getattr(screenshot, "monitor_offset", (0, 0))
        return point[0] + offset[0], point[1] + offset[1]

    def locate_control_area_opencv(self):
        """ Automatically tries to find the painting control area with opencv.
        Returns:    ctrl_x,
                    ctrl_y,
                    ctrl_w,
                    ctrl_h
                    False, if no control area was found
        """
        screenshot = self._screenshot_active_monitor()
        if screenshot is None:
            return False
        screen_w, screen_h = screenshot.size

        image_gray = cv2.cvtColor(numpy.array(screenshot), cv2.COLOR_BGR2GRAY)

        tmpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opencv_template", "rust_palette_template.png")
        tmpl = cv2.imread(tmpl_path, 0)
        if tmpl is None:
            return False
        tmpl_w, tmpl_h = tmpl.shape[::-1]

        x_coord, y_coord = 0, 0
        threshold = 0.8

        for loop in range(50):
            matches = cv2.matchTemplate(image_gray, tmpl, cv2.TM_CCOEFF_NORMED)
            loc = numpy.where(matches >= threshold)

            x_list, y_list = [], []
            for point in zip(*loc[::-1]):
                x_list.append(point[0])
                y_list.append(point[1])

            if x_list:
                x_coord = int(sum(x_list) / len(x_list))
                y_coord = int(sum(y_list) / len(y_list))
                abs_x, abs_y = self._to_absolute((x_coord, y_coord), screenshot)
                return abs_x, abs_y, tmpl_w, tmpl_h

            tmpl_w, tmpl_h = int(tmpl.shape[1]*1.035), int(tmpl.shape[0]*1.035)
            tmpl = cv2.resize(tmpl, (int(tmpl_w), int(tmpl_h)))

            if tmpl_w > screen_w or tmpl_h > screen_h or loop == 49: return False


    def calculate_ctrl_tools_positioning(self):
        """ This function calculates the positioning of the different controls in the painting control area.
        The brush size, type and opacity along with all the different colors.
        Updates:    self.ctrl_remove
                    self.ctrl_update
                    self.ctrl_size
                    self.ctrl_brush
                    self.ctrl_opacity
                    self.ctrl_color
        """
        # Reset
        self.ctrl_remove = 0
        self.ctrl_update = 0
        self.ctrl_size = []
        self.ctrl_brush = []
        self.ctrl_opacity = []
        self.ctrl_color = []

        ctrl_x = self._setting_int("ctrl_x", default_settings["ctrl_x"])
        ctrl_y = self._setting_int("ctrl_y", default_settings["ctrl_y"])
        ctrl_w = self._setting_int("ctrl_w", default_settings["ctrl_w"])
        ctrl_h = self._setting_int("ctrl_h", default_settings["ctrl_h"])

        # Calculate the distance between two items on a row of six items (Size)
        first_x_coord_of_six_v1 = ctrl_x + (ctrl_w/6.5454)
        second_x_coord_of_six_v1 = ctrl_x + (ctrl_w/3.4285)
        dist_btwn_x_coords_of_six_v1 = second_x_coord_of_six_v1 - first_x_coord_of_six_v1

        # Calculate the distance between two items on a row of six items (Opacity)
        first_x_coord_of_six_v2 = ctrl_x + (ctrl_w/7.5789)
        second_x_coord_of_six_v2 = ctrl_x + (ctrl_w/3.5555)
        dist_btwn_x_coords_of_six_v2 = second_x_coord_of_six_v2 - first_x_coord_of_six_v2

        # Calculate the distance between two items on a row of four items (Colors width)
        first_x_coord_of_four = ctrl_x + (ctrl_w/6)
        second_x_coord_of_four = ctrl_x + (ctrl_w/2.5714)
        dist_btwn_x_coords_of_four = second_x_coord_of_four - first_x_coord_of_four

        # Calculate the distance between two items on a column of eight items (Colors height)
        first_y_coord_of_eight = ctrl_y + (ctrl_h/2.3220)
        second_y_coord_of_eight = ctrl_y + (ctrl_h/1.9855)
        dist_btwn_y_coords_of_eight = second_y_coord_of_eight - first_y_coord_of_eight

        # Set the point location of the remove & update buttons
        self.ctrl_remove = ((ctrl_x + (ctrl_w/2.7692)), (ctrl_y + (ctrl_h/19.5714)))
        self.ctrl_update = ((ctrl_x + (ctrl_w/1.5652)), (ctrl_y + (ctrl_h/19.5714)))


        for size in range(6):
            self.ctrl_size.append((  first_x_coord_of_six_v1 +
                                     (size * dist_btwn_x_coords_of_six_v1),
                                     (ctrl_y + (ctrl_h/6.9661))))

        for brush in range(4):
            self.ctrl_brush.append(( first_x_coord_of_four +
                                     (brush * dist_btwn_x_coords_of_four),
                                     (ctrl_y + (ctrl_h/4.2371))))

        for opacity in range(6):
            self.ctrl_opacity.append((   first_x_coord_of_six_v2 +
                                         (opacity * dist_btwn_x_coords_of_six_v2),
                                         (ctrl_y + (ctrl_h/3.0332))))

        for row in range(8):
            for column in range(4):
                if (row == 0 or row == 4) and column == 3: continue
                if (row == 1 or row == 5) and (column == 2 or column == 3): continue
                if row == 2 and column == 0: continue
                if row == 3 and (column == 0 or column == 1): continue
                if row == 6 and column == 2: continue
                if row == 7 and (column == 1 or column == 2): continue
                self.ctrl_color.append(  (first_x_coord_of_four + (column * dist_btwn_x_coords_of_four),
                                         (first_y_coord_of_eight + (row * dist_btwn_y_coords_of_eight))))

        # Hidden colors location
        if self._setting_bool("hidden_colors", default_settings["hidden_colors"]):
            self.ctrl_color.append((ctrl_x + (ctrl_w/18.0000), ctrl_y + (ctrl_h/2.1518)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/4.2353), ctrl_y + (ctrl_h/2.1406)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/13.0909), ctrl_y + (ctrl_h/1.8430)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/3.6923), ctrl_y + (ctrl_h/1.9116)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.8228), ctrl_y + (ctrl_h/1.8853)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.3714), ctrl_y + (ctrl_h/1.8348)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.0746), ctrl_y + (ctrl_h/1.9116)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.0667), ctrl_y + (ctrl_h/1.8430)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.8947), ctrl_y + (ctrl_h/1.6440)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.3333), ctrl_y + (ctrl_h/1.6181)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.2857), ctrl_y + (ctrl_h/1.6440)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.0827), ctrl_y + (ctrl_h/1.6506)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.0588), ctrl_y + (ctrl_h/1.6310)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.0588), ctrl_y + (ctrl_h/1.6118)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.8462), ctrl_y + (ctrl_h/1.4472)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.4545), ctrl_y + (ctrl_h/1.4784)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.3846), ctrl_y + (ctrl_h/1.4838)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.3333), ctrl_y + (ctrl_h/1.4784)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.1803), ctrl_y + (ctrl_h/1.4523)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.1077), ctrl_y + (ctrl_h/1.4421)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.0746), ctrl_y + (ctrl_h/1.4731)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/18.0000), ctrl_y + (ctrl_h/1.4679)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/3.7895), ctrl_y + (ctrl_h/1.4371)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/16.0000), ctrl_y + (ctrl_h/1.3258)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/3.8919), ctrl_y + (ctrl_h/1.3258)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/3.4286), ctrl_y + (ctrl_h/1.3301)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/16.0000), ctrl_y + (ctrl_h/1.2088)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/3.6923), ctrl_y + (ctrl_h/1.2342)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/4.0000), ctrl_y + (ctrl_h/1.2018)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/3.2000), ctrl_y + (ctrl_h/1.1983)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.9200), ctrl_y + (ctrl_h/1.2342)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.4845), ctrl_y + (ctrl_h/1.1844)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.3714), ctrl_y + (ctrl_h/1.1844)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.0746), ctrl_y + (ctrl_h/1.2053)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/16.0000), ctrl_y + (ctrl_h/1.1048)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/4.2353), ctrl_y + (ctrl_h/1.1078)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.3333), ctrl_y + (ctrl_h/1.1078)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.0667), ctrl_y + (ctrl_h/1.1048)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/3.3488), ctrl_y + (ctrl_h/1.0327)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/3.4286), ctrl_y + (ctrl_h/1.0512)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.4694), ctrl_y + (ctrl_h/1.0327)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/2.7692), ctrl_y + (ctrl_h/1.1982)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/2.0571), ctrl_y + (ctrl_h/1.2160)))
            self.ctrl_color.append((ctrl_x + (ctrl_w/1.3211), ctrl_y + (ctrl_h/1.4784)))


    def calculate_statistics(self):
        """ Calculate what colors, how many pixels and lines for the painting
        Updates:    self.img_colors,
                    self.tot_pixels,
                    self.pixels,
                    self.lines
        """
        minimum_line_width = self._setting_int("minimum_line_width", default_settings["minimum_line_width"])
        max_colors = self._setting_int("paint_max_colors", 0)
        self.update_skip_colors()
        if self.quantized_img is None:
            self.img_colors = []
            self.tot_pixels = 0
            self.pixels = 0
            self.lines = 0
            return
        pixel_arr = self.quantized_img.load()

        self.img_colors = []
        self.tot_pixels = 0
        self.pixels = 0
        self.lines = 0

        # Собираем цвета с количеством пикселей, исключая пропускаемые.
        color_stats = []
        color_counts = self.quantized_img.getcolors(maxcolors=self.canvas_w * self.canvas_h) or []
        for color in color_counts:
            if color[1] not in self.skip_colors:
                self.tot_pixels += color[0]
                color_stats.append((color[0], color[1]))  # (count, color_index)

        # В режиме ограничения цветов берём N самых частых цветов.
        # В режиме "Авто" используем умный отбор доминирующих цветов,
        # чтобы не рисовать редкими "шумовыми" оттенками.
        color_stats.sort(key=lambda x: x[0], reverse=True)
        if max_colors > 0:
            color_stats = color_stats[:max_colors]
        else:
            # Smart-auto:
            # 1) отбрасываем очень редкие цвета (<0.2% пикселей),
            # 2) набираем доминирующие цвета до 99.5% покрытия,
            # 3) ограничиваем верхним пределом, чтобы не уходить в сотни оттенков.
            if self.tot_pixels > 0:
                min_pixels = max(1, int(self.tot_pixels * 0.002))
                filtered = [(cnt, idx) for cnt, idx in color_stats if cnt >= min_pixels]
                source = filtered if len(filtered) > 0 else color_stats

                selected = []
                covered = 0
                target_coverage = int(self.tot_pixels * 0.995)
                max_auto_colors = 64

                for cnt, idx in source:
                    selected.append((cnt, idx))
                    covered += cnt
                    if covered >= target_coverage and len(selected) >= 2:
                        break
                    if len(selected) >= max_auto_colors:
                        break

                color_stats = selected if len(selected) > 0 else color_stats

        self.img_colors = [color_index for _, color_index in color_stats]

        for color in self.img_colors:
            is_first_point_of_row = True
            is_last_point_of_row = False
            is_previous_color = False
            is_line = False
            pixels_in_line = 0

            for y in range(self.canvas_h):
                is_first_point_of_row = True
                is_last_point_of_row = False
                is_previous_color = False
                is_line = False
                pixels_in_line = 0

                for x in range(self.canvas_w):
                    if x == (self.canvas_w - 1): is_last_point_of_row = True

                    if is_first_point_of_row:
                        is_first_point_of_row = False
                        if pixel_arr[x, y] == color:
                            is_previous_color = True
                            pixels_in_line = 1
                        continue

                    if pixel_arr[x, y] == color:
                        if is_previous_color:
                            if is_last_point_of_row:
                                if pixels_in_line >= minimum_line_width: self.lines += 1
                                else:
                                    self.pixels += (pixels_in_line + 1)
                            else: is_line = True; pixels_in_line += 1
                        else:
                            if is_last_point_of_row: self.pixels += 1
                            else:
                                is_previous_color = True
                                pixels_in_line = 1
                    else:
                        if is_previous_color:
                            if is_line:
                                is_line = False

                                if is_last_point_of_row:
                                    if pixels_in_line >= minimum_line_width: self.lines += 1
                                    else:
                                        self.pixels += (pixels_in_line + 1)
                                    continue

                                if pixels_in_line >= minimum_line_width: self.lines += 1
                                else: self.pixels += (pixels_in_line + 1)
                                pixels_in_line = 0
                            else: self.pixels += 1
                            is_previous_color = False
                        else:
                            is_line = False
                            pixels_in_line = 0


    def calculate_estimated_time(self):
        """ Calculate estimated time for the painting process.
        Updates:    Estimated time for clicking and lines
                    Estimated time for only clicking
        """
        one_click_time = self.click_delay + 0.001
        one_click_time = one_click_time * 2 if self.use_double_click else one_click_time
        one_line_time = (self.line_delay * 5) + 0.0035
        set_paint_controls_time =   (len(self.img_colors) * ((2 * self.click_delay) + (2 * self.ctrl_area_delay))) + ((2 * self.click_delay) + (2 * self.ctrl_area_delay))
        est_time_lines = int((self.pixels * one_click_time) + (self.lines * one_line_time) + set_paint_controls_time)
        est_time_click = int((self.tot_pixels * one_click_time) + set_paint_controls_time)

        if not self._setting_bool("draw_lines", default_settings["draw_lines"]):
            self.prefer_lines = False
            self.estimated_time = est_time_click
        elif est_time_lines < est_time_click:
            self.prefer_lines = True
            self.estimated_time = est_time_lines
        else:
            self.prefer_lines = False
            self.estimated_time = est_time_click


    def click_pixel(self, x = 0, y = 0):
        """ Click the pixel """
        if isinstance(x, tuple):
            pyautogui.click(x[0], x[1])
            if self.use_double_click:
                pyautogui.click(x[0], x[1])
        else:
            pyautogui.click(x, y)
            if self.use_double_click:
                pyautogui.click(x, y)


    def set_external_hex_color(self, color_index):
        """Установить цвет через внешнее HEX-поле (если оно настроено)."""
        if not self.use_external_hex:
            return
        if self.updated_palette is None or color_index >= len(self.updated_palette):
            return

        hex_x = self._setting_int("brush_hex_x", 0)
        hex_y = self._setting_int("brush_hex_y", 0)
        if hex_x == 0 or hex_y == 0:
            return

        # текущий цвет в HEX без #
        color_rgb = self.updated_palette[color_index]
        hex_str = rgb_to_hex(color_rgb).lstrip("#")

        # клик по полю HEX и ввод значения
        pyautogui.click(hex_x, hex_y)
        time.sleep(self.ctrl_area_delay or 0.05)
        try:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.03)
            pyautogui.press("backspace")
            time.sleep(0.03)
        except Exception:
            pass
        pyautogui.typewrite(hex_str)
        pyautogui.press("enter")
        time.sleep(self.ctrl_area_delay or 0.05)


    def draw_line(self, point_A, point_B):
        """ Draws a line between point_A and point_B. """
        pyautogui.PAUSE = self.line_delay
        pyautogui.mouseDown(button="left", x=point_A[0], y=point_A[1])
        pyautogui.keyDown("shift")
        pyautogui.moveTo(point_B[0], point_B[1])
        pyautogui.keyUp("shift")
        pyautogui.mouseUp(button="left")
        pyautogui.PAUSE = self.click_delay


    def key_event(self, key):
        """ Key-press thread during painting. """
        try: key_str = str(key.char)
        except: key_str = str(key.name)

        if key_str == self.pause_key:       # Pause
            self.paused = not self.paused
        elif key_str == self.skip_key:      # Skip color
            self.paused = False
            self.skip_current_color = True
        elif key_str == self.abort_key:     # Abort
            self.paused = False
            self.abort = True


    def shutdown(self, listener, start_time, state=0):
        """Shutdown the painting process (вызывается из GUI-потока)."""
        try:
            if listener is not None:
                listener.stop()
        except Exception:
            pass
        self.paint_listener = None
        self._set_main_controls_enabled(True)

        elapsed_time = int(time.time() - start_time)
        self._append_log("Затрачено времени: " + str(time.strftime("%H:%M:%S", time.gmtime(elapsed_time))))
        if self.hotkey_label is not None:
            try:
                self.hotkey_label.hide()
                self.hotkey_label.deleteLater()
            except Exception:
                pass
            self.hotkey_label = None

        if state == 0:
            self._set_progress(100)

        if self._setting_bool("window_topmost", default_settings["window_topmost"]):
            try:
                self.parent.setWindowFlags(self.parent.windowFlags() & ~Qt.WindowStaysOnTopHint)
                self.parent.show()
            except Exception:
                pass
        try:
            self.parent.activateWindow()
        except Exception:
            pass


    def shutdown_from_thread(self):
        """Остановить keyboard-listener из рабочего потока (без трогания GUI)."""
        try:
            if self.paint_listener is not None:
                self.paint_listener.stop()
        except Exception:
            pass
        self.paint_listener = None

    def choose_painting_controls(self, size, brush, color):
        """ Choose the paint controls """
        if self.current_ctrl_size != size:
            self.current_ctrl_size = size
            self.click_pixel(self.ctrl_size[size])
            time.sleep(self.ctrl_area_delay)

        if self.current_ctrl_brush != brush:
            self.current_ctrl_brush = brush
            self.click_pixel(self.ctrl_brush[brush])
            time.sleep(self.ctrl_area_delay)

        # Если внешнее HEX-поле настроено, используем его для выбора цвета.
        # Внутренние клики по палитре по-прежнему задают размер/кисть/непрозрачность,
        # но сам цвет переключаем через HEX.
        if self.use_external_hex:
            self.set_external_hex_color(color)
        else:
            if self.use_hidden_colors:
                if   color >= 0  and color < 64: self.click_pixel(self.ctrl_opacity[5])
                elif color >= 64 and color < 128: self.click_pixel(self.ctrl_opacity[4])
                elif color >= 128 and color < 192: self.click_pixel(self.ctrl_opacity[3])
                elif color >= 192 and color < 256: self.click_pixel(self.ctrl_opacity[2])
            else:
                if   color >= 0  and color < 20: self.click_pixel(self.ctrl_opacity[5])
                elif color >= 20 and color < 40: self.click_pixel(self.ctrl_opacity[4])
                elif color >= 40 and color < 60: self.click_pixel(self.ctrl_opacity[3])
                elif color >= 60 and color < 80: self.click_pixel(self.ctrl_opacity[2])
            time.sleep(self.ctrl_area_delay)

            if self.current_ctrl_color != color:
                if self.use_hidden_colors:
                    self.click_pixel(self.ctrl_color[color%64])
                else:
                    self.click_pixel(self.ctrl_color[color%20])
                time.sleep(self.ctrl_area_delay)


    def update_skip_colors(self):
        """Updates the skip colors list.

        Фон считается по той же колоночной логике, что и update_palette:
        col = rust_index % 64, варианты прозрачности — col + 64*b (hidden)
        или b*64 + col для видимых столбцов (col < 20).
        """
        self.skip_colors = []
        temp_skip_colors = self.settings.value("skip_colors", default_settings["skip_colors"], "QStringList")
        if temp_skip_colors is None:
            temp_skip_colors = []
        if isinstance(temp_skip_colors, str):
            temp_skip_colors = [temp_skip_colors]
        if len(temp_skip_colors) != 0:
            for color in temp_skip_colors:
                try:
                    rgb = closest_color(tuple(hex_to_rgb(color)))
                except (TypeError, ValueError, AttributeError):
                    continue
                if self.updated_palette is not None and rgb in self.updated_palette:
                    self.skip_colors.append(self.updated_palette.index(rgb))

        skip_background_color = self._setting_bool("skip_background_color", default_settings["skip_background_color"])
        if skip_background_color and self.updated_palette is not None:
            bg_color_rgb = self._background_rgb()
            use_hidden_colors = self._setting_bool("hidden_colors", default_settings["hidden_colors"])
            use_opacities = self._setting_bool("brush_opacities", default_settings["brush_opacities"])

            bg_colors = []

            if bg_color_rgb in self.updated_palette:
                if use_hidden_colors:
                    col = self.updated_palette.index(bg_color_rgb) % 64
                    if use_opacities:
                        bg_colors = [index for index, entry in enumerate(self.updated_palette)
                                     if entry == bg_color_rgb]
                    else:
                        bg_colors = [col]
                else:
                    first = self.updated_palette.index(bg_color_rgb)
                    if use_opacities:
                        bg_colors = [index for index, entry in enumerate(self.updated_palette)
                                     if entry == bg_color_rgb]
                    else:
                        bg_colors = [first]

            self.skip_colors = self.skip_colors + bg_colors

        self.skip_colors = list(map(int, self.skip_colors))


    def start_painting(self):
        """Start the painting (подготовка в GUI, цикл — в PaintingWorker)."""
        # Update global variables
        self.use_hidden_colors = self._setting_bool("hidden_colors", default_settings["hidden_colors"])
        self.pause_key = str(self.settings.value("pause_key", default_settings["pause_key"])).lower()
        self.skip_key = str(self.settings.value("skip_key", default_settings["skip_key"])).lower()
        self.abort_key = str(self.settings.value("abort_key", default_settings["abort_key"])).lower()

        # Update local variables
        minimum_line_width = self._setting_int("minimum_line_width", default_settings["minimum_line_width"])
        brush_type = self._setting_int("brush_type", default_settings["brush_type"])
        update_canvas_end = self._setting_bool("update_canvas_end", default_settings["update_canvas_end"])
        window_topmost = self._setting_bool("window_topmost", default_settings["window_topmost"])
        update_canvas = self._setting_bool("update_canvas", default_settings["update_canvas"])
        show_info = self._setting_bool("show_information", default_settings["show_information"])
        paint_background = self._setting_bool("paint_background", default_settings["paint_background"])


        self.update()                               # Update click, line, ctrl_area delay
        self.update_skip_colors()                   # Update self.skip_colors variable
        if not self.locate_canvas_area(): return    # Locate the canvas
        if not self.convert_img(): return           # Quantize the image

        # Clear the log
        self._set_progress(0)
        log = self._get_widget("log_TextEdit")
        if log is not None and hasattr(log, "clear"):
            log.clear()
        self._append_log("Вычисляю статистику...")
        QApplication.processEvents()

        self.calculate_ctrl_tools_positioning()     # Calculate the control tools positioning
        self.calculate_statistics()                 # Calculate statistics (colors, total pixels, lines)
        self.calculate_estimated_time()             # Calculate the estimated time


        # Opens a information dialog
        question = "Размеры: \t\t\t\t" + str(self.canvas_w) + " x " + str(self.canvas_h)
        question += "\nКоличество цветов:\t\t\t" + str(len(self.img_colors))
        question += "\nВсего пикселей для рисования:\t" + str(self.tot_pixels)
        question += "\nПикселей для рисования:\t\t" + str(self.pixels)
        question += "\nКоличество линий:\t\t\t" + str(self.lines)
        question += "\nОценочное время рисования:\t" + str(time.strftime("%H:%M:%S", time.gmtime(self.estimated_time)))
        question += "\n\nНачать рисование?"
        if show_info:
            btn = QMessageBox.question(self.parent, None, question, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if btn == QMessageBox.No:
                return

        if self.paint_thread is not None and self.paint_thread.isRunning():
            self._append_log("Рисование уже запущено...")
            return

        # Disable mainwindow buttons while painting
        self._set_main_controls_enabled(False)

        # If window_topmost setting is set, activate window always on top functionality
        if window_topmost:
            self.parent.setWindowFlags(self.parent.windowFlags() | Qt.WindowStaysOnTopHint)
            self.parent.show()

        # Add label info about pause, skip and abort keys
        if self.hotkey_label is not None:
            try:
                self.hotkey_label.hide()
                self.hotkey_label.deleteLater()
            except Exception:
                pass
        self.hotkey_label = QLabel(self.parent)
        self.hotkey_label.setGeometry(QRect(10, 425, 261, 21))
        self.hotkey_label.setText(self.pause_key + " = Пауза        " +
                                  self.skip_key + " = Пропуск        " +
                                  self.abort_key + " = Отмена")
        self.hotkey_label.show()

        # Параметры цикла рисования (читаются один раз, до старта потока).
        self.paint_params = {
            "minimum_line_width": minimum_line_width,
            "brush_type": brush_type,
            "update_canvas": update_canvas,
            "update_canvas_end": update_canvas_end,
            "paint_background": paint_background,
        }
        self.paused = False
        self.abort = False
        self.skip_current_color = False
        self.paint_start_time = time.time()

        self.paint_thread = PaintingWorker(self, self.parent)
        if self.ui_bridge is None:
            self.ui_bridge = _UiBridge(self, self.parent)
        self.paint_thread.log.connect(self.ui_bridge.log.emit)
        self.paint_thread.progress.connect(self.ui_bridge.progress.emit)
        self.paint_thread.finished_ok.connect(self.ui_bridge.finished_ok.emit)
        self.paint_thread.aborted.connect(self.ui_bridge.aborted.emit)
        self.paint_thread.finished.connect(self._on_paint_thread_finished)
        self.paint_thread.start()

    def _on_paint_thread_finished(self):
        self.paint_thread = None

    def paint_loop(self, on_progress=None, on_log=None):
        """Цикл рисования в рабочем потоке (без прямых обращений к GUI)."""
        params = getattr(self, "paint_params", {}) or {}
        minimum_line_width = int(params.get("minimum_line_width", 10))
        brush_type = int(params.get("brush_type", 1))
        update_canvas = bool(params.get("update_canvas", True))
        update_canvas_end = bool(params.get("update_canvas_end", True))
        paint_background = bool(params.get("paint_background", False))

        def emit_log(text):
            if on_log is not None:
                on_log(text)

        def emit_progress(value):
            if on_progress is not None:
                on_progress(int(value))

        # Paint the background with the default background color
        self.click_pixel(self.ctrl_size[0])  # To set focus on the rust window
        time.sleep(.5)
        self.click_pixel(self.ctrl_size[0])
        if paint_background and self.background_color is not None:
            emit_log("Закрашиваю фон...")
            self.choose_painting_controls(5, 3, self.background_color)
            x_start = self.canvas_x + 10
            x_end = self.canvas_x + self.canvas_w - 10
            loops = int((self.canvas_h - 10) / 10)
            for i in range(1, loops + 1):
                if self.abort:
                    break
                while self.paused:
                    time.sleep(0.05)
                    if self.abort:
                        break
                self.draw_line((x_start, self.canvas_y + (10 * i)), (x_end, self.canvas_y + (10 * i)))

        # Print out the start time, estimated time and estimated finish time
        emit_log("Время начала:\t" + str((datetime.datetime.now()).time().strftime("%H:%M:%S")))
        emit_log("Оценочное время:\t" + str(time.strftime("%H:%M:%S", time.gmtime(self.estimated_time))))
        emit_log("Оценочное завершение:\t" + str((datetime.datetime.now() + datetime.timedelta(seconds=self.estimated_time)).time().strftime("%H:%M:%S")))

        pixel_counter = 0
        previous_progress_percent = None

        start_time = self.paint_start_time or time.time()
        pixel_arr = self.quantized_img.load()

        # Start keyboard listener
        self.paint_listener = keyboard.Listener(on_press=self.key_event)
        self.paint_listener.start()

        for counter, color in enumerate(self.img_colors):
            self.skip_current_color = False
            # Print current color to the log
            color_hex = rgb_to_hex(self.updated_palette[color])
            emit_log(
                "(" + str((counter + 1)) + "/" + str((len(self.img_colors))) + ") Текущий цвет: " +
                "<span style=\" font-size:8pt; font-weight:600; color:" + str(color_hex) + ";\" >█" +
                str(color_hex) + "█</span>")

            # Choose painting controls
            self.choose_painting_controls(0, brush_type, color)

            for y in range(self.canvas_h):
                if self.skip_current_color:
                    break

                # Calculate percentage for progress bar
                if self.tot_pixels > 0:
                    progress_percent = int(pixel_counter / (self.tot_pixels / 100))
                    progress_percent = max(0, min(100, progress_percent))
                else:
                    progress_percent = 0
                if progress_percent != previous_progress_percent:
                    previous_progress_percent = progress_percent
                    emit_progress(progress_percent)

                # Reset variables
                is_first_point_of_row = True
                is_last_point_of_row = False
                is_previous_color = False
                is_line = False
                pixels_in_line = 0

                for x in range(self.canvas_w):

                    while self.paused:
                        time.sleep(0.05)
                    if self.skip_current_color:
                        break
                    if self.abort:
                        emit_log("Отменено...")
                        return

                    if x == (self.canvas_w - 1):
                        is_last_point_of_row = True

                    if is_first_point_of_row and self.prefer_lines:
                        is_first_point_of_row = False
                        if pixel_arr[x, y] == color:
                            first_point = (self.canvas_x + x, self.canvas_y + y)
                            is_previous_color = True
                            pixels_in_line = 1
                        continue

                    if pixel_arr[x, y] == color:
                        if not self.prefer_lines:
                            self.click_pixel(self.canvas_x + x, self.canvas_y + y)
                            pixel_counter += 1
                            continue
                        if is_previous_color:
                            if is_last_point_of_row:
                                if pixels_in_line >= minimum_line_width:
                                    self.draw_line(first_point, (self.canvas_x + x, self.canvas_y + y))
                                    pixel_counter += pixels_in_line
                                else:
                                    for index in range(pixels_in_line):
                                        self.click_pixel(first_point[0] + index, self.canvas_y + y)
                                    self.click_pixel(self.canvas_x + x, self.canvas_y + y)
                                    pixel_counter += pixels_in_line + 1
                            else:
                                is_line = True
                                pixels_in_line += 1
                        else:
                            if is_last_point_of_row:
                                self.click_pixel(self.canvas_x + x, self.canvas_y + y)
                                pixel_counter += 1
                            else:
                                first_point = (self.canvas_x + x, self.canvas_y + y)
                                is_previous_color = True
                                pixels_in_line = 1
                    else:
                        if not self.prefer_lines:
                            continue
                        if is_previous_color:
                            if is_line:
                                is_line = False

                                if is_last_point_of_row:
                                    if pixels_in_line >= minimum_line_width:
                                        self.draw_line(first_point, (self.canvas_x + (x - 1), self.canvas_y + y))
                                        pixel_counter += pixels_in_line
                                    else:
                                        for index in range(pixels_in_line):
                                            self.click_pixel(first_point[0] + index, self.canvas_y + y)
                                        pixel_counter += pixels_in_line
                                    continue

                                if pixels_in_line >= minimum_line_width:
                                    self.draw_line(first_point, (self.canvas_x + (x - 1), self.canvas_y + y))
                                    pixel_counter += pixels_in_line
                                else:
                                    for index in range(pixels_in_line):
                                        self.click_pixel(first_point[0] + index, self.canvas_y + y)
                                    pixel_counter += pixels_in_line
                                pixels_in_line = 0

                            else:
                                self.click_pixel(self.canvas_x + (x - 1), self.canvas_y + y)
                                pixel_counter += 1
                            is_previous_color = False
                        else:
                            is_line = False
                            pixels_in_line = 0

            if update_canvas:
                self.click_pixel(self.ctrl_update)

        if update_canvas_end:
            self.click_pixel(self.ctrl_update)
