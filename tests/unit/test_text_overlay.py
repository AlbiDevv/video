from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.core.text_overlay import OverlayLayout, TextOverlayRenderer
from video_unicalizator.state import TextStyle


class TextOverlayRendererTestCase(unittest.TestCase):
    def test_renderer_preserves_manual_line_breaks(self) -> None:
        style = TextStyle(font_name="Segoe UI", preview_text="Первая\nВторая", box_width_ratio=0.85)
        renderer = TextOverlayRenderer(OverlayLayout(width=1080, height=1920), style, "Первая\nВторая")
        self.assertEqual(renderer.text_lines[:2], ["Первая", "Вторая"])

    def test_renderer_handles_emoji_without_crashing(self) -> None:
        style = TextStyle(font_name="Segoe UI", preview_text="Тест 😊", box_width_ratio=0.8)
        renderer = TextOverlayRenderer(OverlayLayout(width=1080, height=1920), style, "Тест 😊")
        self.assertEqual(renderer.overlay_rgba.shape, (1920, 1080, 4))
        self.assertGreater(renderer.overlay_rgba[..., 3].max(), 0)

    def test_renderer_wraps_more_lines_for_narrower_box(self) -> None:
        quote = "Это длинная цитата для проверки переноса строк в узком блоке"
        wide_style = TextStyle(font_name="Segoe UI", preview_text=quote, box_width_ratio=0.85)
        narrow_style = TextStyle(font_name="Segoe UI", preview_text=quote, box_width_ratio=0.35)

        wide_renderer = TextOverlayRenderer(OverlayLayout(width=1080, height=1920), wide_style, quote)
        narrow_renderer = TextOverlayRenderer(OverlayLayout(width=1080, height=1920), narrow_style, quote)

        self.assertLessEqual(len(wide_renderer.text_lines), len(narrow_renderer.text_lines))
        self.assertLess(narrow_renderer.bounds.width, wide_renderer.bounds.width)


if __name__ == "__main__":
    unittest.main()
