from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.scheduler.excel_exporter import ExcelExporter
from video_unicalizator.scheduler.schedule_builder import ScheduleBuilder
from video_unicalizator.state import GeneratedVariation
from video_unicalizator.utils.ffmpeg_tools import ffmpeg_available


def main() -> int:
    print(f"FFmpeg available: {ffmpeg_available()}")
    builder = ScheduleBuilder()
    fake_variations = [
        GeneratedVariation(
            source_video=Path("source.mp4"),
            output_video=Path(f"variation_{index}.mp4"),
            quote=f"Quote {index}",
            music_track=None,
            speed_factor=1.0,
            sharpness_score=100.0,
            visual_difference_score=10.0,
        )
        for index in range(3)
    ]
    entries = builder.build(fake_variations)
    assert len(entries) == 3

    with tempfile.TemporaryDirectory() as temp_dir:
        target = Path(temp_dir) / "Расписание_выкладки.xlsx"
        ExcelExporter().export(entries, target)
        assert target.exists()

    print("Smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
