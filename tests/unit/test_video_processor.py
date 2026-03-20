from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.core.video_processor import VariationProfile, VideoProcessor
from video_unicalizator.state import RenderedMusicAssignment
from video_unicalizator.utils.ffmpeg_tools import MediaProbeInfo


class VideoProcessorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.processor = VideoProcessor()
        self.profile = VariationProfile(
            speed_factor=1.0,
            brightness_shift=0.0,
            contrast_shift=0.0,
            saturation_shift=0.0,
            filter_preset="neutral_contrast",
            trim_start=0.0,
            trim_end=0.0,
            output_duration=6.0,
            target_duration=6.0,
        )

    def test_build_command_includes_music_input_and_amix_for_source_audio(self) -> None:
        assignment = RenderedMusicAssignment(
            clip_id="music_1",
            track=Path("track.mp3"),
            start_sec=1.0,
            end_sec=3.5,
            volume=0.5,
            track_offset_sec=4.25,
        )
        command = self.processor._build_command(
            ffmpeg_path="ffmpeg",
            source_video=Path("source.mp4"),
            quote_inputs=[],
            music_segments=[assignment],
            music_volume=1.2,
            output_video=Path("out.mp4"),
            profile=self.profile,
            media_info=MediaProbeInfo(width=1080, height=1920, duration=6.0, fps=30.0, has_audio=True),
            enhance_sharpness=False,
        )

        self.assertIn(str(Path("track.mp3")), command)
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("[1:a]volume=0.6000", filter_complex)
        self.assertIn("atrim=start=4.2500:duration=2.5000", filter_complex)
        self.assertIn("[music0]anull[musicbus]", filter_complex)
        self.assertIn("[voice][musicbus]amix=inputs=2:normalize=0:duration=longest[aout]", filter_complex)
        self.assertIn("[aout]", command)

    def test_build_filter_complex_uses_music_bus_without_source_audio(self) -> None:
        assignment = RenderedMusicAssignment(
            clip_id="music_1",
            track=Path("track.mp3"),
            start_sec=0.5,
            end_sec=2.0,
            volume=0.8,
            track_offset_sec=7.0,
        )

        filter_complex, audio_label = self.processor._build_filter_complex(
            quote_inputs=[],
            music_inputs=[(1, assignment)],
            music_volume=1.0,
            profile=self.profile,
            media_info=MediaProbeInfo(width=1080, height=1920, duration=6.0, fps=30.0, has_audio=False),
            enhance_sharpness=False,
        )

        self.assertEqual(audio_label, "aout")
        self.assertIn("[1:a]volume=0.8000", filter_complex)
        self.assertIn("atrim=start=7.0000:duration=1.5000", filter_complex)
        self.assertIn("[music0]anull[musicbus]", filter_complex)
        self.assertIn("[musicbus]anull[aout]", filter_complex)
        self.assertNotIn("[0:a]", filter_complex)

    def test_build_filter_complex_always_uses_center_cover_crop(self) -> None:
        profile = VariationProfile(
            speed_factor=1.0,
            brightness_shift=0.0,
            contrast_shift=0.0,
            saturation_shift=0.0,
            filter_preset="neutral_contrast",
            trim_start=0.0,
            trim_end=0.0,
            output_duration=6.0,
            target_duration=6.0,
            crop_family="tight_crop",
            crop_anchor="top",
        )

        filter_complex, _audio_label = self.processor._build_filter_complex(
            quote_inputs=[],
            music_inputs=[],
            music_volume=1.0,
            profile=profile,
            media_info=MediaProbeInfo(width=1280, height=720, duration=6.0, fps=30.0, has_audio=False),
            enhance_sharpness=False,
        )

        self.assertIn("scale=1080:1920:force_original_aspect_ratio=increase", filter_complex)
        self.assertIn("crop=1080:1920:x=(in_w-out_w)/2:y=(in_h-out_h)/2", filter_complex)
        self.assertNotIn(":y=0", filter_complex)
        self.assertNotIn(":y=in_h-out_h", filter_complex)


if __name__ == "__main__":
    unittest.main()
