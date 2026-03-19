from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.state import MusicClip, VideoTimelineProfile
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


if __name__ == "__main__":
    unittest.main()
