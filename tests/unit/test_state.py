from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.state import AppState


class AppStateTestCase(unittest.TestCase):
    def test_remove_original_updates_selection_and_profiles(self) -> None:
        state = AppState()
        a = Path("a.mp4")
        b = Path("b.mp4")
        c = Path("c.mp4")
        state.media.original_videos = [a, b, c]
        state.selected_video = b
        state.ensure_video_profile(a)
        state.ensure_video_profile(b)
        state.ensure_video_profile(c)

        selected = state.remove_original(b)

        self.assertEqual(state.media.original_videos, [a, c])
        self.assertEqual(selected, c)
        self.assertEqual(state.selected_video, c)
        self.assertNotIn(str(b), state.video_profiles)

    def test_remove_last_original_clears_selection(self) -> None:
        state = AppState()
        a = Path("a.mp4")
        state.media.original_videos = [a]
        state.selected_video = a
        state.ensure_video_profile(a)

        selected = state.remove_original(a)

        self.assertIsNone(selected)
        self.assertIsNone(state.selected_video)
        self.assertEqual(state.media.original_videos, [])

    def test_build_default_profile_uses_layer_sample_defaults(self) -> None:
        state = AppState()
        state.set_default_layer_sample("A", "Первая\nцитата")
        state.set_default_layer_sample("B", "Вторая строка")

        profile = state.build_default_profile()

        self.assertEqual(profile.layer_a.preview_text, "Первая\nцитата")
        self.assertEqual(profile.layer_b.preview_text, "Вторая строка")
        self.assertTrue(profile.layer_a.enabled)
        self.assertTrue(profile.layer_b.enabled)

    def test_ensure_video_profile_inherits_quote_samples_loaded_before_originals(self) -> None:
        state = AppState()
        state.set_default_layer_sample("A", "Цитата A")
        state.set_default_layer_sample("B", "Цитата B")

        profile = state.ensure_video_profile(Path("video.mp4"))

        self.assertEqual(profile.layer_a.preview_text, "Цитата A")
        self.assertEqual(profile.layer_b.preview_text, "Цитата B")


if __name__ == "__main__":
    unittest.main()
