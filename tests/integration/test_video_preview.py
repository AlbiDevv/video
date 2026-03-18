from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.state import VideoEditProfile
from video_unicalizator.ui.widgets.video_preview import VideoPreviewWidget
from video_unicalizator.utils.tk_runtime import ensure_tcl_tk_environment

ensure_tcl_tk_environment()
import customtkinter as ctk


class VideoPreviewIntegrationTestCase(unittest.TestCase):
    def test_drag_finish_updates_layer_a_and_b_without_crash(self) -> None:
        app = ctk.CTk()
        self.addCleanup(app.destroy)
        app.geometry("1200x900")

        widget = VideoPreviewWidget(app, on_overlay_change=lambda _layer, _style: None)
        widget.pack(fill="both", expand=True)

        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Layer A"
        profile.layer_a.enabled = True
        profile.layer_b.preview_text = "Layer B"
        profile.layer_b.enabled = True
        widget.load_profile(profile)

        app.update_idletasks()
        app.update()

        old_a_x = widget._profile.layer_a.position_x
        old_b_x = widget._profile.layer_b.position_x

        a_bounds = widget._overlay_a._current_canvas_bounds()
        self.assertTrue(widget._overlay_a.start_interaction(a_bounds.center_x, a_bounds.center_y))
        self.assertTrue(widget._overlay_a.drag_to(a_bounds.center_x + 40, a_bounds.center_y))
        widget._overlay_a.finish_interaction()

        b_bounds = widget._overlay_b._current_canvas_bounds()
        self.assertTrue(widget._overlay_b.start_interaction(b_bounds.center_x, b_bounds.center_y))
        self.assertTrue(widget._overlay_b.drag_to(b_bounds.center_x - 40, b_bounds.center_y))
        widget._overlay_b.finish_interaction()

        self.assertNotEqual(widget._profile.layer_a.position_x, old_a_x)
        self.assertNotEqual(widget._profile.layer_b.position_x, old_b_x)


if __name__ == "__main__":
    unittest.main()
