from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.core.quality_checker import QualityReport
from video_unicalizator.core.variation_generator import RenderAttempt, VariationGenerator
from video_unicalizator.core.video_processor import VariationProfile
from video_unicalizator.state import AppState


class VariationGeneratorTestCase(unittest.TestCase):
    def test_resolve_quotes_falls_back_to_preview_text(self) -> None:
        state = AppState()
        state.text_style.preview_text = "Текст из макета"
        quotes = VariationGenerator()._resolve_quotes(state)
        self.assertEqual(quotes, ["Текст из макета"])

    def test_resolve_quotes_allows_empty_overlay(self) -> None:
        state = AppState()
        state.text_style.preview_text = "   "
        quotes = VariationGenerator()._resolve_quotes(state)
        self.assertEqual(quotes, [])

    def test_generate_continues_after_single_variation_error(self) -> None:
        state = AppState()
        state.media.original_videos = [Path("source.mp4")]
        state.generation.variation_count = 2

        generator = VariationGenerator()
        side_effects = [
            RuntimeError("render failed"),
            RenderAttempt(
                output_video=Path("output_ok.mp4"),
                profile=VariationProfile(
                    speed_factor=1.0,
                    brightness_shift=0.0,
                    contrast_shift=0.0,
                    saturation_shift=0.0,
                    accent_color=(1, 2, 3),
                    accent_strength=0.0,
                ),
                report=QualityReport(
                    sharpness_score=100.0,
                    visual_difference_score=10.0,
                    format_ok=True,
                    warnings=[],
                ),
                quote="quote",
                music_track=None,
                snapshot=None,
            ),
        ]

        with (
            patch.object(generator, "_validate_state", return_value=None),
            patch.object(generator.quality_checker, "inspect_video", return_value=(1080, 1920, 1.0)),
            patch.object(generator, "_render_with_quality_gate", side_effect=side_effects),
        ):
            generated = generator.generate(state)

        self.assertEqual(len(generated), 1)
        self.assertEqual(generator.last_summary.failed_count, 1)
        self.assertEqual(generator.last_summary.success_count, 1)


if __name__ == "__main__":
    unittest.main()
