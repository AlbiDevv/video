from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.utils import ffmpeg_tools
from video_unicalizator.utils.temp_paths import project_temporary_directory


class FfmpegToolsTestCase(unittest.TestCase):
    def test_probe_media_uses_cache_and_no_window_creationflags(self) -> None:
        with project_temporary_directory(prefix="test_ffmpeg_", subdir="tests") as tmpdir:
            media_path = tmpdir / "sample.mp4"
            media_path.write_bytes(b"fake")
            payload = {
                "streams": [
                    {
                        "codec_type": "video",
                        "width": 1080,
                        "height": 1920,
                        "avg_frame_rate": "30/1",
                        "duration": "5.0",
                    },
                    {"codec_type": "audio"},
                ],
                "format": {"duration": "5.0"},
            }
            completed = Mock(stdout=json.dumps(payload))

            with patch.object(ffmpeg_tools, "ensure_ffmpeg_environment", return_value=("ffmpeg", "ffprobe")), patch(
                "video_unicalizator.utils.ffmpeg_tools.subprocess.run",
                return_value=completed,
            ) as run_mock:
                first = ffmpeg_tools.probe_media(media_path)
                second = ffmpeg_tools.probe_media(media_path)

            self.assertEqual(run_mock.call_count, 1)
            self.assertEqual(first.width, 1080)
            self.assertEqual(first.height, 1920)
            self.assertTrue(first.has_audio)
            self.assertEqual(second.duration, 5.0)
            self.assertEqual(
                run_mock.call_args.kwargs.get("creationflags"),
                ffmpeg_tools.no_window_creationflags(),
            )

    def test_probe_export_metadata_parses_tags_and_chapters(self) -> None:
        with project_temporary_directory(prefix="test_ffmpeg_", subdir="tests") as tmpdir:
            media_path = tmpdir / "sample.mp4"
            media_path.write_bytes(b"fake")
            payload = {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "tags": {"creation_time": "2026-03-26T12:00:00Z"},
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
                "format": {
                    "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                    "duration": "5.0",
                    "tags": {"creation_time": "2026-03-26T12:00:00Z", "encoder": "Lavf"},
                },
                "chapters": [{"id": 0}],
            }
            completed = Mock(stdout=json.dumps(payload))

            with patch.object(ffmpeg_tools, "ensure_ffmpeg_environment", return_value=("ffmpeg", "ffprobe")), patch(
                "video_unicalizator.utils.ffmpeg_tools.subprocess.run",
                return_value=completed,
            ) as run_mock:
                probe = ffmpeg_tools.probe_export_metadata(media_path)

            self.assertEqual(run_mock.call_count, 1)
            self.assertEqual(probe.format_name, "mov,mp4,m4a,3gp,3g2,mj2")
            self.assertEqual(probe.video_codec, "h264")
            self.assertEqual(probe.audio_codec, "aac")
            self.assertEqual(probe.creation_time, "2026-03-26T12:00:00Z")
            self.assertEqual(probe.chapter_count, 1)
            self.assertEqual(probe.format_tags["encoder"], "Lavf")


if __name__ == "__main__":
    unittest.main()
