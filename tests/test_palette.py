import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication
from PIL import Image

from lib.rustDaVinci import rustDaVinci
from lib.rustPaletteData import rust_palette
from ui.settings.default_settings import default_settings

_app = None


def _engine(**overrides):
    global _app
    if _app is None:
        _app = QApplication([])
    engine = rustDaVinci.__new__(rustDaVinci)
    engine.settings = QSettings("RustDaVinciTest", "palette")
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
    return engine


def test_palette_lengths_visible():
    engine = _engine(hidden_colors=0, brush_opacities=0)
    palette, updated, _bg = engine.update_palette(rust_palette[0])
    assert len(updated) == 20
    assert len(palette.getpalette()) == 768


def test_palette_lengths_visible_opacities():
    engine = _engine(hidden_colors=0, brush_opacities=1)
    _palette, updated, _bg = engine.update_palette(rust_palette[0])
    assert len(updated) == 80


def test_palette_lengths_hidden():
    engine = _engine(hidden_colors=1, brush_opacities=0)
    _palette, updated, _bg = engine.update_palette(rust_palette[0])
    assert len(updated) == 64


def test_palette_lengths_hidden_opacities():
    engine = _engine(hidden_colors=1, brush_opacities=1)
    _palette, updated, _bg = engine.update_palette(rust_palette[0])
    assert len(updated) == 256


def test_background_replaced_in_all_opacity_blocks():
    engine = _engine(hidden_colors=0, brush_opacities=1, skip_background_color=1,
                     background_color="#2ECC71")
    _palette, updated, _bg = engine.update_palette((46, 204, 113))
    assert updated[0] == (46, 204, 113)
    assert updated[20] == (46, 204, 113)
    assert updated[40] == (46, 204, 113)
    assert updated[60] == (46, 204, 113)


def test_skip_colors_match_palette_replacement():
    engine = _engine(hidden_colors=0, brush_opacities=1, skip_background_color=1,
                     background_color="#2ECC71")
    engine.update_palette((46, 204, 113))
    engine.update_skip_colors()
    assert engine.skip_colors == [0, 20, 40, 60]


def test_quantize_does_not_mutate_source():
    engine = _engine()
    src = Image.new("RGB", (8, 8), (255, 0, 0))
    before = list(src.get_flattened_data())
    out = engine.quantize_to_palette(src)
    assert out.mode == "P"
    assert list(src.get_flattened_data()) == before


def test_quantize_rgba_source():
    engine = _engine()
    src = Image.new("RGBA", (8, 8), (255, 0, 0, 128))
    out = engine.quantize_to_palette(src)
    assert out.mode == "P"
    assert out.size == (8, 8)
