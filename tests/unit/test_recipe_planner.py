from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.core.recipe_planner import SourceUniquenessLedger, VariationRecipePlanner
from video_unicalizator.services.music_loader import MusicChoice
from video_unicalizator.state import ColorGradeProfile, GenerationSettings


class RecipePlannerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = VariationRecipePlanner(
            source_video=Path("source.mp4"),
            source_duration=12.8,
            settings=GenerationSettings(variation_count=10, candidate_search_attempts=24),
            color_grade=ColorGradeProfile(),
        )

    def test_planner_emits_unique_visual_keys_for_same_source(self) -> None:
        ledger = SourceUniquenessLedger()
        music_choice = MusicChoice(track=Path("track_a.mp3"), cycle_index=0)

        visual_keys: set[tuple] = set()
        for _ in range(4):
            candidate = self.planner.next_recipe(ledger, music_choice)
            self.assertIsNotNone(candidate)
            assert candidate is not None
            self.assertNotIn(candidate.recipe.visual_key, visual_keys)
            visual_keys.add(candidate.recipe.visual_key)
            ledger.record_accepted(candidate.recipe)

    def test_rejected_neighbourhood_forces_new_recipe(self) -> None:
        ledger = SourceUniquenessLedger()
        music_choice = MusicChoice(track=Path("track_a.mp3"), cycle_index=0)

        first = self.planner.next_recipe(ledger, music_choice)
        self.assertIsNotNone(first)
        assert first is not None
        ledger.record_rejected(first.recipe)

        second = self.planner.next_recipe(ledger, music_choice)
        self.assertIsNotNone(second)
        assert second is not None
        self.assertNotEqual(first.recipe.visual_key, second.recipe.visual_key)
        self.assertGreater(self.planner.recipe_distance(first.recipe, second.recipe), 1.0)

    def test_quote_text_is_not_part_of_recipe_identity(self) -> None:
        ledger = SourceUniquenessLedger()
        music_choice = MusicChoice(track=Path("track_a.mp3"), cycle_index=0)
        candidate = self.planner.next_recipe(ledger, music_choice)

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertNotIn("quote", candidate.recipe.recipe_key.lower())
        self.assertNotIn("цит", candidate.recipe.recipe_key.lower())


if __name__ == "__main__":
    unittest.main()
