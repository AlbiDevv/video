from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.scheduler.excel_exporter import ExcelExporter
from video_unicalizator.state import ScheduleEntry


class SmokeIntegrationTestCase(unittest.TestCase):
    def test_excel_export_creates_file(self) -> None:
        entries = [
            ScheduleEntry(file_name="video_01.mp4", publish_time="2026-01-01 09:00"),
            ScheduleEntry(file_name="video_02.mp4", publish_time="2026-01-01 11:00"),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "schedule.xlsx"
            ExcelExporter().export(entries, target)
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
