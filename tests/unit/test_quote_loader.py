from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.services.quote_loader import load_quotes, load_quotes_from_files


class QuoteLoaderTestCase(unittest.TestCase):
    def test_load_quotes_supports_cp1251(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "quotes.txt"
            path.write_text("Привет\nМир\n\nНовая цитата", encoding="cp1251")
            self.assertEqual(load_quotes(path), ["Привет\nМир", "Новая цитата"])

    def test_load_quotes_preserves_internal_line_breaks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "quotes.txt"
            path.write_text("Первая строка\nВторая строка\n\nОдиночная цитата", encoding="utf-8")
            self.assertEqual(load_quotes(path), ["Первая строка\nВторая строка", "Одиночная цитата"])

    def test_load_quotes_from_multiple_files_merges_quote_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "q1.txt"
            second = Path(temp_dir) / "q2.txt"
            first.write_text("Одна\n\nДве строки\nв одном блоке", encoding="utf-8")
            second.write_text("Три", encoding="utf-8")
            self.assertEqual(load_quotes_from_files([first, second]), ["Одна", "Две строки\nв одном блоке", "Три"])


if __name__ == "__main__":
    unittest.main()
