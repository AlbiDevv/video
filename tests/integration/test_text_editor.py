from __future__ import annotations

import sys
from types import SimpleNamespace
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
    def _create_tab(self, **tab_kwargs) -> tuple[ctk.CTk, TextEditorTab]:
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
            **tab_kwargs,
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
        self.assertEqual(profile.timeline.music_clips[0].bound_track, Path("track_a.mp3"))
        self.assertEqual(tab._selected_clip_lane, "Music")
        self.assertEqual(tab._selected_clip_id, profile.timeline.music_clips[0].clip_id)

    def test_music_preview_volume_callback_updates_master_volume(self) -> None:
        callback_values: list[float] = []
        app, tab = self._create_tab(on_music_master_volume_changed=lambda value: callback_values.append(value))
        self.addCleanup(app.destroy)

        tab.preview.set_music_preview_settings(volume=0.68, notify=True)

        self.assertAlmostEqual(tab.read_music_master_volume(), 0.68, places=2)
        self.assertTrue(callback_values)
        self.assertAlmostEqual(callback_values[-1], 0.68, places=2)

    def test_workspace_state_clears_legacy_selected_time_range(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        video_path = Path("video.mp4")
        tab._selected_video_path = video_path
        tab._current_duration = 12.0
        tab.preview._duration_sec = 12.0
        tab.load_profile(VideoEditProfile().normalized_for_duration(12.0))
        tab.timeline.set_time_range(2.0, 4.5)
        tab._capture_workspace_state()

        tab._video_workspace_state[str(video_path)].selected_range_start_sec = 2.0
        tab._video_workspace_state[str(video_path)].selected_range_end_sec = 4.5
        tab._restore_workspace_state()

        self.assertEqual(tab.timeline.read_time_range(), (None, None))

    def test_editor_shortcut_splits_selected_clip_outside_timeline_focus(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Layer A"
        profile.layer_a.enabled = True
        tab.load_profile(profile.normalized_for_duration(10.0))
        clip_id = tab.read_video_profile().timeline.quote_clips_a[0].clip_id
        tab.timeline.select_clip("A", clip_id)
        tab.timeline.set_playhead(4.0, notify=False)
        tab.generate_button.focus_set()
        app.update_idletasks()
        app.update()

        result = tab._dispatch_editor_hotkeys(SimpleNamespace(widget=tab.generate_button, char="x", keysym="x", state=0))
        current = tab.read_video_profile().timeline

        self.assertEqual(result, "break")
        self.assertEqual([(clip.start_sec, clip.end_sec) for clip in current.quote_clips_a], [(0.0, 4.0), (4.0, 10.0)])
        self.assertEqual(tab._selected_clip_lane, "A")
        self.assertIsNotNone(tab._selected_clip_id)

    def test_editor_shortcut_supports_russian_keyboard_layout(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Layer A"
        profile.layer_a.enabled = True
        tab.load_profile(profile.normalized_for_duration(10.0))
        clip_id = tab.read_video_profile().timeline.quote_clips_a[0].clip_id
        tab.timeline.select_clip("A", clip_id)
        tab.timeline.set_playhead(5.0, notify=False)
        tab.inspector_toggle_button.focus_set()
        app.update_idletasks()
        app.update()

        result = tab._handle_editor_keypress(SimpleNamespace(widget=tab.inspector_toggle_button, char="ч"))
        current = tab.read_video_profile().timeline

        self.assertEqual(result, "break")
        self.assertEqual([(clip.start_sec, clip.end_sec) for clip in current.quote_clips_a], [(0.0, 5.0), (5.0, 10.0)])

    def test_editor_shortcut_ignores_text_input_focus(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Layer A"
        profile.layer_a.enabled = True
        tab.load_profile(profile.normalized_for_duration(10.0))
        clip_id = tab.read_video_profile().timeline.quote_clips_a[0].clip_id
        tab.timeline.select_clip("A", clip_id)
        tab.timeline.set_playhead(4.0, notify=False)
        text_box = tab.layer_sections["A"].sample_quote_box
        text_box.focus_set()
        app.update_idletasks()
        app.update()

        result = tab._handle_editor_keypress(SimpleNamespace(widget=text_box, char="x"))
        current = tab.read_video_profile().timeline

        self.assertIsNone(result)
        self.assertEqual([(clip.start_sec, clip.end_sec) for clip in current.quote_clips_a], [(0.0, 10.0)])

    def test_undo_redo_restores_overlay_move(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Layer A"
        profile.layer_a.enabled = True
        tab.load_profile(profile.normalized_for_duration(10.0))
        app.update_idletasks()
        app.update()

        original = tab.read_video_profile().layer_a
        bounds = tab.preview._overlay_a._current_canvas_bounds()
        self.assertTrue(tab.preview._overlay_a.start_interaction(bounds.center_x, bounds.center_y))
        self.assertTrue(tab.preview._overlay_a.drag_to(bounds.center_x + 70, bounds.center_y + 18))
        tab.preview._overlay_a.finish_interaction()
        app.update_idletasks()
        app.update()

        moved = tab.read_video_profile().layer_a
        self.assertNotAlmostEqual(moved.position_x, original.position_x, places=4)

        self.assertTrue(tab.undo_editor_change())
        app.update_idletasks()
        app.update()
        restored = tab.read_video_profile().layer_a
        self.assertAlmostEqual(restored.position_x, original.position_x, places=4)
        self.assertAlmostEqual(restored.position_y, original.position_y, places=4)

        self.assertTrue(tab.redo_editor_change())
        app.update_idletasks()
        app.update()
        redone = tab.read_video_profile().layer_a
        self.assertAlmostEqual(redone.position_x, moved.position_x, places=4)
        self.assertAlmostEqual(redone.position_y, moved.position_y, places=4)

    def test_undo_redo_restores_split_clip(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Layer A"
        profile.layer_a.enabled = True
        tab.load_profile(profile.normalized_for_duration(10.0))
        clip_id = tab.read_video_profile().timeline.quote_clips_a[0].clip_id
        tab.timeline.select_clip("A", clip_id)
        tab.timeline.set_playhead(4.0, notify=False)

        self.assertTrue(tab.timeline.request_split_selected_clip())
        self.assertEqual(
            [(clip.start_sec, clip.end_sec) for clip in tab.read_video_profile().timeline.quote_clips_a],
            [(0.0, 4.0), (4.0, 10.0)],
        )

        self.assertTrue(tab.undo_editor_change())
        self.assertEqual(
            [(clip.start_sec, clip.end_sec) for clip in tab.read_video_profile().timeline.quote_clips_a],
            [(0.0, 10.0)],
        )

        self.assertTrue(tab.redo_editor_change())
        self.assertEqual(
            [(clip.start_sec, clip.end_sec) for clip in tab.read_video_profile().timeline.quote_clips_a],
            [(0.0, 4.0), (4.0, 10.0)],
        )

    def test_ctrl_z_and_ctrl_u_work_from_text_input(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Old text"
        profile.layer_a.enabled = True
        tab.load_profile(profile.normalized_for_duration(10.0))

        text_box = tab.layer_sections["A"].sample_quote_box
        text_box.delete("1.0", "end")
        text_box.insert("1.0", "New text")
        text_box.focus_set()
        tab._handle_section_change("A")
        app.update_idletasks()
        app.update()

        undo_result = tab._dispatch_editor_hotkeys(SimpleNamespace(widget=text_box, char="", keysym="z", state=0x4))
        self.assertEqual(undo_result, "break")
        self.assertEqual(tab.read_video_profile().layer_a.preview_text, "Old text")

        redo_result = tab._dispatch_editor_hotkeys(SimpleNamespace(widget=text_box, char="", keysym="u", state=0x4))
        self.assertEqual(redo_result, "break")
        self.assertEqual(tab.read_video_profile().layer_a.preview_text, "New text")

    def test_dispatch_shortcut_supports_real_russian_split_key(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        profile = VideoEditProfile()
        profile.layer_a.preview_text = "Layer A"
        profile.layer_a.enabled = True
        tab.load_profile(profile.normalized_for_duration(10.0))
        clip_id = tab.read_video_profile().timeline.quote_clips_a[0].clip_id
        tab.timeline.select_clip("A", clip_id)
        tab.timeline.set_playhead(5.0, notify=False)
        tab.inspector_toggle_button.focus_set()
        app.update_idletasks()
        app.update()

        result = tab._dispatch_editor_hotkeys(
            SimpleNamespace(widget=tab.inspector_toggle_button, char="\u0447", keysym="\u0447", state=0)
        )

        self.assertEqual(result, "break")
        self.assertEqual(
            [(clip.start_sec, clip.end_sec) for clip in tab.read_video_profile().timeline.quote_clips_a],
            [(0.0, 5.0), (5.0, 10.0)],
        )

    def test_undo_history_is_isolated_per_video(self) -> None:
        app, tab = self._create_tab()
        self.addCleanup(app.destroy)

        video_a = PROJECT_ROOT / "rush_5s.mp4"
        video_b = PROJECT_ROOT / "rush.mp4"

        profile_a = VideoEditProfile()
        profile_a.layer_a.preview_text = "Video A"
        profile_a.layer_a.enabled = True
        tab._selected_video_path = video_a
        tab.load_profile(profile_a.normalized_for_duration(10.0))
        box_a = tab.layer_sections["A"].sample_quote_box
        box_a.delete("1.0", "end")
        box_a.insert("1.0", "Video A edited")
        tab._handle_section_change("A")
        tab._flush_pending_history_commit()
        profile_a_edited = tab.read_video_profile()
        tab._capture_workspace_state()

        profile_b = VideoEditProfile()
        profile_b.layer_a.preview_text = "Video B"
        profile_b.layer_a.enabled = True
        tab._selected_video_path = video_b
        tab.load_profile(profile_b.normalized_for_duration(10.0))
        box_b = tab.layer_sections["A"].sample_quote_box
        box_b.delete("1.0", "end")
        box_b.insert("1.0", "Video B edited")
        tab._handle_section_change("A")
        tab._flush_pending_history_commit()
        profile_b_edited = tab.read_video_profile()
        tab._capture_workspace_state()

        tab._selected_video_path = video_a
        tab.load_profile(profile_a_edited)
        tab._restore_workspace_state()
        self.assertTrue(tab.undo_editor_change())
        self.assertEqual(tab.read_video_profile().layer_a.preview_text, "Video A")

        tab._capture_workspace_state()
        tab._selected_video_path = video_b
        tab.load_profile(profile_b_edited)
        tab._restore_workspace_state()
        self.assertEqual(tab.read_video_profile().layer_a.preview_text, "Video B edited")


if __name__ == "__main__":
    unittest.main()
