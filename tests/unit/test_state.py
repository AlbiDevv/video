from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.state import (
    AppState,
    MusicClip,
    QuoteClip,
    VideoTimelineProfile,
    cut_timeline_clips_to_range,
    resolve_music_track_bindings,
)


class AppStateTestCase(unittest.TestCase):
    def test_remove_original_updates_selection_and_profiles(self) -> None:
        state = AppState()
        a = Path("a.mp4")
        b = Path("b.mp4")
        c = Path("c.mp4")
        state.media.original_videos = [a, b, c]
        state.selected_video = b
        state.ensure_video_profile(a)
        state.ensure_video_profile(b)
        state.ensure_video_profile(c)

        selected = state.remove_original(b)

        self.assertEqual(state.media.original_videos, [a, c])
        self.assertEqual(selected, c)
        self.assertEqual(state.selected_video, c)
        self.assertNotIn(str(b), state.video_profiles)

    def test_remove_last_original_clears_selection(self) -> None:
        state = AppState()
        a = Path("a.mp4")
        state.media.original_videos = [a]
        state.selected_video = a
        state.ensure_video_profile(a)

        selected = state.remove_original(a)

        self.assertIsNone(selected)
        self.assertIsNone(state.selected_video)
        self.assertEqual(state.media.original_videos, [])

    def test_build_default_profile_uses_layer_sample_defaults(self) -> None:
        state = AppState()
        state.set_default_layer_sample("A", "Первая\nцитата")
        state.set_default_layer_sample("B", "Вторая строка")

        profile = state.build_default_profile()

        self.assertEqual(profile.layer_a.preview_text, "Первая\nцитата")
        self.assertEqual(profile.layer_b.preview_text, "Вторая строка")
        self.assertTrue(profile.layer_a.enabled)
        self.assertTrue(profile.layer_b.enabled)

    def test_ensure_video_profile_inherits_quote_samples_loaded_before_originals(self) -> None:
        state = AppState()
        state.set_default_layer_sample("A", "Цитата A")
        state.set_default_layer_sample("B", "Цитата B")

        profile = state.ensure_video_profile(Path("video.mp4"))

        self.assertEqual(profile.layer_a.preview_text, "Цитата A")
        self.assertEqual(profile.layer_b.preview_text, "Цитата B")


    def test_normalized_profile_creates_default_full_clip_for_enabled_layers(self) -> None:
        state = AppState()
        profile = state.build_default_profile()
        profile.layer_b.enabled = True
        profile.layer_b.preview_text = "Layer B"

        normalized = profile.normalized_for_duration(9.5)

        self.assertEqual(len(normalized.timeline.quote_clips_a), 1)
        self.assertEqual(len(normalized.timeline.quote_clips_b), 1)
        self.assertAlmostEqual(normalized.timeline.quote_clips_a[0].end_sec, 9.5, places=3)
        self.assertAlmostEqual(normalized.timeline.quote_clips_b[0].end_sec, 9.5, places=3)

    def test_normalized_profile_clamps_overlapping_clips_per_lane(self) -> None:
        state = AppState()
        profile = state.build_default_profile()
        profile.timeline.quote_clips_a = [
            QuoteClip(lane="A", start_sec=0.0, end_sec=4.0),
            QuoteClip(lane="A", start_sec=3.0, end_sec=6.0),
        ]
        profile.timeline.music_clips = [
            MusicClip(start_sec=1.0, end_sec=3.0, volume=1.0),
            MusicClip(start_sec=2.5, end_sec=5.0, volume=1.0),
        ]

        normalized = profile.normalized_for_duration(8.0)

        self.assertGreaterEqual(normalized.timeline.quote_clips_a[1].start_sec, normalized.timeline.quote_clips_a[0].end_sec)
        self.assertGreaterEqual(normalized.timeline.music_clips[1].start_sec, normalized.timeline.music_clips[0].end_sec)

    def test_cut_range_removes_clips_fully_inside_window(self) -> None:
        clips = [
            QuoteClip(lane="A", start_sec=0.0, end_sec=1.0),
            QuoteClip(lane="A", start_sec=2.0, end_sec=3.0),
            QuoteClip(lane="A", start_sec=4.0, end_sec=5.0),
        ]

        result = cut_timeline_clips_to_range(clips, start_sec=1.5, end_sec=3.5)

        self.assertEqual([(clip.start_sec, clip.end_sec) for clip in result], [(0.0, 1.0), (4.0, 5.0)])

    def test_cut_range_trims_clip_for_partial_overlap(self) -> None:
        clips = [QuoteClip(lane="A", start_sec=0.0, end_sec=3.0)]

        result = cut_timeline_clips_to_range(clips, start_sec=1.5, end_sec=4.0)

        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].start_sec, 0.0, places=3)
        self.assertAlmostEqual(result[0].end_sec, 1.5, places=3)

    def test_cut_range_splits_clip_and_preserves_quote_fields(self) -> None:
        clip = QuoteClip(lane="B", start_sec=0.0, end_sec=6.0, sample_text="Hello", source_mode="sample")

        result = cut_timeline_clips_to_range([clip], start_sec=2.0, end_sec=4.0)

        self.assertEqual(len(result), 2)
        self.assertEqual([(item.start_sec, item.end_sec) for item in result], [(0.0, 2.0), (4.0, 6.0)])
        self.assertEqual([item.sample_text for item in result], ["Hello", "Hello"])
        self.assertEqual([item.source_mode for item in result], ["sample", "sample"])
        self.assertEqual([item.lane for item in result], ["B", "B"])
        self.assertNotEqual(result[0].clip_id, result[1].clip_id)

    def test_cut_range_splits_music_and_preserves_volume(self) -> None:
        clip = MusicClip(
            start_sec=1.0,
            end_sec=7.0,
            volume=0.45,
            source_mode="sample",
            bound_track=Path("track.mp3"),
            track_offset_sec=2.5,
        )

        result = cut_timeline_clips_to_range([clip], start_sec=3.0, end_sec=5.0)

        self.assertEqual(len(result), 2)
        self.assertEqual([(item.start_sec, item.end_sec) for item in result], [(1.0, 3.0), (5.0, 7.0)])
        self.assertEqual([round(item.volume, 2) for item in result], [0.45, 0.45])
        self.assertEqual([item.source_mode for item in result], ["sample", "sample"])
        self.assertEqual([item.bound_track for item in result], [Path("track.mp3"), Path("track.mp3")])
        self.assertEqual([round(item.track_offset_sec, 2) for item in result], [2.5, 4.5])

    def test_video_timeline_profile_cut_range_updates_all_lanes(self) -> None:
        timeline = VideoTimelineProfile(
            quote_clips_a=[QuoteClip(lane="A", start_sec=0.0, end_sec=4.0)],
            quote_clips_b=[QuoteClip(lane="B", start_sec=1.0, end_sec=5.0)],
            music_clips=[MusicClip(start_sec=2.0, end_sec=6.0, volume=1.0)],
            duration_hint=8.0,
        )

        cut = timeline.cut_range(2.0, 3.0)

        self.assertEqual([(clip.start_sec, clip.end_sec) for clip in cut.quote_clips_a], [(0.0, 2.0), (3.0, 4.0)])
        self.assertEqual([(clip.start_sec, clip.end_sec) for clip in cut.quote_clips_b], [(1.0, 2.0), (3.0, 5.0)])
        self.assertEqual([(clip.start_sec, clip.end_sec) for clip in cut.music_clips], [(3.0, 6.0)])

    def test_cut_range_does_not_count_removed_gap_in_music_offset(self) -> None:
        clip = MusicClip(
            start_sec=0.0,
            end_sec=8.0,
            volume=1.0,
            bound_track=Path("track.mp3"),
            track_offset_sec=10.0,
        )

        result = cut_timeline_clips_to_range([clip], start_sec=2.0, end_sec=5.0)

        self.assertEqual([(item.start_sec, item.end_sec) for item in result], [(0.0, 2.0), (5.0, 8.0)])
        self.assertEqual([round(item.track_offset_sec, 2) for item in result], [10.0, 12.0])

    def test_resolve_music_track_bindings_ignores_singleton_legacy_bound_track(self) -> None:
        clips = [
            MusicClip(
                clip_id="music_a",
                start_sec=0.0,
                end_sec=2.0,
                volume=1.0,
                bound_track=Path("legacy.mp3"),
            ),
            MusicClip(clip_id="music_b", start_sec=2.0, end_sec=4.0, volume=1.0),
        ]

        bindings = resolve_music_track_bindings(
            clips,
            [Path("alpha.mp3"), Path("beta.mp3")],
            preferred_first_track=Path("beta.mp3"),
        )

        self.assertEqual(bindings["music_a"], (Path("beta.mp3"), 0))
        self.assertEqual(bindings["music_b"], (Path("alpha.mp3"), 0))

    def test_resolve_music_track_bindings_keeps_continuity_group_rotating_as_one_pick(self) -> None:
        clips = [
            MusicClip(
                clip_id="music_a",
                start_sec=0.0,
                end_sec=2.0,
                volume=1.0,
                bound_track=Path("legacy.mp3"),
            ),
            MusicClip(
                clip_id="music_b",
                start_sec=3.0,
                end_sec=5.0,
                volume=1.0,
                bound_track=Path("legacy.mp3"),
                track_offset_sec=2.0,
            ),
            MusicClip(clip_id="music_c", start_sec=5.0, end_sec=7.0, volume=1.0),
        ]

        bindings = resolve_music_track_bindings(
            clips,
            [Path("alpha.mp3"), Path("beta.mp3")],
            preferred_first_track=Path("beta.mp3"),
        )

        self.assertEqual(bindings["music_a"], (Path("beta.mp3"), 0))
        self.assertEqual(bindings["music_b"], (Path("beta.mp3"), 0))
        self.assertEqual(bindings["music_c"], (Path("alpha.mp3"), 0))

    def test_resolve_music_track_bindings_preserves_locked_track_and_consumes_pool_slot(self) -> None:
        clips = [
            MusicClip(
                clip_id="music_locked",
                start_sec=0.0,
                end_sec=2.0,
                volume=1.0,
                bound_track=Path("alpha.mp3"),
                track_locked=True,
            ),
            MusicClip(clip_id="music_auto", start_sec=2.0, end_sec=4.0, volume=1.0),
        ]

        bindings = resolve_music_track_bindings(
            clips,
            [Path("alpha.mp3"), Path("beta.mp3")],
            preferred_first_track=Path("alpha.mp3"),
        )

        self.assertEqual(bindings["music_locked"], (Path("alpha.mp3"), 0))
        self.assertEqual(bindings["music_auto"], (Path("beta.mp3"), 0))


if __name__ == "__main__":
    unittest.main()
