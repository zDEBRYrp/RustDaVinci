import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication
from PIL import Image

from lib.rustDaVinci import rustDaVinci
from ui.settings.default_settings import default_settings

_app = None


def _engine(**overrides):
    global _app
    if _app is None:
        _app = QApplication([])
    engine = rustDaVinci.__new__(rustDaVinci)
    engine.settings = QSettings("RustDaVinciTest", "statistics")
    engine.settings.clear()
    for key, value in default_settings.items():
        if key == "skip_colors":
            engine.settings.setValue(key, [])
        else:
            engine.settings.setValue(key, value)
    for key, value in overrides.items():
        engine.settings.setValue(key, value)
    engine.palette_data = None
    engine.updated_palette = None
    engine.background_color = None
    engine.skip_colors = []
    engine.img_colors = []
    engine.tot_pixels = 0
    engine.pixels = 0
    engine.lines = 0
    return engine


def _quantized_block(engine, width=16, height=16):
    src = Image.new("RGB", (width, height), (255, 0, 0))
    quantized = engine.quantize_to_palette(src)
    engine.quantized_img = quantized
    engine.canvas_w, engine.canvas_h = quantized.size
    return quantized


def test_calculate_statistics_empty_canvas_no_crash():
    engine = _engine()
    engine.quantize_to_palette(Image.new("RGB", (4, 4), (255, 0, 0)))
    engine.quantized_img = Image.new("P", (0, 0))
    engine.canvas_w, engine.canvas_h = 0, 0
    engine.calculate_statistics()
    assert engine.tot_pixels == 0
    assert engine.img_colors == []


def test_calculate_statistics_max_colors_truncates():
    engine = _engine(paint_max_colors=1, skip_background_color=0, minimum_line_width=1000)
    _quantized_block(engine)
    engine.calculate_statistics()
    assert len(engine.img_colors) == 1
    assert engine.tot_pixels == 16 * 16


def test_calculate_statistics_auto_selects_dominant():
    engine = _engine(paint_max_colors=0, skip_background_color=0, minimum_line_width=1000)
    _quantized_block(engine)
    engine.calculate_statistics()
    assert len(engine.img_colors) >= 1
    assert engine.tot_pixels == 16 * 16
