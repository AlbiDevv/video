from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_unicalizator.state import VideoEditProfile
from video_unicalizator.ui.tabs.text_editor import TextEditorTab
from video_unicalizator.utils.tk_runtime import ensure_tcl_tk_environment

ensure_tcl_tk_environment()
import customtkinter as ctk


class TextEditorIntegrationTestCase(unittest.TestCase):
    def _create_tab(self) -> tuple[ctk.CTk, TextEditorTab]:
        app = ctk.CTk()
        app.geometry("1600x980")
        tab = TextEditorTab(
            app,
            fonts=["Arial", "Bahnschrift"],
            on_load_originals_files=lambda: None,
            on_load_originals_folder=lambda: None,
            on_load_music_files=lambda: None,
            on_load_music_folder=lambda: None,
            on_load_quotes_a_files=lambda: None,
            on_load_quotes_a_folder=lambda: None,
            on_load_quotes_b_files=lambda: None,
            on_load_quotes_b_folder=lambda: None,
            on_choose_output_folder=lambda: None,
            on_apply_style=lambda: None,
            on_generate=lambda: None,
            on_video_selected=lambda _path: None,
            on_profile_changed=lambda _profile, _variation_count, _enhance: None,
            on_overlay_changed=lambda _layer, _style: None,
        )
        tab.pack(fill="both", expand=True)
        app.update_idletasks()
        app.update()
        return app, tab

    def test_drag_layer_a_persists_after_reload_and_control_change(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Layer A"
        profile.layer_a.enabled = True
        profile.layer_b.preview_text = "Layer B"
        profile.layer_b.enabled = True
        tab.load_profile(profile)
        app.update_idletasks()
        app.update()

        bounds = tab.preview._overlay_a._current_canvas_bounds()
        old_x = tab.read_video_profile().layer_a.position_x

        self.assertTrue(tab.preview._overlay_a.start_interaction(bounds.center_x, bounds.center_y))
        self.assertTrue(tab.preview._overlay_a.drag_to(bounds.center_x + 60, bounds.center_y))
        tab.preview._overlay_a.finish_interaction()
        app.update_idletasks()
        app.update()

        moved_profile = tab.read_video_profile()
        self.assertNotEqual(moved_profile.layer_a.position_x, old_x)

        section = tab.layer_sections["A"]
        new_size = moved_profile.layer_a.font_size + 4
        section.font_size_slider.set(new_size)
        tab._on_font_size_changed("A", new_size)

        after_control_change = tab.read_video_profile()
        self.assertAlmostEqual(after_control_change.layer_a.position_x, moved_profile.layer_a.position_x, places=4)
        self.assertAlmostEqual(after_control_change.layer_a.position_y, moved_profile.layer_a.position_y, places=4)

        tab.load_profile(after_control_change)
        reloaded = tab.read_video_profile()
        self.assertAlmostEqual(reloaded.layer_a.position_x, moved_profile.layer_a.position_x, places=4)
        self.assertAlmostEqual(reloaded.layer_a.position_y, moved_profile.layer_a.position_y, places=4)

    def test_drag_layer_b_does_not_reset_layer_a(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Top"
        profile.layer_a.enabled = True
        profile.layer_b.preview_text = "Bottom"
        profile.layer_b.enabled = True
        tab.load_profile(profile)
        app.update_idletasks()
        app.update()

        a_before = tab.read_video_profile().layer_a.position_x
        b_bounds = tab.preview._overlay_b._current_canvas_bounds()
        self.assertTrue(tab.preview._overlay_b.start_interaction(b_bounds.center_x, b_bounds.center_y))
        self.assertTrue(tab.preview._overlay_b.drag_to(b_bounds.center_x - 50, b_bounds.center_y))
        tab.preview._overlay_b.finish_interaction()
        app.update_idletasks()
        app.update()

        current = tab.read_video_profile()
        self.assertAlmostEqual(current.layer_a.position_x, a_before, places=4)
        self.assertNotEqual(current.layer_b.position_x, profile.layer_b.position_x)

    def test_set_quote_sample_updates_multiline_text_immediately(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        quote = "Первая строка\nВторая строка"
        tab.set_quote_sample("A", quote)

        self.assertEqual(tab.layer_sections["A"].sample_quote_box.get("1.0", "end-1c"), quote)
        self.assertEqual(tab.read_video_profile().layer_a.preview_text, quote)

    def test_loading_music_tracks_creates_clip_at_current_playhead_for_selected_video(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        tab._selected_video_path = Path("video.mp4")
        tab._current_duration = 9.0
        tab.preview._playhead_sec = 1.75
        tab.load_profile(VideoEditProfile().normalized_for_duration(9.0))

        tab.set_music_tracks([Path("track_a.mp3"), Path("track_b.mp3")])
        profile = tab.read_video_profile()

        self.assertEqual(len(profile.timeline.music_clips), 1)
        self.assertAlmostEqual(profile.timeline.music_clips[0].start_sec, 1.75, places=2)
        self.assertEqual(tab._selected_clip_lane, "Music")
        self.assertEqual(tab._selected_clip_id, profile.timeline.music_clips[0].clip_id)


if __name__ == "__main__":
    unittest.main()
