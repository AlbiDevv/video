from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.state import MusicClip, QuoteClip, VideoTimelineProfile
from video_unicalizator.ui.widgets.timeline_editor import TimelineEditorWidget
from video_unicalizator.utils.tk_runtime import ensure_tcl_tk_environment

ensure_tcl_tk_environment()
import customtkinter as ctk


class TimelineEditorIntegrationTestCase(unittest.TestCase):
    def test_scroll_to_end_persists_after_redraw_and_playhead_updates(self) -> None:
        app = ctk.CTk()
        self.addCleanup(app.destroy)
        app.geometry("1500x900")

        widget = TimelineEditorWidget(
            app,
            on_timeline_change=lambda _timeline: None,
            on_playhead_change=lambda _seconds: None,
            on_lane_focus=lambda _lane: None,
        )
        widget.pack(fill="both", expand=True)
        app.update_idletasks()
        app.update()

        timeline = VideoTimelineProfile(
            music_clips=[MusicClip(start_sec=18.0, end_sec=22.0, volume=1.0)],
            duration_hint=24.0,
        )
        widget.load_timeline(timeline, duration=24.0)
        app.update_idletasks()
        app.update()

        widget.scroll_to_end()
        app.update_idletasks()
        app.update()
        left_before = widget.read_view_state()[1]

        widget.set_playhead(23.5, notify=False)
        widget._redraw()
        app.update_idletasks()
        app.update()
        left_after = widget.read_view_state()[1]

        self.assertGreater(left_before, 0.0)
        self.assertAlmostEqual(left_after, left_before, places=1)

    def test_split_selected_clip_cuts_only_selected_block(self) -> None:
        app = ctk.CTk()
        self.addCleanup(app.destroy)
        app.geometry("1500x900")

        snapshots: list[VideoTimelineProfile] = []
        widget = TimelineEditorWidget(
            app,
            on_timeline_change=lambda timeline: snapshots.append(timeline),
            on_playhead_change=lambda _seconds: None,
            on_lane_focus=lambda _lane: None,
        )
        widget.pack(fill="both", expand=True)
        app.update_idletasks()
        app.update()

        timeline = VideoTimelineProfile(
            quote_clips_a=[QuoteClip(lane="A", start_sec=0.0, end_sec=8.0)],
            quote_clips_b=[QuoteClip(lane="B", start_sec=1.0, end_sec=7.0)],
            music_clips=[MusicClip(start_sec=2.0, end_sec=6.0, volume=0.8)],
            duration_hint=10.0,
        )
        widget.load_timeline(timeline, duration=10.0)
        widget.set_playhead(4.0, notify=False)
        clip_id = widget.read_timeline().quote_clips_a[0].clip_id
        widget.select_clip("A", clip_id)
        app.update_idletasks()
        app.update()

        widget.split_selected_clip()
        app.update_idletasks()
        app.update()

        current = widget.read_timeline()
        self.assertEqual([(clip.start_sec, clip.end_sec) for clip in current.quote_clips_a], [(0.0, 4.0), (4.0, 8.0)])
        self.assertEqual([(clip.start_sec, clip.end_sec) for clip in current.quote_clips_b], [(1.0, 7.0)])
        self.assertEqual([(clip.start_sec, clip.end_sec) for clip in current.music_clips], [(2.0, 6.0)])
        self.assertEqual(widget._selected_lane, "A")
        self.assertIsNotNone(widget._selected_clip_id)
        self.assertTrue(snapshots)

    def test_split_button_enabled_only_when_playhead_inside_selected_clip(self) -> None:
        app = ctk.CTk()
        self.addCleanup(app.destroy)
        app.geometry("1500x900")

        widget = TimelineEditorWidget(
            app,
            on_timeline_change=lambda _timeline: None,
            on_playhead_change=lambda _seconds: None,
            on_lane_focus=lambda _lane: None,
        )
        widget.pack(fill="both", expand=True)
        app.update_idletasks()
        app.update()

        widget.load_timeline(
            VideoTimelineProfile(quote_clips_a=[QuoteClip(lane="A", start_sec=1.0, end_sec=6.0)], duration_hint=10.0),
            duration=10.0,
        )
        clip_id = widget.read_timeline().quote_clips_a[0].clip_id
        widget.select_clip("A", clip_id)
        widget.set_playhead(3.0, notify=False)
        app.update_idletasks()
        app.update()
        self.assertEqual(widget.cut_button.cget("state"), "normal")

        widget.set_playhead(1.0, notify=False)
        app.update_idletasks()
        app.update()
        self.assertEqual(widget.cut_button.cget("state"), "disabled")


if __name__ == "__main__":
    unittest.main()
