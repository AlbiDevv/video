from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.state import MusicClip, VideoTimelineProfile
from video_unicalizator.ui.preview_support import PreviewAudioCache, assign_preview_music_clips


class PreviewSupportTestCase(unittest.TestCase):
    def test_assign_preview_music_clips_uses_all_tracks_before_repeat(self) -> None:
        clips = [
            MusicClip(clip_id="c1", start_sec=0.0, end_sec=1.0, volume=1.0),
            MusicClip(clip_id="c2", start_sec=1.0, end_sec=2.0, volume=1.0),
            MusicClip(clip_id="c3", start_sec=2.0, end_sec=3.0, volume=1.0),
        ]
        tracks = [Path("one.mp3"), Path("two.mp3")]
        assignments = assign_preview_music_clips(clips, tracks)
        self.assertEqual([item.track for item in assignments], [tracks[0], tracks[1], tracks[0]])
        self.assertEqual([item.cycle_index for item in assignments], [0, 0, 1])

    def test_assign_preview_music_clips_preserves_bound_track_and_offset(self) -> None:
        clips = [
            MusicClip(
                clip_id="c1",
                start_sec=0.0,
                end_sec=2.0,
                volume=1.0,
                bound_track=Path("bound.mp3"),
                track_locked=True,
                track_offset_sec=4.25,
            ),
            MusicClip(clip_id="c2", start_sec=2.0, end_sec=4.0, volume=1.0),
        ]

        assignments = assign_preview_music_clips(clips, [Path("other.mp3"), Path("next.mp3")])

        self.assertEqual(assignments[0].track, Path("bound.mp3"))
        self.assertAlmostEqual(assignments[0].track_offset_sec, 4.25, places=2)
        self.assertEqual(assignments[1].track, Path("other.mp3"))

    def test_assign_preview_music_clips_ignores_legacy_singleton_bound_track_for_rotation(self) -> None:
        clips = [
            MusicClip(
                clip_id="c1",
                start_sec=0.0,
                end_sec=2.0,
                volume=1.0,
                bound_track=Path("legacy.mp3"),
                track_offset_sec=1.5,
            ),
            MusicClip(clip_id="c2", start_sec=2.0, end_sec=4.0, volume=1.0),
        ]

        assignments = assign_preview_music_clips(clips, [Path("other.mp3"), Path("next.mp3")])

        self.assertEqual([item.track for item in assignments], [Path("other.mp3"), Path("next.mp3")])
        self.assertAlmostEqual(assignments[0].track_offset_sec, 1.5, places=2)

    def test_preview_audio_cache_returns_none_without_source_video(self) -> None:
        cache = PreviewAudioCache()
        result = cache.get_or_create(
            source_video=None,
            timeline=VideoTimelineProfile(),
            music_tracks=[],
            music_preview_enabled=True,
            music_preview_volume=1.0,
        )
        self.assertIsNone(result)

    def test_preview_audio_cache_reports_unavailable_without_source_video(self) -> None:
        cache = PreviewAudioCache()
        state = cache.state_for(
            source_video=None,
            timeline=VideoTimelineProfile(),
            music_tracks=[],
            music_preview_enabled=True,
            music_preview_volume=1.0,
        )
        self.assertEqual(state, "unavailable")


if __name__ == "__main__":
    unittest.main()
