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


if __name__ == "__main__":
    unittest.main()
