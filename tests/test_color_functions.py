import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.color_functions import closest_color, hex_to_rgb, rgb_to_hex
from lib.rustPaletteData import rust_palette


def test_hex_rgb_roundtrip():
    assert hex_to_rgb("#ECF0F1") == (236, 240, 241)
    assert rgb_to_hex((236, 240, 241)) == "#ECF0F1"


def test_closest_color_returns_palette_entry():
    assert closest_color((0, 0, 0)) in rust_palette
    assert closest_color((46, 204, 113)) == (46, 204, 113)
