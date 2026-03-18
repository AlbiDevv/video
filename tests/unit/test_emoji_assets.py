from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.utils.emoji_assets import resolve_emoji_asset


class EmojiAssetsTestCase(unittest.TestCase):
    def test_resolve_known_twemoji_assets(self) -> None:
        cool = resolve_emoji_asset("\U0001F60E")
        fire = resolve_emoji_asset("\U0001F525")
        self.assertIsNotNone(cool)
        self.assertIsNotNone(fire)
        self.assertTrue(cool.exists())
        self.assertTrue(fire.exists())


if __name__ == "__main__":
    unittest.main()
