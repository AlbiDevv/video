from __future__ import annotations

import sys
import unittest

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.utils.validation import ValidationError, validate_variation_count


class ValidationTestCase(unittest.TestCase):
    def test_validate_variation_count_accepts_range(self) -> None:
        self.assertEqual(validate_variation_count(10), 10)
        self.assertEqual(validate_variation_count(20), 20)

    def test_validate_variation_count_rejects_outside_range(self) -> None:
        with self.assertRaises(ValidationError):
            validate_variation_count(9)
        with self.assertRaises(ValidationError):
            validate_variation_count(21)


if __name__ == "__main__":
    unittest.main()
