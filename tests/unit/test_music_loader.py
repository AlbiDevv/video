from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.services.music_loader import MusicRotation, QuoteRotation


class MusicRotationTestCase(unittest.TestCase):
    def test_rotation_uses_all_tracks_before_repeat_cycle(self) -> None:
        rotation = MusicRotation()
        tracks = [Path("a.mp3"), Path("b.mp3"), Path("c.mp3")]

        with patch("random.choice", side_effect=lambda options: options[0]):
            picks = [rotation.pick(tracks) for _ in range(4)]

        self.assertEqual({pick.track for pick in picks[:3]}, set(tracks))
        self.assertEqual(picks[0].cycle_index, 0)
        self.assertEqual(picks[1].cycle_index, 0)
        self.assertEqual(picks[2].cycle_index, 0)
        self.assertEqual(picks[3].cycle_index, 1)

    def test_preview_for_accept_index_prefers_unused_tracks_first(self) -> None:
        rotation = MusicRotation()
        tracks = [Path("b.mp3"), Path("a.mp3"), Path("c.mp3")]

        picks = [rotation.preview_for_accept_index(tracks, index) for index in range(5)]

        self.assertEqual([pick.track for pick in picks[:3]], [Path("a.mp3"), Path("b.mp3"), Path("c.mp3")])
        self.assertEqual(picks[3].cycle_index, 1)
        self.assertEqual(picks[3].track, Path("a.mp3"))
        self.assertEqual(picks[4].track, Path("b.mp3"))

    def test_quote_rotation_uses_unused_quotes_before_repeat(self) -> None:
        rotation = QuoteRotation()
        quotes = ["Первая", "Вторая", "Третья"]

        with patch("random.choice", side_effect=lambda options: options[0]):
            picks = [rotation.pick(quotes) for _ in range(4)]

        self.assertEqual([pick.text for pick in picks[:3]], quotes)
        self.assertEqual(picks[3].cycle_index, 1)

    def test_quote_rotation_avoids_repeating_inside_single_roll_when_possible(self) -> None:
        rotation = QuoteRotation()
        quotes = ["A", "B", "C"]
        used_in_roll: set[str] = set()

        with patch("random.choice", side_effect=lambda options: options[0]):
            first = rotation.pick(quotes, used_in_roll=used_in_roll)
            used_in_roll.add(first.text)
            second = rotation.pick(quotes, used_in_roll=used_in_roll)

        self.assertNotEqual(first.text, second.text)


if __name__ == "__main__":
    unittest.main()
