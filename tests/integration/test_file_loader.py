from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.services.file_loader import (
    load_music_tracks_from_folder,
    load_original_videos_from_folder,
    load_quote_files_from_folder,
)
from video_unicalizator.utils.temp_paths import project_temporary_directory


class FileLoaderIntegrationTestCase(unittest.TestCase):
    def test_folder_loaders_collect_supported_files(self) -> None:
        with project_temporary_directory(prefix="test_loader_", subdir="tests") as root:
            originals = root / "originals"
            music = root / "music"
            quotes = root / "quotes"
            originals.mkdir()
            music.mkdir()
            quotes.mkdir()

            (originals / "a.mp4").write_bytes(b"mp4")
            (music / "b.mp3").write_bytes(b"mp3")
            (quotes / "c.txt").write_text("quote", encoding="utf-8")

            self.assertEqual(len(load_original_videos_from_folder(str(originals))), 1)
            self.assertEqual(len(load_music_tracks_from_folder(str(music))), 1)
            self.assertEqual(len(load_quote_files_from_folder(str(quotes))), 1)


if __name__ == "__main__":
    unittest.main()
