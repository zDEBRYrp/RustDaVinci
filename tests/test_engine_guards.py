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
    engine.settings = QSettings("RustDaVinciTest", "guards")
    engine.settings.clear()
    for key, value in default_settings.items():
        if key == "skip_colors":
            engine.settings.setValue(key, [])
        else:
            engine.settings.setValue(key, value)
    for key, value in overrides.items():
        engine.settings.setValue(key, value)
    engine.palette_data = None
    engine.updated_palette = []
    engine.background_color = None
    engine.skip_colors = []
    engine.img_colors = []
    engine.tot_pixels = 0
    engine.pixels = 0
    engine.lines = 0
    engine.org_img = None
    engine.org_img_template = None
    engine.org_img_ok = False
    engine.quantized_img = None
    engine.canvas_x, engine.canvas_y = 0, 0
    engine.canvas_w, engine.canvas_h = 0, 0
    return engine


def test_hex_partial_zero_disables_external_mode():
    engine = _engine(brush_hex_x=0, brush_hex_y=500)
    engine.parent = None
    engine.use_external_hex = True
    engine.update()
    assert engine.use_external_hex is False


def test_convert_img_without_image_returns_false():
    engine = _engine()
    assert engine.convert_img() is False
    assert engine.quantized_img is None
    assert engine.org_img_ok is False


def test_statistics_many_colors_uses_maxcolors():
    engine = _engine(skip_background_color=0, minimum_line_width=1)
    engine.update_palette((46, 204, 113))
    src = Image.new("RGB", (32, 32))
    pixels = src.load()
    palette = engine.updated_palette
    for y in range(32):
        for x in range(32):
            pixels[x, y] = palette[(x + y * 32) % len(palette)]
    quantized = engine.quantize_to_palette(src)
    engine.quantized_img = quantized
    engine.canvas_w, engine.canvas_h = quantized.size
    engine.calculate_statistics()
    assert engine.tot_pixels == 32 * 32
    assert len(engine.img_colors) > 0
