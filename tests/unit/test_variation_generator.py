from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.core.quality_checker import QualityReport
from video_unicalizator.core.variation_generator import (
    RenderAttempt,
    UniquenessExhaustedError,
    VariationGenerator,
)
from video_unicalizator.core.video_processor import VariationProfile
from video_unicalizator.state import (
    AppState,
    GenerationCancelToken,
    MusicClip,
    QuoteClip,
    RenderedMusicAssignment,
    VideoEditProfile,
)


class VariationGeneratorTestCase(unittest.TestCase):
    def test_resolve_quote_pools_fall_back_to_profile_text(self) -> None:
        state = AppState()
        state.text_style.preview_text = "Legacy fallback"
        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Текст A"
        profile.layer_b.preview_text = "Текст B"
        profile.layer_b.enabled = True

        primary, secondary = VariationGenerator()._resolve_quote_pools(state, profile)

        self.assertEqual(primary, ["Текст A"])
        self.assertEqual(secondary, ["Текст B"])

    def test_resolve_quote_pools_allow_empty_layer(self) -> None:
        state = AppState()
        profile = VideoEditProfile()
        profile.layer_a.preview_text = "   "
        profile.layer_b.preview_text = "   "
        profile.layer_b.enabled = False

        primary, secondary = VariationGenerator()._resolve_quote_pools(state, profile)

        self.assertEqual(primary, [])
        self.assertEqual(secondary, [])

    def test_generate_continues_after_single_variation_error(self) -> None:
        state = AppState()
        state.media.original_videos = [Path("source.mp4")]
        state.generation.variation_count = 2

        generator = VariationGenerator()
        side_effects = [
            RuntimeError("render failed"),
            RenderAttempt(
                output_video=Path("output_ok.mp4"),
                profile=VariationProfile(
                    speed_factor=1.0,
                    brightness_shift=0.0,
                    contrast_shift=0.0,
                    saturation_shift=0.0,
                    filter_preset="neutral_contrast",
                    trim_start=0.0,
                    trim_end=0.0,
                    output_duration=5.2,
                    target_duration=5.2,
                    music_cycle_index=0,
                ),
                report=QualityReport(
                    sharpness_score=100.0,
                    visual_difference_score=10.0,
                    format_ok=True,
                    duration_seconds=5.2,
                    duration_unique=True,
                    warnings=[],
                ),
                primary_quote="quote A",
                secondary_quote="quote B",
                music_track=None,
                snapshot=None,
            ),
        ]

        with (
            patch.object(generator, "_validate_state", return_value=None),
            patch.object(generator.quality_checker, "inspect_video", return_value=(1080, 1920, 6.0)),
            patch.object(generator, "_render_with_quality_gate", side_effect=side_effects),
        ):
            generated = generator.generate(state)

        self.assertEqual(len(generated), 1)
        self.assertEqual(generator.last_summary.failed_count, 1)
        self.assertEqual(generator.last_summary.success_count, 1)

    def test_generate_stops_after_cancel_request(self) -> None:
        state = AppState()
        state.media.original_videos = [Path("source.mp4")]
        state.generation.variation_count = 3

        generator = VariationGenerator()
        cancel_token = GenerationCancelToken()
        render_attempt = RenderAttempt(
            output_video=Path("output_ok.mp4"),
            profile=VariationProfile(
                speed_factor=1.0,
                brightness_shift=0.0,
                contrast_shift=0.0,
                saturation_shift=0.0,
                filter_preset="neutral_contrast",
                trim_start=0.0,
                trim_end=0.0,
                output_duration=5.2,
                target_duration=5.2,
                music_cycle_index=0,
            ),
            report=QualityReport(
                sharpness_score=100.0,
                visual_difference_score=10.0,
                format_ok=True,
                duration_seconds=5.2,
                duration_unique=True,
                warnings=[],
            ),
            primary_quote="quote A",
            secondary_quote="quote B",
            music_track=None,
            snapshot=None,
        )
        calls = {"count": 0}

        def render_side_effect(**_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                cancel_token.cancel()
                return render_attempt
            raise AssertionError("Generator should not start a new variation after cancellation.")

        with (
            patch.object(generator, "_validate_state", return_value=None),
            patch.object(generator.quality_checker, "inspect_video", return_value=(1080, 1920, 6.0)),
            patch.object(generator, "_render_with_quality_gate", side_effect=render_side_effect),
        ):
            generated = generator.generate(state, cancel_token=cancel_token)

        self.assertEqual(len(generated), 1)
        self.assertTrue(generator.last_summary.cancelled)
        self.assertEqual(generator.last_summary.success_count, 1)

    def test_generate_marks_remaining_variations_skipped_when_uniqueness_exhausted(self) -> None:
        state = AppState()
        state.media.original_videos = [Path("source.mp4")]
        state.generation.variation_count = 3

        generator = VariationGenerator()
        first_attempt = RenderAttempt(
            output_video=Path("output_ok.mp4"),
            profile=VariationProfile(
                speed_factor=1.0,
                brightness_shift=0.0,
                contrast_shift=0.0,
                saturation_shift=0.0,
                filter_preset="neutral_contrast",
                trim_start=0.0,
                trim_end=0.0,
                output_duration=5.2,
                target_duration=5.2,
            ),
            report=QualityReport(
                sharpness_score=100.0,
                visual_difference_score=10.0,
                format_ok=True,
                duration_seconds=5.2,
                duration_unique=True,
                warnings=[],
            ),
            primary_quote="quote A",
            secondary_quote="quote B",
            music_track=None,
            snapshot=None,
        )

        with (
            patch.object(generator, "_validate_state", return_value=None),
            patch.object(generator.quality_checker, "inspect_video", return_value=(1080, 1920, 6.0)),
            patch.object(
                generator,
                "_render_with_quality_gate",
                side_effect=[first_attempt, UniquenessExhaustedError("space exhausted")],
            ),
        ):
            generated = generator.generate(state)

        self.assertEqual(len(generated), 1)
        self.assertEqual(generator.last_summary.success_count, 1)
        self.assertEqual(generator.last_summary.skipped_uniqueness_count, 2)

    def test_build_quote_segments_uses_unused_quotes_before_repeat(self) -> None:
        generator = VariationGenerator()
        profile = VideoEditProfile().normalized_for_duration(8.0)
        profile.timeline.quote_clips_a = [
            QuoteClip(lane="A", start_sec=0.0, end_sec=2.0),
            QuoteClip(lane="A", start_sec=3.0, end_sec=5.0),
        ]
        variation_profile = VariationProfile(
            speed_factor=1.0,
            brightness_shift=0.0,
            contrast_shift=0.0,
            saturation_shift=0.0,
            filter_preset="neutral_contrast",
            trim_start=0.0,
            trim_end=0.0,
            output_duration=8.0,
            target_duration=8.0,
        )

        with patch("random.choice", side_effect=lambda options: options[0]):
            segments = generator._build_quote_segments(
                profile=profile,
                variation_profile=variation_profile,
                source_duration=8.0,
                primary_pool=["A1", "A2", "A3"],
                secondary_pool=[],
            )

        self.assertEqual([segment.assignment.text for segment in segments], ["A1", "A2"])

    def test_build_music_segments_uses_different_tracks_inside_one_video_when_possible(self) -> None:
        generator = VariationGenerator()
        clips = [
            MusicClip(start_sec=0.0, end_sec=2.0, volume=1.0),
            MusicClip(start_sec=3.0, end_sec=5.0, volume=1.0),
        ]
        variation_profile = VariationProfile(
            speed_factor=1.0,
            brightness_shift=0.0,
            contrast_shift=0.0,
            saturation_shift=0.0,
            filter_preset="neutral_contrast",
            trim_start=0.0,
            trim_end=0.0,
            output_duration=8.0,
            target_duration=8.0,
        )

        with patch("pathlib.Path.exists", return_value=True):
            assignments = generator._build_music_segments(
                timeline_clips=clips,
                variation_profile=variation_profile,
                source_duration=8.0,
                music_tracks=[Path("a.mp3"), Path("b.mp3"), Path("c.mp3")],
                preferred_track=Path("b.mp3"),
            )

        self.assertEqual(assignments[0].track, Path("b.mp3"))
        self.assertNotEqual(assignments[0].track, assignments[1].track)

    def test_build_music_segments_uses_bound_track_and_offset_for_split_clip(self) -> None:
        generator = VariationGenerator()
        clips = [
            MusicClip(
                clip_id="music_a",
                start_sec=0.0,
                end_sec=2.0,
                volume=1.0,
                bound_track=Path("bound.mp3"),
                track_offset_sec=6.5,
            ),
            MusicClip(
                clip_id="music_b",
                start_sec=4.0,
                end_sec=6.0,
                volume=1.0,
                bound_track=Path("bound.mp3"),
                track_offset_sec=8.5,
            ),
        ]
        variation_profile = VariationProfile(
            speed_factor=1.0,
            brightness_shift=0.0,
            contrast_shift=0.0,
            saturation_shift=0.0,
            filter_preset="neutral_contrast",
            trim_start=0.0,
            trim_end=0.0,
            output_duration=8.0,
            target_duration=8.0,
        )

        with patch("pathlib.Path.exists", return_value=True):
            assignments = generator._build_music_segments(
                timeline_clips=clips,
                variation_profile=variation_profile,
                source_duration=8.0,
                music_tracks=[Path("other.mp3"), Path("bound.mp3")],
                preferred_track=Path("other.mp3"),
            )

        self.assertEqual([assignment.track for assignment in assignments], [Path("other.mp3"), Path("other.mp3")])
        self.assertEqual([round(assignment.track_offset_sec, 2) for assignment in assignments], [6.5, 8.5])

    def test_build_music_segments_preserves_locked_bound_track(self) -> None:
        generator = VariationGenerator()
        clips = [
            MusicClip(
                clip_id="music_locked",
                start_sec=0.0,
                end_sec=2.0,
                volume=1.0,
                bound_track=Path("bound.mp3"),
                track_locked=True,
                track_offset_sec=2.25,
            ),
            MusicClip(
                clip_id="music_auto",
                start_sec=2.0,
                end_sec=4.0,
                volume=1.0,
            ),
        ]
        variation_profile = VariationProfile(
            speed_factor=1.0,
            brightness_shift=0.0,
            contrast_shift=0.0,
            saturation_shift=0.0,
            filter_preset="neutral_contrast",
            trim_start=0.0,
            trim_end=0.0,
            output_duration=8.0,
            target_duration=8.0,
        )

        with patch("pathlib.Path.exists", return_value=True):
            assignments = generator._build_music_segments(
                timeline_clips=clips,
                variation_profile=variation_profile,
                source_duration=8.0,
                music_tracks=[Path("bound.mp3"), Path("other.mp3")],
                preferred_track=Path("other.mp3"),
            )

        self.assertEqual([assignment.track for assignment in assignments], [Path("bound.mp3"), Path("other.mp3")])
        self.assertEqual([assignment.track_locked for assignment in assignments], [True, False])

    def test_generate_advances_music_rotation_once_per_auto_track_cycle_pair(self) -> None:
        state = AppState()
        state.media.original_videos = [Path("source.mp4")]
        state.media.music_tracks = [Path("a.mp3"), Path("b.mp3")]
        state.output_dir = Path("outputs")
        state.generation.variation_count = 1
        state.generation.render_retry_attempts = 1
        profile = state.ensure_video_profile(Path("source.mp4")).normalized_for_duration(8.0)
        profile.timeline.music_clips = [
            MusicClip(clip_id="m1", start_sec=0.0, end_sec=2.0, volume=1.0),
            MusicClip(clip_id="m2", start_sec=2.0, end_sec=4.0, volume=1.0),
        ]
        state.video_profiles[str(Path("source.mp4"))] = profile

        generator = VariationGenerator()
        attempt = RenderAttempt(
            output_video=Path("outputs/source_v1.mp4"),
            profile=VariationProfile(
                speed_factor=1.0,
                brightness_shift=0.0,
                contrast_shift=0.0,
                saturation_shift=0.0,
                filter_preset="neutral_contrast",
                trim_start=0.0,
                trim_end=0.0,
                output_duration=8.0,
                target_duration=8.0,
                music_cycle_index=0,
            ),
            report=QualityReport(
                sharpness_score=100.0,
                visual_difference_score=10.0,
                format_ok=True,
                duration_seconds=8.0,
                duration_unique=True,
                warnings=[],
            ),
            primary_quote="",
            secondary_quote="",
            music_track=Path("a.mp3"),
            snapshot=None,
            music_assignments=[
                RenderedMusicAssignment(
                    clip_id="m1",
                    track=Path("a.mp3"),
                    start_sec=0.0,
                    end_sec=2.0,
                    volume=1.0,
                    cycle_index=0,
                    track_locked=False,
                ),
                RenderedMusicAssignment(
                    clip_id="m2",
                    track=Path("a.mp3"),
                    start_sec=2.0,
                    end_sec=4.0,
                    volume=1.0,
                    cycle_index=0,
                    track_locked=False,
                ),
            ],
        )

        with (
            patch("video_unicalizator.core.variation_generator.ffmpeg_available", return_value=(True, "")),
            patch.object(generator.quality_checker, "inspect_video", return_value=(1080, 1920, 8.0)),
            patch.object(generator, "_resolve_quote_pools", return_value=([], [])),
            patch.object(generator, "_render_with_quality_gate", return_value=attempt),
        ):
            generated = generator.generate(state)

        self.assertEqual(len(generated), 1)
        self.assertEqual(generator._music_pick_count, 1)


if __name__ == "__main__":
    unittest.main()
