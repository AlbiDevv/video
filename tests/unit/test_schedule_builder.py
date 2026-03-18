from __future__ import annotations

import random
import sys
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.scheduler.schedule_builder import ScheduleBuilder
from video_unicalizator.state import GeneratedVariation


class ScheduleBuilderTestCase(unittest.TestCase):
    def test_build_returns_all_entries_and_intervals_in_range(self) -> None:
        random.seed(7)
        start = datetime(2026, 1, 1, 9, 0)
        variations = [
            GeneratedVariation(
                source_video=Path("source.mp4"),
                output_video=Path(f"output_{index}.mp4"),
                quote="test",
                music_track=None,
                speed_factor=1.0,
                sharpness_score=100.0,
                visual_difference_score=10.0,
            )
            for index in range(5)
        ]

        entries = ScheduleBuilder().build(variations, start_at=start)

        self.assertEqual(len(entries), 5)
        self.assertTrue(all(entry.file_name.endswith(".mp4") for entry in entries))


if __name__ == "__main__":
    unittest.main()
