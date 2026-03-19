from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import customtkinter as ctk

from video_unicalizator.config import DEFAULT_VARIATIONS, MAX_VARIATIONS, MIN_VARIATIONS, TIMELINE_DEFAULT_PIXELS_PER_SECOND
from video_unicalizator.ui.preview_controller import ManagedPreviewPlaybackController
from video_unicalizator.state import (
    EditorLayoutState,
    GenerationProgressEvent,
    MusicClip,
    QuoteClip,
    TextStyle,
    TimelineLane,
    VideoEditProfile,
)
from video_unicalizator.ui.widgets.color_picker import ColorPickerRow
from video_unicalizator.ui.widgets.generation_console import GenerationConsole
from video_unicalizator.ui.widgets.timeline_editor import TimelineEditorWidget
from video_unicalizator.ui.widgets.video_preview import VideoPreviewWidget

LayerKey = Literal["A", "B"]


@dataclass(slots=True)
class EditorHistorySnapshot:
    profile: VideoEditProfile
    playhead_sec: float = 0.0
    selected_lane: TimelineLane | None = None
    selected_clip_id: str | None = None
    focused_layer: LayerKey = "A"


@dataclass(slots=True)
class VideoWorkspaceState:
    playhead_sec: float = 0.0
    timeline_zoom: float = float(TIMELINE_DEFAULT_PIXELS_PER_SECOND)
    timeline_scroll: float = 0.0
    selected_lane: TimelineLane | None = None
    selected_clip_id: str | None = None
    selected_range_start_sec: float | None = None
    selected_range_end_sec: float | None = None
    undo_stack: list[EditorHistorySnapshot] = None  # type: ignore[assignment]
    redo_stack: list[EditorHistorySnapshot] = None  # type: ignore[assignment]
    pending_snapshot: EditorHistorySnapshot | None = None
    pending_after_id: str | None = None

    def __post_init__(self) -> None:
        if self.undo_stack is None:
            self.undo_stack = []
        if self.redo_stack is None:
            self.redo_stack = []


@dataclass(slots=True)
class LayerSectionControls:
    key: LayerKey
    frame: ctk.CTkFrame
    title_label: ctk.CTkLabel
    enabled_switch: ctk.CTkSwitch
    sample_quote_box: ctk.CTkTextbox
    font_combo: ctk.CTkComboBox
    font_size_label: ctk.CTkLabel
    font_size_slider: ctk.CTkSlider
    box_width_label: ctk.CTkLabel
    box_width_slider: ctk.CTkSlider
    text_color_picker: ColorPickerRow
    bg_color_picker: ColorPickerRow
    bg_opacity_label: ctk.CTkLabel
    bg_opacity_slider: ctk.CTkSlider
    corner_radius_label: ctk.CTkLabel
    corner_radius_slider: ctk.CTkSlider
    shadow_label: ctk.CTkLabel
    shadow_slider: ctk.CTkSlider
    clip_status_label: ctk.CTkLabel


@dataclass(slots=True)
class MusicSectionControls:
    frame: ctk.CTkFrame
    clip_status_label: ctk.CTkLabel
    volume_label: ctk.CTkLabel
    volume_slider: ctk.CTkSlider
    helper_label: ctk.CTkLabel


class TextEditorTab(ctk.CTkFrame):
    HISTORY_DEBOUNCE_MS = 280
    MAX_HISTORY_DEPTH = 80
    """Главный экран редактора ресурсов, двух цитат и per-video макетов."""

    def __init__(
        self,
        master,
        fonts: list[str],
        on_load_originals_files,
        on_load_originals_folder,
        on_load_music_files,
        on_load_music_folder,
        on_load_quotes_a_files,
        on_load_quotes_a_folder,
        on_load_quotes_b_files,
        on_load_quotes_b_folder,
        on_choose_output_folder,
        on_apply_style,
        on_generate,
        on_video_selected,
        on_profile_changed,
        on_overlay_changed,
        on_stop_generation=None,
        on_remove_original=None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._fonts = fonts or ["Arial"]
        self._on_apply_style = on_apply_style
        self._on_generate = on_generate
        self._on_stop_generation = on_stop_generation or (lambda: None)
        self._on_remove_original = on_remove_original or (lambda: None)
        self._on_video_selected = on_video_selected
        self._on_profile_changed = on_profile_changed
        self._on_overlay_changed = on_overlay_changed
        self._suspend_callbacks = False
        self._focused_layer: LayerKey = "A"
        self._current_profile = VideoEditProfile()
        self._current_duration = 0.0
        self._original_paths: list[Path] = []
        self._music_tracks: list[Path] = []
        self._selected_video_path: Path | None = None
        self._selected_video_index = 0
        self._selected_clip_lane: TimelineLane | None = None
        self._selected_clip_id: str | None = None
        self._layout_state = EditorLayoutState()
        self._video_workspace_state: dict[str, VideoWorkspaceState] = {}
        self._last_drawer_compact_state: bool | None = None
        self._layout_resize_after_id: str | None = None
        self._editor_keypress_binding_id: str | None = None
        self._history_restore_in_progress = False

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.workspace_toolbar = ctk.CTkFrame(
            self,
            fg_color="#08111f",
            corner_radius=18,
            border_width=1,
            border_color="#16253c",
        )
        self.workspace_toolbar.grid(row=0, column=0, padx=12, pady=(10, 8), sticky="ew")
        self.workspace_toolbar.grid_columnconfigure(1, weight=1)

        self.workspace_title = ctk.CTkLabel(
            self.workspace_toolbar,
            text="Монтажная студия",
            font=ctk.CTkFont(family="Bahnschrift", size=18, weight="bold"),
            text_color="#f8fafc",
        )
        self.workspace_title.grid(row=0, column=0, padx=(14, 8), pady=10, sticky="w")

        nav_frame = ctk.CTkFrame(self.workspace_toolbar, fg_color="transparent")
        nav_frame.grid(row=0, column=1, pady=8, sticky="w")
        self.prev_video_button = ctk.CTkButton(nav_frame, text="Prev", width=58, height=30, command=self._select_prev_video)
        self.prev_video_button.grid(row=0, column=0, padx=(0, 6))
        self.current_video_label = ctk.CTkLabel(
            nav_frame,
            text="Видео не выбрано",
            text_color="#f8fafc",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
        )
        self.current_video_label.grid(row=0, column=1, padx=(0, 6), sticky="w")
        self.next_video_button = ctk.CTkButton(nav_frame, text="Next", width=58, height=30, command=self._select_next_video)
        self.next_video_button.grid(row=0, column=2, padx=(0, 10))

        actions_frame = ctk.CTkFrame(self.workspace_toolbar, fg_color="transparent")
        actions_frame.grid(row=0, column=2, padx=(8, 10), pady=8, sticky="e")
        self.undo_button = ctk.CTkButton(
            actions_frame,
            text="Undo",
            command=self.undo_editor_change,
            width=74,
            height=32,
            corner_radius=12,
            fg_color="#16253c",
            hover_color="#1d3557",
            state="disabled",
        )
        self.undo_button.grid(row=0, column=0, padx=(0, 6))
        self.redo_button = ctk.CTkButton(
            actions_frame,
            text="Redo",
            command=self.redo_editor_change,
            width=74,
            height=32,
            corner_radius=12,
            fg_color="#16253c",
            hover_color="#1d3557",
            state="disabled",
        )
        self.redo_button.grid(row=0, column=1, padx=(0, 6))

        self.generate_button = ctk.CTkButton(
            actions_frame,
            text="Рендер",
            command=self._on_generate,
            width=96,
            height=32,
            corner_radius=12,
            fg_color="#f97316",
            hover_color="#ea580c",
        )
        self.generate_button.grid(row=0, column=2, padx=(0, 6))

        self.stop_generation_button = ctk.CTkButton(
            actions_frame,
            text="Стоп",
            command=self._on_stop_generation,
            width=74,
            height=32,
            corner_radius=12,
            fg_color="#991b1b",
            hover_color="#b91c1c",
            state="disabled",
        )
        self.stop_generation_button.grid(row=0, column=3, padx=(0, 10))

        toggle_frame = ctk.CTkFrame(self.workspace_toolbar, fg_color="transparent")
        toggle_frame.grid(row=0, column=3, padx=(0, 14), pady=8, sticky="e")
        self.media_toggle_button = ctk.CTkButton(toggle_frame, text="Медиа", width=78, height=30, command=self._toggle_media_rail)
        self.media_toggle_button.grid(row=0, column=0, padx=(0, 6))
        self.inspector_toggle_button = ctk.CTkButton(toggle_frame, text="Инспектор", width=92, height=30, command=self._toggle_inspector)
        self.inspector_toggle_button.grid(row=0, column=1, padx=(0, 6))
        self.timeline_toggle_button = ctk.CTkButton(toggle_frame, text="Timeline", width=82, height=30, command=self._toggle_timeline)
        self.timeline_toggle_button.grid(row=0, column=2, padx=(0, 6))
        self.console_toggle_button = ctk.CTkButton(toggle_frame, text="Лог", width=62, height=30, command=self._toggle_console)
        self.console_toggle_button.grid(row=0, column=3)

        self.main_pane = tk.PanedWindow(
            self,
            orient="horizontal",
            sashwidth=8,
            bd=0,
            relief="flat",
            bg="#050914",
            opaqueresize=True,
        )
        self.main_pane.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="nsew")

        self.left_shell = ctk.CTkFrame(self.main_pane, fg_color="transparent")
        self.left_shell.grid_rowconfigure(0, weight=1)
        self.left_shell.grid_columnconfigure(0, weight=1)
        self.left_panel = ctk.CTkScrollableFrame(
            self.left_shell,
            width=getattr(self._layout_state, "media_rail_width", 280),
            corner_radius=18,
            fg_color="#0b1320",
            border_width=1,
            border_color="#16253c",
        )
        self.left_panel.grid(row=0, column=0, sticky="nsew")
        self.left_panel.grid_columnconfigure(0, weight=1)

        self.center_host = ctk.CTkFrame(self.main_pane, fg_color="transparent")
        self.center_host.grid_rowconfigure(0, weight=1)
        self.center_host.grid_columnconfigure(0, weight=1)

        self.center_pane = tk.PanedWindow(
            self.center_host,
            orient="vertical",
            sashwidth=8,
            bd=0,
            relief="flat",
            bg="#050914",
            opaqueresize=True,
        )
        self.center_pane.grid(row=0, column=0, sticky="nsew")

        self.preview = VideoPreviewWidget(
            self.center_pane,
            on_overlay_change=self._handle_overlay_change,
            on_overlay_focus=self._handle_overlay_focus,
            on_time_change=self._handle_preview_time_change,
        )

        self.timeline = TimelineEditorWidget(
            self.center_pane,
            on_timeline_change=self._handle_timeline_change,
            on_playhead_change=self._handle_timeline_playhead_change,
            on_lane_focus=self._handle_timeline_lane_focus,
            on_selection_change=self._handle_timeline_selection_change,
            height=self._layout_state.timeline_height,
        )

        self.right_shell = ctk.CTkFrame(self.main_pane, fg_color="transparent")
        self.right_shell.grid_rowconfigure(0, weight=1)
        self.right_shell.grid_columnconfigure(0, weight=1)
        self.right_panel = ctk.CTkScrollableFrame(
            self.right_shell,
            width=self._layout_state.inspector_width,
            corner_radius=18,
            fg_color="#0b1320",
            border_width=1,
            border_color="#16253c",
        )
        self.right_panel.grid(row=0, column=0, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)

        self.generation_console = GenerationConsole(
            self,
            title="Статус генерации",
            compact=True,
            start_collapsed=True,
        )
        self.generation_console.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        if not self._layout_state.console_visible:
            self.generation_console.grid_remove()

        self._build_media_rail(
            on_load_originals_files,
            on_load_originals_folder,
            on_load_music_files,
            on_load_music_folder,
            on_load_quotes_a_files,
            on_load_quotes_a_folder,
            on_load_quotes_b_files,
            on_load_quotes_b_folder,
            on_choose_output_folder,
        )
        self._build_inspector()
        self._playback_controller = ManagedPreviewPlaybackController(
            preview_widget=self.preview,
            get_timeline=lambda: self._current_profile.timeline.copy(),
            get_music_tracks=lambda: list(self._music_tracks),
            get_music_preview_settings=self.preview.read_music_preview_settings,
        )
        self.preview.set_playback_controller(self._playback_controller)
        self.main_pane.bind("<ButtonRelease-1>", lambda _event: self.after_idle(self._remember_layout_state))
        self.center_pane.bind("<ButtonRelease-1>", lambda _event: self.after_idle(self._remember_layout_state))
        self.bind("<Configure>", self._schedule_layout_refresh)
        self._apply_workspace_layout()
        self.load_profile(VideoEditProfile())
        self._sync_toggle_buttons()
        self._refresh_original_actions()
        self._bind_editor_shortcuts()
        self.bind("<Destroy>", self._handle_destroy, add="+")

    def _pane_present(self, pane: tk.PanedWindow, widget) -> bool:
        return str(widget) in pane.panes()

    def _apply_workspace_layout(self) -> None:
        compact_mode = (self.winfo_width() or 0) < 1380
        effective_media_visible = self._layout_state.media_rail_visible
        effective_inspector_visible = self._layout_state.inspector_visible and not compact_mode

        self.left_panel.configure(width=self._layout_state.media_rail_width)
        self.right_panel.configure(width=self._layout_state.inspector_width)
        self.timeline.configure(height=self._layout_state.timeline_height)

        if self._pane_present(self.center_pane, self.preview):
            self.center_pane.forget(self.preview)
        if self._pane_present(self.center_pane, self.timeline):
            self.center_pane.forget(self.timeline)
        self.center_pane.add(self.preview, minsize=360)
        if self._layout_state.timeline_visible:
            self.center_pane.add(self.timeline, minsize=220)

        if self._pane_present(self.main_pane, self.left_shell):
            self.main_pane.forget(self.left_shell)
        if self._pane_present(self.main_pane, self.center_host):
            self.main_pane.forget(self.center_host)
        if self._pane_present(self.main_pane, self.right_shell):
            self.main_pane.forget(self.right_shell)

        if effective_media_visible:
            self.main_pane.add(self.left_shell, minsize=220)
        self.main_pane.add(self.center_host, minsize=680)
        if effective_inspector_visible:
            self.main_pane.add(self.right_shell, minsize=260)

        if self._layout_state.console_visible:
            self.generation_console.grid()
            self.generation_console.set_expanded(True)
        else:
            self.generation_console.grid_remove()
        self._last_drawer_compact_state = compact_mode
        self.after_idle(self._remember_layout_state)

    def _remember_layout_state(self) -> None:
        if self._layout_state.media_rail_visible and self.left_panel.winfo_exists():
            self._layout_state.media_rail_width = max(220, self.left_shell.winfo_width())
        if self._layout_state.inspector_visible and self.right_panel.winfo_exists() and self._pane_present(self.main_pane, self.right_shell):
            self._layout_state.inspector_width = max(260, self.right_shell.winfo_width())
        if self._layout_state.timeline_visible and self.timeline.winfo_exists():
            self._layout_state.timeline_height = max(220, self.timeline.winfo_height())

    def _sync_toggle_buttons(self) -> None:
        compact_mode = (self.winfo_width() or 0) < 1380
        button_map = (
            (self.media_toggle_button, self._layout_state.media_rail_visible),
            (self.inspector_toggle_button, self._layout_state.inspector_visible and not compact_mode),
            (self.timeline_toggle_button, self._layout_state.timeline_visible),
            (self.console_toggle_button, self._layout_state.console_visible),
        )
        for button, enabled in button_map:
            button.configure(
                fg_color="#2563eb" if enabled else "#16253c",
                hover_color="#1d4ed8" if enabled else "#1d3557",
            )

    def _toggle_media_rail(self) -> None:
        self._layout_state.media_rail_visible = not self._layout_state.media_rail_visible
        self._apply_workspace_layout()
        self._sync_toggle_buttons()

    def _toggle_inspector(self) -> None:
        self._layout_state.inspector_visible = not self._layout_state.inspector_visible
        self._apply_workspace_layout()
        self._sync_toggle_buttons()

    def _toggle_timeline(self) -> None:
        self._layout_state.timeline_visible = not self._layout_state.timeline_visible
        self._apply_workspace_layout()
        self._sync_toggle_buttons()

    def _toggle_console(self) -> None:
        self._layout_state.console_visible = not self._layout_state.console_visible
        self._apply_workspace_layout()
        self._sync_toggle_buttons()

    def _schedule_layout_refresh(self, _event=None) -> None:
        if self._layout_resize_after_id is not None:
            self.after_cancel(self._layout_resize_after_id)
        self._layout_resize_after_id = self.after(90, self._refresh_layout_on_resize)

    def _bind_editor_shortcuts(self) -> None:
        toplevel = self.winfo_toplevel()
        if self._editor_keypress_binding_id is None:
            self._editor_keypress_binding_id = toplevel.bind("<KeyPress>", self._dispatch_editor_hotkeys, add="+")

    def _handle_destroy(self, event=None) -> None:
        self._flush_pending_history_commit()
        if event is not None and event.widget is not self:
            return
        if self._editor_keypress_binding_id is None:
            return
        try:
            self.winfo_toplevel().unbind("<KeyPress>", self._editor_keypress_binding_id)
        except tk.TclError:
            pass
        self._editor_keypress_binding_id = None

    def _handle_editor_keypress(self, event) -> str | None:
        char = (getattr(event, "char", "") or "").lower()
        if char not in {"x", "ч"}:
            return None
        if not self.winfo_exists() or not self.winfo_ismapped():
            return None
        focus_widget = self.focus_get() or getattr(event, "widget", None)
        if focus_widget is None or not self._is_descendant_widget(focus_widget):
            return None
        if self._is_text_input_widget(focus_widget):
            return None
        self.timeline.request_split_selected_clip()
        return "break"

    def _is_descendant_widget(self, widget) -> bool:
        current = widget
        while current is not None:
            if current == self:
                return True
            current = getattr(current, "master", None)
        return False

    def _is_text_input_widget(self, widget) -> bool:
        if isinstance(widget, (ctk.CTkTextbox, ctk.CTkEntry, tk.Text, tk.Entry)):
            return True
        try:
            widget_class = str(widget.winfo_class()).lower()
        except tk.TclError:
            return False
        return "text" in widget_class or "entry" in widget_class

    def _handle_editor_hotkeys(self, event) -> str | None:
        if not self.winfo_exists() or not self.winfo_ismapped():
            return None
        focus_widget = self.focus_get() or getattr(event, "widget", None)
        if focus_widget is None or not self._is_descendant_widget(focus_widget):
            return None
        keysym = (getattr(event, "keysym", "") or "").lower()
        char = (getattr(event, "char", "") or "").lower()
        is_control = bool(getattr(event, "state", 0) & 0x4)
        if is_control and keysym in {"z", "я"}:
            if self.undo_editor_change():
                return "break"
            return None
        if is_control and keysym in {"u", "г"}:
            if self.redo_editor_change():
                return "break"
            return None
        if char not in {"x", "ч"} and keysym not in {"x", "ч"}:
            return None
        if self._is_text_input_widget(focus_widget):
            return None
        if self.timeline.request_split_selected_clip():
            return "break"
        return None

    def _dispatch_editor_hotkeys(self, event) -> str | None:
        if not self.winfo_exists() or not self.winfo_ismapped():
            return None
        focus_widget = self.focus_get()
        if focus_widget is None or not self._is_descendant_widget(focus_widget):
            focus_widget = getattr(event, "widget", None)
        if focus_widget is None or not self._is_descendant_widget(focus_widget):
            return None
        keysym = (getattr(event, "keysym", "") or "").lower()
        char = (getattr(event, "char", "") or "").lower()
        is_control = bool(getattr(event, "state", 0) & 0x4)
        if is_control and keysym in {"z", "\u044f"}:
            if self.undo_editor_change():
                return "break"
            return None
        if is_control and keysym in {"u", "\u0433"}:
            if self.redo_editor_change():
                return "break"
            return None
        if char not in {"x", "\u0447"} and keysym not in {"x", "\u0447"}:
            return None
        if self._is_text_input_widget(focus_widget):
            return None
        if self.timeline.request_split_selected_clip():
            return "break"
        return None

    def _history_key_for_video(self, video_path: Path | None) -> str:
        return str(video_path) if video_path is not None else "__default__"

    def _history_state_for_video(self, video_path: Path | None = None) -> VideoWorkspaceState:
        target = self._selected_video_path if video_path is None else video_path
        return self._video_workspace_state.setdefault(self._history_key_for_video(target), VideoWorkspaceState())

    def _capture_history_snapshot(self) -> EditorHistorySnapshot:
        return EditorHistorySnapshot(
            profile=self._current_profile.copy(),
            playhead_sec=self.preview.get_playhead(),
            selected_lane=self._selected_clip_lane,
            selected_clip_id=self._selected_clip_id,
            focused_layer=self._focused_layer,
        )

    def _snapshots_equal(self, left: EditorHistorySnapshot | None, right: EditorHistorySnapshot | None) -> bool:
        if left is None or right is None:
            return left is right
        return (
            left.profile == right.profile
            and abs(left.playhead_sec - right.playhead_sec) < 1e-4
            and left.selected_lane == right.selected_lane
            and left.selected_clip_id == right.selected_clip_id
            and left.focused_layer == right.focused_layer
        )

    def _trim_history_stack(self, stack: list[EditorHistorySnapshot]) -> None:
        if len(stack) > self.MAX_HISTORY_DEPTH:
            del stack[: len(stack) - self.MAX_HISTORY_DEPTH]

    def _push_undo_snapshot(self, snapshot: EditorHistorySnapshot, *, clear_redo: bool = True) -> None:
        state = self._history_state_for_video()
        if state.undo_stack and self._snapshots_equal(state.undo_stack[-1], snapshot):
            if clear_redo:
                state.redo_stack.clear()
            self._refresh_history_controls()
            return
        state.undo_stack.append(snapshot)
        self._trim_history_stack(state.undo_stack)
        if clear_redo:
            state.redo_stack.clear()
        self._refresh_history_controls()

    def _begin_debounced_history_capture(self) -> None:
        if self._history_restore_in_progress or self._suspend_callbacks:
            return
        state = self._history_state_for_video()
        if state.pending_snapshot is None:
            state.pending_snapshot = self._capture_history_snapshot()
        if state.pending_after_id is not None:
            self.after_cancel(state.pending_after_id)
        state.pending_after_id = self.after(self.HISTORY_DEBOUNCE_MS, self._flush_pending_history_commit)

    def _flush_pending_history_commit(self) -> None:
        state = self._history_state_for_video()
        if state.pending_after_id is not None:
            try:
                self.after_cancel(state.pending_after_id)
            except tk.TclError:
                pass
            state.pending_after_id = None
        pending = state.pending_snapshot
        state.pending_snapshot = None
        if pending is None or self._history_restore_in_progress:
            self._refresh_history_controls()
            return
        current = self._capture_history_snapshot()
        if not self._snapshots_equal(pending, current):
            self._push_undo_snapshot(pending, clear_redo=True)
        else:
            self._refresh_history_controls()

    def _pop_distinct_snapshot(
        self,
        stack: list[EditorHistorySnapshot],
        current: EditorHistorySnapshot,
    ) -> EditorHistorySnapshot | None:
        while stack:
            candidate = stack.pop()
            if not self._snapshots_equal(candidate, current):
                return candidate
        return None

    def _restore_history_snapshot(self, snapshot: EditorHistorySnapshot) -> None:
        self._history_restore_in_progress = True
        try:
            self._current_profile = snapshot.profile.copy()
            self._selected_clip_lane = snapshot.selected_lane
            self._selected_clip_id = snapshot.selected_clip_id
            self._focused_layer = snapshot.focused_layer
            self.load_profile(snapshot.profile.copy())
            self.preview.set_playhead(snapshot.playhead_sec)
            self.timeline.set_playhead(snapshot.playhead_sec, notify=False)
            self._selected_clip_lane = snapshot.selected_lane
            self._selected_clip_id = snapshot.selected_clip_id
            if snapshot.selected_lane in {"A", "B"}:
                self._focus_layer(snapshot.selected_lane, refresh=False)
                self.timeline.select_clip(snapshot.selected_lane, snapshot.selected_clip_id)
            elif snapshot.selected_lane == "Music":
                self.timeline.select_clip("Music", snapshot.selected_clip_id)
                self.preview.set_active_layer(snapshot.focused_layer)
            else:
                self._focus_layer(snapshot.focused_layer, refresh=False)
                self.timeline.select_clip(None, None)
            self._emit_profile_change(refresh_timeline=False)
            self._capture_workspace_state()
        finally:
            self._history_restore_in_progress = False
        self._refresh_history_controls()

    def undo_editor_change(self) -> bool:
        if self.generate_button.cget("state") == "disabled":
            return False
        self._flush_pending_history_commit()
        state = self._history_state_for_video()
        current = self._capture_history_snapshot()
        target = self._pop_distinct_snapshot(state.undo_stack, current)
        if target is None:
            self._refresh_history_controls()
            return False
        state.redo_stack.append(current)
        self._trim_history_stack(state.redo_stack)
        self._restore_history_snapshot(target)
        return True

    def redo_editor_change(self) -> bool:
        if self.generate_button.cget("state") == "disabled":
            return False
        self._flush_pending_history_commit()
        state = self._history_state_for_video()
        current = self._capture_history_snapshot()
        target = self._pop_distinct_snapshot(state.redo_stack, current)
        if target is None:
            self._refresh_history_controls()
            return False
        state.undo_stack.append(current)
        self._trim_history_stack(state.undo_stack)
        self._restore_history_snapshot(target)
        return True

    def _refresh_history_controls(self) -> None:
        state = self._history_state_for_video()
        enabled = self.generate_button.cget("state") != "disabled"
        undo_state = "normal" if enabled and bool(state.undo_stack or state.pending_snapshot is not None) else "disabled"
        redo_state = "normal" if enabled and bool(state.redo_stack) else "disabled"
        if hasattr(self, "undo_button"):
            self.undo_button.configure(state=undo_state)
        if hasattr(self, "redo_button"):
            self.redo_button.configure(state=redo_state)

    def _refresh_layout_on_resize(self) -> None:
        self._layout_resize_after_id = None
        compact_mode = (self.winfo_width() or 0) < 1380
        if compact_mode != self._last_drawer_compact_state:
            self._apply_workspace_layout()

    def _capture_workspace_state(self) -> None:
        state = self._history_state_for_video()
        self._flush_pending_history_commit()
        state.playhead_sec = self.preview.get_playhead()
        state.timeline_zoom = self.timeline.read_view_state()[0]
        state.timeline_scroll = self.timeline.read_view_state()[1]
        state.selected_lane = self._selected_clip_lane
        state.selected_clip_id = self._selected_clip_id
        state.selected_range_start_sec = None
        state.selected_range_end_sec = None

    def _restore_workspace_state(self) -> None:
        if self._selected_video_path is None:
            self._refresh_history_controls()
            return
        state = self._video_workspace_state.get(str(self._selected_video_path))
        if state is None:
            self._refresh_history_controls()
            return
        self.timeline.set_view_state(pixels_per_second=state.timeline_zoom, scroll_fraction=state.timeline_scroll)
        self.preview.set_playhead(state.playhead_sec)
        self.timeline.clear_time_range()
        self._selected_clip_lane = state.selected_lane
        self._selected_clip_id = state.selected_clip_id
        if state.selected_lane in {"A", "B"}:
            self._focus_layer(state.selected_lane, refresh=False)
            self.timeline.select_clip(state.selected_lane, state.selected_clip_id)
        elif state.selected_lane == "Music":
            self.timeline.select_clip("Music", state.selected_clip_id)
            self.preview.set_active_layer(self._focused_layer)
        else:
            self.timeline.select_clip(None, None)
            self.preview.set_active_layer(self._focused_layer)
        self._refresh_inspector()
        self._refresh_history_controls()

    def _section_title(self, parent, row: int, title: str, subtitle: str | None = None) -> int:
        ctk.CTkLabel(
            parent,
            text=title,
            font=ctk.CTkFont(family="Bahnschrift", size=17, weight="bold"),
            text_color="#f8fafc",
        ).grid(row=row, column=0, padx=14, pady=(14, 4), sticky="w")
        row += 1
        if subtitle:
            ctk.CTkLabel(
                parent,
                text=subtitle,
                text_color="#8ea2c0",
                wraplength=318,
                justify="left",
            ).grid(row=row, column=0, padx=14, pady=(0, 8), sticky="w")
            row += 1
        return row

    def _resource_row(
        self,
        parent,
        row: int,
        title: str,
        on_pick_files,
        on_pick_folder,
        files_text: str,
        folder_text: str,
        accent_color: str,
    ) -> tuple[int, ctk.CTkButton, ctk.CTkButton]:
        row_frame = ctk.CTkFrame(parent, fg_color="#0f1b31", corner_radius=14)
        row_frame.grid(row=row, column=0, padx=14, pady=(0, 8), sticky="ew")
        row_frame.grid_columnconfigure(0, weight=1)
        row_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row_frame,
            text=title,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#f8fafc",
        ).grid(row=0, column=0, columnspan=2, padx=10, pady=(8, 6), sticky="w")

        files_button = ctk.CTkButton(
            row_frame,
            text=files_text,
            command=on_pick_files,
            height=34,
            corner_radius=12,
            fg_color=accent_color,
            hover_color=accent_color,
        )
        files_button.grid(row=1, column=0, padx=(10, 5), pady=(0, 10), sticky="ew")

        folder_button = ctk.CTkButton(
            row_frame,
            text=folder_text,
            command=on_pick_folder,
            height=34,
            corner_radius=12,
            fg_color="#1f2937",
            hover_color="#334155",
        )
        folder_button.grid(row=1, column=1, padx=(5, 10), pady=(0, 10), sticky="ew")
        return row + 1, files_button, folder_button

    def _build_media_rail(
        self,
        on_load_originals_files,
        on_load_originals_folder,
        on_load_music_files,
        on_load_music_folder,
        on_load_quotes_a_files,
        on_load_quotes_a_folder,
        on_load_quotes_b_files,
        on_load_quotes_b_folder,
        on_choose_output_folder,
    ) -> None:
        row = 0
        row = self._section_title(
            self.left_panel,
            row,
            "Медиатека",
            "Только ресурсы проекта: видео, музыка, txt-пулы и папка вывода. Монтаж и настройки живут в центре и справа.",
        )

        self.drawer_video_label = ctk.CTkLabel(
            self.left_panel,
            text="Видео не выбрано",
            text_color="#f8fafc",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
        )
        self.drawer_video_label.grid(row=row, column=0, padx=14, pady=(0, 6), sticky="w")
        row += 1

        self.inspector_summary = ctk.CTkLabel(
            self.left_panel,
            text="Оригиналы: 0\nМузыка: 0\nЦитаты A: 0\nЦитаты B: 0",
            justify="left",
            anchor="w",
            text_color="#9fb3cf",
        )
        self.inspector_summary.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        row += 1

        self.list_title = ctk.CTkLabel(
            self.left_panel,
            text="Видео проекта",
            font=ctk.CTkFont(family="Bahnschrift", size=16, weight="bold"),
            text_color="#f8fafc",
        )
        self.list_title.grid(row=row, column=0, padx=14, pady=(0, 6), sticky="w")
        row += 1

        self.listbox = tk.Listbox(
            self.left_panel,
            bg="#09111f",
            fg="#e2e8f0",
            selectbackground="#2563eb",
            activestyle="none",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 11),
            height=10,
        )
        self.listbox.grid(row=row, column=0, padx=14, pady=(0, 10), sticky="ew")
        self.listbox.bind("<<ListboxSelect>>", self._handle_video_selected)
        self.listbox.bind("<Delete>", self._handle_delete_pressed)
        row += 1

        self.remove_original_button = ctk.CTkButton(
            self.left_panel,
            text="Удалить из проекта",
            command=self._on_remove_original,
            height=36,
            corner_radius=12,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            state="disabled",
        )
        self.remove_original_button.grid(row=row, column=0, padx=14, pady=(0, 14), sticky="ew")
        row += 1

        row, self.originals_files_button, self.originals_folder_button = self._resource_row(
            self.left_panel,
            row,
            "Оригиналы",
            on_load_originals_files,
            on_load_originals_folder,
            "Выбрать mp4",
            "Папка",
            "#2563eb",
        )
        row, self.music_files_button, self.music_folder_button = self._resource_row(
            self.left_panel,
            row,
            "Музыка",
            on_load_music_files,
            on_load_music_folder,
            "Выбрать mp3",
            "Папка",
            "#0f766e",
        )
        row, self.quotes_a_files_button, self.quotes_a_folder_button = self._resource_row(
            self.left_panel,
            row,
            "Цитаты A",
            on_load_quotes_a_files,
            on_load_quotes_a_folder,
            "txt для A",
            "Папка",
            "#2563eb",
        )
        row, self.quotes_b_files_button, self.quotes_b_folder_button = self._resource_row(
            self.left_panel,
            row,
            "Цитаты B",
            on_load_quotes_b_files,
            on_load_quotes_b_folder,
            "txt для B",
            "Папка",
            "#ec4899",
        )

        self.output_button = ctk.CTkButton(
            self.left_panel,
            text="Папка вывода",
            command=on_choose_output_folder,
            height=36,
            corner_radius=12,
            fg_color="#16253c",
            hover_color="#1d3557",
        )
        self.output_button.grid(row=row, column=0, padx=14, pady=(4, 4), sticky="ew")
        row += 1

        self.output_label = ctk.CTkLabel(
            self.left_panel,
            text="output",
            text_color="#cbd5e1",
            justify="left",
            wraplength=248,
        )
        self.output_label.grid(row=row, column=0, padx=14, pady=(0, 6), sticky="w")
        row += 1

        self.output_status = ctk.CTkLabel(
            self.left_panel,
            text="Вывод: output",
            text_color="#8ea2c0",
            justify="left",
            wraplength=248,
        )
        self.output_status.grid(row=row, column=0, padx=14, pady=(0, 10), sticky="w")
        row += 1

        self.ffmpeg_status_label = ctk.CTkLabel(
            self.left_panel,
            text="FFmpeg: проверка...",
            text_color="#8ea2c0",
            justify="left",
            wraplength=248,
        )
        self.ffmpeg_status_label.grid(row=row, column=0, padx=14, pady=(0, 14), sticky="w")

    def _build_layer_sections(self, parent, row: int) -> tuple[int, dict[LayerKey, LayerSectionControls]]:
        sections: dict[LayerKey, LayerSectionControls] = {}
        row, sections["A"] = self._build_layer_section(
            parent,
            row,
            key="A",
            title="Цитата A",
            accent="#2563eb",
            subtitle="Основная дорожка цитаты. Если txt-пул не загружен, генерация берёт sample-текст отсюда.",
        )
        row, sections["B"] = self._build_layer_section(
            parent,
            row,
            key="B",
            title="Цитата B",
            accent="#ec4899",
            subtitle="Вторая независимая дорожка. Удобно для call-to-action или нижней подписи.",
        )
        return row, sections

    def _build_music_section(self, parent, row: int) -> tuple[int, MusicSectionControls]:
        frame = ctk.CTkFrame(
            parent,
            fg_color="#0f1b31",
            corner_radius=16,
            border_width=1,
            border_color="#16253c",
        )
        frame.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        row += 1

        ctk.CTkLabel(
            frame,
            text="Музыка",
            font=ctk.CTkFont(family="Bahnschrift", size=16, weight="bold"),
            text_color="#f8fafc",
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")

        helper_label = ctk.CTkLabel(
            frame,
            text="Здесь настраивается только выбранный музыкальный клип. Источник трека всё ещё назначается автоматически по правилу unused first.",
            text_color="#8ea2c0",
            wraplength=270,
            justify="left",
        )
        helper_label.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")

        clip_status_label = ctk.CTkLabel(
            frame,
            text="Клипы: 0",
            text_color="#dbe4f0",
            justify="left",
            anchor="w",
        )
        clip_status_label.grid(row=2, column=0, padx=12, pady=(0, 6), sticky="ew")

        volume_label = ctk.CTkLabel(frame, text="Громкость выбранного клипа: 100%", text_color="#dbe4f0")
        volume_label.grid(row=3, column=0, padx=12, pady=(0, 4), sticky="w")

        volume_slider = ctk.CTkSlider(
            frame,
            from_=0.0,
            to=1.5,
            number_of_steps=150,
            command=self._on_music_volume_changed,
            progress_color="#0f766e",
        )
        volume_slider.grid(row=4, column=0, padx=12, pady=(0, 12), sticky="ew")

        return row, MusicSectionControls(
            frame=frame,
            clip_status_label=clip_status_label,
            volume_label=volume_label,
            volume_slider=volume_slider,
            helper_label=helper_label,
        )

    def _build_layer_section(
        self,
        parent,
        row: int,
        *,
        key: LayerKey,
        title: str,
        accent: str,
        subtitle: str,
    ) -> tuple[int, LayerSectionControls]:
        frame = ctk.CTkFrame(
            parent,
            fg_color="#0f1b31",
            corner_radius=16,
            border_width=1,
            border_color="#16253c",
        )
        frame.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        row += 1

        title_label = ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(family="Bahnschrift", size=16, weight="bold"),
            text_color="#f8fafc",
        )
        title_label.grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")

        ctk.CTkLabel(
            frame,
            text=subtitle,
            text_color="#8ea2c0",
            wraplength=270,
            justify="left",
        ).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")

        enabled_switch = ctk.CTkSwitch(
            frame,
            text="Слой включён",
            command=lambda layer=key: self._handle_section_change(layer),
            progress_color=accent,
        )
        enabled_switch.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="w")

        clip_status_label = ctk.CTkLabel(
            frame,
            text="Клипы: 0",
            text_color="#8ea2c0",
            justify="left",
        )
        clip_status_label.grid(row=2, column=0, padx=(160, 12), pady=(0, 8), sticky="e")

        sample_quote_box = ctk.CTkTextbox(
            frame,
            height=92,
            corner_radius=14,
            fg_color="#09111f",
            border_width=1,
            border_color="#16253c",
            wrap="word",
            font=ctk.CTkFont(family="Segoe UI", size=13),
        )
        sample_quote_box.grid(row=3, column=0, padx=12, pady=(0, 10), sticky="ew")
        sample_quote_box.bind("<KeyRelease>", lambda _event, layer=key: self._handle_section_change(layer))

        font_combo = ctk.CTkComboBox(
            frame,
            values=self._fonts,
            height=34,
            corner_radius=12,
            command=lambda _value, layer=key: self._handle_section_change(layer),
        )
        font_combo.grid(row=4, column=0, padx=12, pady=(0, 10), sticky="ew")

        font_size_label = ctk.CTkLabel(frame, text="Размер: 64 px", text_color="#dbe4f0")
        font_size_label.grid(row=5, column=0, padx=12, pady=(0, 4), sticky="w")
        font_size_slider = ctk.CTkSlider(
            frame,
            from_=28,
            to=128,
            number_of_steps=100,
            command=lambda value, layer=key: self._on_font_size_changed(layer, value),
            progress_color="#f97316",
        )
        font_size_slider.grid(row=6, column=0, padx=12, pady=(0, 8), sticky="ew")

        box_width_label = ctk.CTkLabel(frame, text="Ширина блока: 72%", text_color="#dbe4f0")
        box_width_label.grid(row=7, column=0, padx=12, pady=(0, 4), sticky="w")
        box_width_slider = ctk.CTkSlider(
            frame,
            from_=0.30,
            to=0.90,
            number_of_steps=60,
            command=lambda value, layer=key: self._on_box_width_changed(layer, value),
            progress_color="#38bdf8",
        )
        box_width_slider.grid(row=8, column=0, padx=12, pady=(0, 8), sticky="ew")

        text_color_picker = ColorPickerRow(
            frame,
            title="Цвет текста",
            initial_color="#FFFFFF",
            on_change=lambda _value, layer=key: self._handle_section_change(layer),
        )
        text_color_picker.grid(row=9, column=0, padx=12, pady=(0, 4), sticky="ew")

        bg_color_picker = ColorPickerRow(
            frame,
            title="Фон цитаты",
            initial_color="#101010",
            on_change=lambda _value, layer=key: self._handle_section_change(layer),
        )
        bg_color_picker.grid(row=10, column=0, padx=12, pady=(0, 4), sticky="ew")

        bg_opacity_label = ctk.CTkLabel(frame, text="Прозрачность: 45%", text_color="#dbe4f0")
        bg_opacity_label.grid(row=11, column=0, padx=12, pady=(0, 4), sticky="w")
        bg_opacity_slider = ctk.CTkSlider(
            frame,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            command=lambda value, layer=key: self._on_bg_opacity_changed(layer, value),
            progress_color="#06b6d4",
        )
        bg_opacity_slider.grid(row=12, column=0, padx=12, pady=(0, 8), sticky="ew")

        corner_radius_label = ctk.CTkLabel(frame, text="Скругление: 36 px", text_color="#dbe4f0")
        corner_radius_label.grid(row=13, column=0, padx=12, pady=(0, 4), sticky="w")
        corner_radius_slider = ctk.CTkSlider(
            frame,
            from_=8,
            to=92,
            number_of_steps=84,
            command=lambda value, layer=key: self._on_corner_radius_changed(layer, value),
            progress_color="#a78bfa",
        )
        corner_radius_slider.grid(row=14, column=0, padx=12, pady=(0, 8), sticky="ew")

        shadow_label = ctk.CTkLabel(frame, text="Тень: 45%", text_color="#dbe4f0")
        shadow_label.grid(row=15, column=0, padx=12, pady=(0, 4), sticky="w")
        shadow_slider = ctk.CTkSlider(
            frame,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            command=lambda value, layer=key: self._on_shadow_changed(layer, value),
            progress_color="#f59e0b",
        )
        shadow_slider.grid(row=16, column=0, padx=12, pady=(0, 12), sticky="ew")

        return row, LayerSectionControls(
            key=key,
            frame=frame,
            title_label=title_label,
            enabled_switch=enabled_switch,
            sample_quote_box=sample_quote_box,
            font_combo=font_combo,
            font_size_label=font_size_label,
            font_size_slider=font_size_slider,
            box_width_label=box_width_label,
            box_width_slider=box_width_slider,
            text_color_picker=text_color_picker,
            bg_color_picker=bg_color_picker,
            bg_opacity_label=bg_opacity_label,
            bg_opacity_slider=bg_opacity_slider,
            corner_radius_label=corner_radius_label,
            corner_radius_slider=corner_radius_slider,
            shadow_label=shadow_label,
            shadow_slider=shadow_slider,
            clip_status_label=clip_status_label,
        )

    def _build_inspector(self) -> None:
        row = 0
        row = self._section_title(
            self.right_panel,
            row,
            "Инспектор",
            "Справа показываются только свойства выбранной дорожки или клипа. Выбор идёт от клика по цитате на stage или по клипу на timeline.",
        )

        self.inspector_context_label = ctk.CTkLabel(
            self.right_panel,
            text="Ничего не выбрано",
            text_color="#f8fafc",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
        )
        self.inspector_context_label.grid(row=row, column=0, padx=14, pady=(0, 6), sticky="w")
        row += 1

        self.layer_status = ctk.CTkLabel(
            self.right_panel,
            text="Выделите Цитату A, Цитату B или музыкальный клип, чтобы увидеть только его параметры.",
            justify="left",
            anchor="w",
            text_color="#cbd5e1",
            wraplength=286,
        )
        self.layer_status.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        row += 1

        self.context_help_frame = ctk.CTkFrame(
            self.right_panel,
            fg_color="#0f1b31",
            corner_radius=16,
            border_width=1,
            border_color="#16253c",
        )
        self.context_help_frame.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        self.context_help_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.context_help_frame,
            text="Подсказка",
            font=ctk.CTkFont(family="Bahnschrift", size=16, weight="bold"),
            text_color="#f8fafc",
        ).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")
        self.context_help_label = ctk.CTkLabel(
            self.context_help_frame,
            text="Кликните по цитате на stage, по дорожке A/B или по music clip на timeline. Инспектор покажет только нужные параметры.",
            text_color="#8ea2c0",
            justify="left",
            wraplength=270,
        )
        self.context_help_label.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="w")
        row += 1

        row, self.layer_sections = self._build_layer_sections(self.right_panel, row)
        row, self.music_section = self._build_music_section(self.right_panel, row)
        self.layer_sections["A"].frame.grid_remove()
        self.layer_sections["B"].frame.grid_remove()
        self.music_section.frame.grid_remove()

        export_frame = ctk.CTkFrame(
            self.right_panel,
            fg_color="#0f1b31",
            corner_radius=16,
            border_width=1,
            border_color="#16253c",
        )
        export_frame.grid(row=row, column=0, padx=14, pady=(0, 12), sticky="ew")
        export_frame.grid_columnconfigure(0, weight=1)
        row += 1

        ctk.CTkLabel(
            export_frame,
            text="Экспорт",
            font=ctk.CTkFont(family="Bahnschrift", size=16, weight="bold"),
            text_color="#f8fafc",
        ).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")

        self.variation_label = ctk.CTkLabel(
            export_frame,
            text=f"Вариаций на оригинал: {DEFAULT_VARIATIONS}",
            text_color="#dbe4f0",
        )
        self.variation_label.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="w")

        self.variation_slider = ctk.CTkSlider(
            export_frame,
            from_=MIN_VARIATIONS,
            to=MAX_VARIATIONS,
            number_of_steps=MAX_VARIATIONS - MIN_VARIATIONS,
            command=self._on_variation_changed,
            progress_color="#ec4899",
        )
        self.variation_slider.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")

        self.enhance_sharpness_switch = ctk.CTkSwitch(
            export_frame,
            text="Повысить чёткость при рендере",
            command=self._emit_profile_change,
            progress_color="#22c55e",
        )
        self.enhance_sharpness_switch.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="w")

        self.apply_button = ctk.CTkButton(
            export_frame,
            text="Применить макет ко всем видео",
            command=self._on_apply_style,
            height=38,
            corner_radius=12,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self.apply_button.grid(row=4, column=0, padx=12, pady=(0, 12), sticky="ew")

    def _show_inspector_section(self, section: str | None) -> None:
        frame_map = {
            "A": self.layer_sections["A"].frame,
            "B": self.layer_sections["B"].frame,
            "Music": self.music_section.frame,
            "Help": self.context_help_frame,
        }
        target = section if section in frame_map else "Help"
        for name, frame in frame_map.items():
            if name == target:
                frame.grid()
            else:
                frame.grid_remove()

    def _get_layer_style(self, layer: LayerKey) -> TextStyle:
        return self._current_profile.layer_a if layer == "A" else self._current_profile.layer_b

    def _set_layer_style(self, layer: LayerKey, style: TextStyle) -> None:
        if layer == "A":
            self._current_profile.layer_a = replace(style)
        else:
            self._current_profile.layer_b = replace(style)

    def _read_section_style(self, layer: LayerKey) -> TextStyle:
        section = self.layer_sections[layer]
        current_style = self._get_layer_style(layer)
        font_size = int(round(section.font_size_slider.get()))
        text_value = section.sample_quote_box.get("1.0", "end-1c")
        return replace(
            current_style,
            text_color=section.text_color_picker.get_value(),
            background_color=section.bg_color_picker.get_value(),
            background_opacity=float(section.bg_opacity_slider.get()),
            shadow_strength=float(section.shadow_slider.get()),
            font_size=font_size,
            font_name=section.font_combo.get(),
            preview_text=text_value,
            box_width_ratio=float(section.box_width_slider.get()),
            padding_x=max(18, int(round(font_size * 0.55))),
            padding_y=max(12, int(round(font_size * 0.35))),
            corner_radius=int(round(section.corner_radius_slider.get())),
            text_align="center",
            line_spacing=1.18,
            enabled=bool(section.enabled_switch.get()),
        )

    def _load_layer_into_section(self, layer: LayerKey, style: TextStyle) -> None:
        section = self.layer_sections[layer]
        self._suspend_callbacks = True
        if style.enabled:
            section.enabled_switch.select()
        else:
            section.enabled_switch.deselect()
        section.sample_quote_box.delete("1.0", "end")
        section.sample_quote_box.insert("1.0", style.preview_text)
        section.font_combo.set(style.font_name if style.font_name in self._fonts else self._fonts[0])
        section.font_size_slider.set(style.font_size)
        section.box_width_slider.set(style.box_width_ratio)
        section.bg_opacity_slider.set(style.background_opacity)
        section.corner_radius_slider.set(style.corner_radius)
        section.shadow_slider.set(style.shadow_strength)
        section.text_color_picker.set_value(style.text_color)
        section.bg_color_picker.set_value(style.background_color)
        self._update_section_labels(layer, style)
        self._suspend_callbacks = False

    def _update_section_labels(self, layer: LayerKey, style: TextStyle | None = None) -> None:
        section = self.layer_sections[layer]
        current = style or self._read_section_style(layer)
        section.font_size_label.configure(text=f"Размер: {int(round(current.font_size))} px")
        section.box_width_label.configure(text=f"Ширина блока: {int(round(current.box_width_ratio * 100))}%")
        section.bg_opacity_label.configure(text=f"Прозрачность: {int(round(current.background_opacity * 100))}%")
        section.corner_radius_label.configure(text=f"Скругление: {int(round(current.corner_radius))} px")
        section.shadow_label.configure(text=f"Тень: {int(round(current.shadow_strength * 100))}%")

    def _sync_layer_from_section(self, layer: LayerKey, *, update_preview: bool = True) -> TextStyle:
        style = self._read_section_style(layer)
        self._set_layer_style(layer, style)
        if update_preview:
            self.preview.update_layer(layer, style)
        return style

    def _sync_all_sections_to_profile(self) -> None:
        if self._suspend_callbacks:
            return
        for layer in ("A", "B"):
            self._sync_layer_from_section(layer, update_preview=False)

    def _handle_section_change(self, layer: LayerKey) -> None:
        if self._suspend_callbacks:
            return
        self._begin_debounced_history_capture()
        self._focus_layer(layer, refresh=False)
        style = self._sync_layer_from_section(layer)
        self._sync_lane_sample_to_timeline(layer, style.preview_text)
        self.timeline.set_lane_defaults(
            lane_a_text=self._current_profile.layer_a.preview_text,
            lane_b_text=self._current_profile.layer_b.preview_text,
        )
        self._update_section_labels(layer, style)
        self._emit_profile_change()

    def _emit_profile_change(self, *, refresh_timeline: bool = True) -> None:
        if self._suspend_callbacks:
            return
        self._sync_all_sections_to_profile()
        preview_duration = self._current_duration or self._current_profile.timeline.duration_hint or 12.0
        self._current_profile = self._current_profile.normalized_for_duration(preview_duration)
        self.preview.load_profile(self._current_profile)
        self.preview.set_active_layer(self._focused_layer)
        if refresh_timeline:
            self.timeline.set_lane_defaults(
                lane_a_text=self._current_profile.layer_a.preview_text,
                lane_b_text=self._current_profile.layer_b.preview_text,
            )
            self.timeline.load_timeline(self._current_profile.timeline, preview_duration)
        self._on_profile_changed(self._current_profile.copy(), self.read_variation_count(), self.read_enhance_sharpness())
        self._refresh_inspector()

    def _focus_layer(self, layer: LayerKey, *, refresh: bool = True) -> None:
        self._focused_layer = layer
        self.preview.set_active_layer(layer)
        for section_layer, section in self.layer_sections.items():
            is_active = section_layer == layer
            border_color = "#2563eb" if section_layer == "A" else "#ec4899"
            section.frame.configure(
                border_color=border_color if is_active else "#16253c",
                fg_color="#12233d" if is_active else "#0f1b31",
            )
        if refresh:
            self._refresh_inspector()

    def _handle_overlay_focus(self, layer: LayerKey) -> None:
        self._selected_clip_lane = layer
        self._selected_clip_id = None
        self._focus_layer(layer)

    def _sync_lane_sample_to_timeline(self, layer: LayerKey, sample_text: str) -> None:
        clips = self._current_profile.timeline.quote_clips_a if layer == "A" else self._current_profile.timeline.quote_clips_b
        for clip in clips:
            clip.sample_text = sample_text

    def _selected_music_clip(self) -> MusicClip | None:
        if self._selected_clip_lane != "Music" or self._selected_clip_id is None:
            return None
        for clip in self._current_profile.timeline.music_clips:
            if clip.clip_id == self._selected_clip_id:
                return clip
        return None

    def _handle_preview_time_change(self, seconds: float, duration: float) -> None:
        previous_duration = self._current_duration
        self._current_duration = max(0.0, duration)
        self.timeline.set_playhead(seconds, notify=False)
        if abs(previous_duration - self._current_duration) > 0.01:
            self._current_profile = self._current_profile.normalized_for_duration(self._current_duration)
            self.timeline.load_timeline(self._current_profile.timeline, self._current_duration)
        if self._selected_video_path is not None:
            state = self._video_workspace_state.setdefault(str(self._selected_video_path), VideoWorkspaceState())
            state.playhead_sec = seconds
        if not self.preview.is_playing():
            self._refresh_inspector()

    def _handle_timeline_playhead_change(self, seconds: float) -> None:
        self.preview.set_playhead(seconds)
        if self._selected_video_path is not None:
            state = self._video_workspace_state.setdefault(str(self._selected_video_path), VideoWorkspaceState())
            state.playhead_sec = seconds
        if not self.preview.is_playing():
            self._refresh_inspector()

    def _handle_timeline_lane_focus(self, lane: TimelineLane) -> None:
        self._selected_clip_lane = lane
        self._selected_clip_id = None
        if lane in {"A", "B"}:
            self._focus_layer(lane)
            return
        self._refresh_inspector()

    def _handle_timeline_selection_change(self, lane: TimelineLane | None, clip_id: str | None) -> None:
        self._selected_clip_lane = lane
        self._selected_clip_id = clip_id
        if lane in {"A", "B"}:
            self._focus_layer(lane)
            return
        self._refresh_inspector()

    def _handle_timeline_change(self, timeline) -> None:
        if not self._history_restore_in_progress:
            self._flush_pending_history_commit()
            self._push_undo_snapshot(self._capture_history_snapshot(), clear_redo=True)
        self._current_profile.timeline = timeline.copy()
        self._current_profile = self._current_profile.normalized_for_duration(self._current_duration or timeline.duration_hint)
        self.preview.load_profile(self._current_profile)
        self._emit_profile_change(refresh_timeline=False)
        self._capture_workspace_state()
        self._playback_controller.schedule_audio_prewarm()

    def _on_music_volume_changed(self, value: float) -> None:
        self.music_section.volume_label.configure(text=f"Громкость выбранного клипа: {int(round(value * 100))}%")
        clip = self._selected_music_clip()
        if clip is None or self._suspend_callbacks:
            return
        self._begin_debounced_history_capture()
        clip.volume = float(value)
        self.timeline.load_timeline(self._current_profile.timeline, self._current_duration)
        self._emit_profile_change(refresh_timeline=False)

    def _on_font_size_changed(self, layer: LayerKey, value: float) -> None:
        section = self.layer_sections[layer]
        section.font_size_label.configure(text=f"Размер: {int(round(value))} px")
        self._handle_section_change(layer)

    def _on_box_width_changed(self, layer: LayerKey, value: float) -> None:
        section = self.layer_sections[layer]
        section.box_width_label.configure(text=f"Ширина блока: {int(round(value * 100))}%")
        self._handle_section_change(layer)

    def _on_bg_opacity_changed(self, layer: LayerKey, value: float) -> None:
        section = self.layer_sections[layer]
        section.bg_opacity_label.configure(text=f"Прозрачность: {int(round(value * 100))}%")
        self._handle_section_change(layer)

    def _on_corner_radius_changed(self, layer: LayerKey, value: float) -> None:
        section = self.layer_sections[layer]
        section.corner_radius_label.configure(text=f"Скругление: {int(round(value))} px")
        self._handle_section_change(layer)

    def _on_shadow_changed(self, layer: LayerKey, value: float) -> None:
        section = self.layer_sections[layer]
        section.shadow_label.configure(text=f"Тень: {int(round(value * 100))}%")
        self._handle_section_change(layer)

    def _on_variation_changed(self, value: float) -> None:
        self.variation_label.configure(text=f"Вариаций на оригинал: {int(round(value))}")
        self._emit_profile_change()

    def _handle_video_selected(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        self._selected_video_index = selection[0]
        self._on_video_selected(self._original_paths[self._selected_video_index])

    def _handle_delete_pressed(self, _event=None) -> str:
        if self._original_paths:
            self._on_remove_original()
        return "break"

    def _select_prev_video(self) -> None:
        if not self._original_paths:
            return
        self._selected_video_index = (self._selected_video_index - 1) % len(self._original_paths)
        self._select_video_from_index()

    def _select_next_video(self) -> None:
        if not self._original_paths:
            return
        self._selected_video_index = (self._selected_video_index + 1) % len(self._original_paths)
        self._select_video_from_index()

    def _select_video_from_index(self) -> None:
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(self._selected_video_index)
        self.listbox.activate(self._selected_video_index)
        self._on_video_selected(self._original_paths[self._selected_video_index])

    def _refresh_original_actions(self) -> None:
        has_originals = bool(self._original_paths)
        button_state = "normal" if has_originals else "disabled"
        self.prev_video_button.configure(state=button_state)
        self.next_video_button.configure(state=button_state)
        self.remove_original_button.configure(state=button_state)

    def _handle_overlay_change(self, layer: LayerKey, style: TextStyle) -> None:
        if not self._history_restore_in_progress:
            self._flush_pending_history_commit()
            self._push_undo_snapshot(self._capture_history_snapshot(), clear_redo=True)
        self._set_layer_style(layer, style)
        self._selected_clip_lane = layer
        self._selected_clip_id = None
        self._focus_layer(layer, refresh=False)
        self._load_layer_into_section(layer, style)
        self._sync_lane_sample_to_timeline(layer, style.preview_text)
        self._on_overlay_changed(layer, style)
        self._refresh_inspector()

    def load_profile(self, profile: VideoEditProfile) -> None:
        preview_duration = self._current_duration or profile.timeline.duration_hint or 12.0
        self._current_profile = profile.normalized_for_duration(preview_duration)
        self.preview.load_profile(self._current_profile)
        self._load_layer_into_section("A", self._current_profile.layer_a)
        self._load_layer_into_section("B", self._current_profile.layer_b)
        self.timeline.set_lane_defaults(
            lane_a_text=self._current_profile.layer_a.preview_text,
            lane_b_text=self._current_profile.layer_b.preview_text,
        )
        self.timeline.set_media_sources(video_path=self._selected_video_path, music_tracks=self._music_tracks)
        self.timeline.load_timeline(self._current_profile.timeline, preview_duration)
        self._focus_layer(self._focused_layer, refresh=False)
        self._refresh_inspector()
        self._refresh_history_controls()

    def read_video_profile(self) -> VideoEditProfile:
        self._sync_all_sections_to_profile()
        self._current_profile.timeline = self.timeline.read_timeline()
        return self._current_profile.copy()

    def read_variation_count(self) -> int:
        return int(round(self.variation_slider.get()))

    def read_enhance_sharpness(self) -> bool:
        return bool(self.enhance_sharpness_switch.get())

    def set_quote_sample(self, layer: LayerKey, quote: str) -> None:
        style = self._get_layer_style(layer)
        style.preview_text = quote
        if quote.strip():
            style.enabled = True
        self._sync_lane_sample_to_timeline(layer, quote)
        self._load_layer_into_section(layer, style)
        self.timeline.set_lane_defaults(
            lane_a_text=self._current_profile.layer_a.preview_text,
            lane_b_text=self._current_profile.layer_b.preview_text,
        )
        self._focus_layer(layer, refresh=False)
        self.preview.update_layer(layer, style)
        self._refresh_inspector()

    def set_originals(self, paths: list[Path], selected_path: Path | None = None) -> None:
        self._original_paths = list(paths)
        self.listbox.delete(0, "end")
        for path in paths:
            self.listbox.insert("end", path.name)
        if not paths:
            self._selected_video_index = 0
            self._selected_video_path = None
            self.listbox.selection_clear(0, "end")
            self.current_video_label.configure(text="Видео не выбрано")
            self.drawer_video_label.configure(text="Видео не выбрано")
            self._refresh_original_actions()
            self._refresh_inspector()
            return
        if selected_path and selected_path in paths:
            self._selected_video_index = paths.index(selected_path)
        else:
            self._selected_video_index = 0
        self._selected_video_path = paths[self._selected_video_index]
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(self._selected_video_index)
        self.listbox.activate(self._selected_video_index)
        self.current_video_label.configure(text=paths[self._selected_video_index].name)
        self.drawer_video_label.configure(text=paths[self._selected_video_index].name)
        self._refresh_original_actions()
        self._refresh_inspector()

    def set_music_tracks(self, tracks: list[Path]) -> None:
        self._music_tracks = list(tracks)
        self.timeline.set_media_sources(video_path=self._selected_video_path, music_tracks=self._music_tracks)
        clip_duration = self._current_duration or self.preview.get_duration() or self._current_profile.timeline.duration_hint
        created_clip = None
        if (
            self._selected_video_path is not None
            and self._music_tracks
            and not self._current_profile.timeline.music_clips
            and clip_duration > 0
        ):
            self._current_duration = max(self._current_duration, clip_duration)
            created_clip = self.timeline.create_clip("Music", seconds=self.preview.get_playhead(), notify=False)
        if created_clip is not None:
            self._selected_clip_lane = "Music"
            self._selected_clip_id = created_clip.clip_id
            self.timeline.select_clip("Music", created_clip.clip_id)
        else:
            self.timeline.ensure_music_lane_visible()
        self._refresh_inspector()
        self._playback_controller.schedule_audio_prewarm()

    def load_video_context(self, video_path: Path | None, profile: VideoEditProfile) -> None:
        self._capture_workspace_state()
        self._selected_video_path = video_path
        self.preview.load_video(video_path)
        self.load_profile(profile)
        self.timeline.set_media_sources(video_path=video_path, music_tracks=self._music_tracks)
        if video_path is None:
            self.current_video_label.configure(text="Видео не выбрано")
            self.drawer_video_label.configure(text="Видео не выбрано")
        else:
            self.current_video_label.configure(text=video_path.name)
            self.drawer_video_label.configure(text=video_path.name)
        self._restore_workspace_state()
        self._refresh_inspector()
        self._refresh_history_controls()
        self._playback_controller.schedule_audio_prewarm()

    def set_media_summary(
        self,
        *,
        originals_count: int,
        music_count: int,
        quotes_count_a: int,
        quotes_count_b: int,
        max_warning_variations: int,
    ) -> None:
        self.inspector_summary.configure(
            text=(
                f"Оригиналы: {originals_count}\n"
                f"Музыка: {music_count}\n"
                f"Цитаты A: {quotes_count_a}\n"
                f"Цитаты B: {quotes_count_b}\n"
                f"Warning budget: {max_warning_variations}"
            )
        )

    def set_output_directory(self, path: Path) -> None:
        path_text = str(path)
        self.output_label.configure(text=path_text)
        self.output_status.configure(text=f"Вывод: {path_text}")

    def set_ffmpeg_status(self, status_text: str, available: bool) -> None:
        color = "#22c55e" if available else "#f97316"
        self.ffmpeg_status_label.configure(text=f"FFmpeg: {status_text}", text_color=color)
        self.current_video_label.configure(text_color="#f8fafc")
        self.drawer_video_label.configure(text_color="#f8fafc")

    def clear_generation_console(self) -> None:
        self.generation_console.clear()

    def set_generation_console_expanded(self, expanded: bool) -> None:
        self._layout_state.console_visible = expanded
        self._sync_toggle_buttons()
        self._apply_workspace_layout()
        self.generation_console.set_expanded(expanded)

    def set_stop_button_state(self, *, is_running: bool, stop_requested: bool) -> None:
        if is_running:
            self.stop_generation_button.configure(
                state="disabled" if stop_requested else "normal",
                text="Останавливаю..." if stop_requested else "Стоп",
            )
        else:
            self.stop_generation_button.configure(state="disabled", text="Стоп")

    def push_generation_event(self, event: GenerationProgressEvent) -> None:
        if event.stage not in {"Ожидание"}:
            if not self._layout_state.console_visible:
                self._layout_state.console_visible = True
                self._apply_workspace_layout()
                self._sync_toggle_buttons()
            self.generation_console.set_expanded(True)
        self.generation_console.push_event(event)
        if event.stage in {"Рендер", "Проверка качества", "Экспорт расписания"}:
            self.preview.set_runtime_status(event.message)
        elif event.stage in {"Готово", "Ошибка", "Ожидание", "Остановлено", "Остановка"}:
            self.preview.set_runtime_status(None)

    def set_generation_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.originals_files_button,
            self.originals_folder_button,
            self.music_files_button,
            self.music_folder_button,
            self.quotes_a_files_button,
            self.quotes_a_folder_button,
            self.quotes_b_files_button,
            self.quotes_b_folder_button,
            self.output_button,
            self.apply_button,
            self.undo_button,
            self.redo_button,
            self.generate_button,
            self.remove_original_button,
            self.variation_slider,
            self.prev_video_button,
            self.next_video_button,
        ):
            widget.configure(state=state)

        self.listbox.configure(state=state)
        self.enhance_sharpness_switch.configure(state=state)
        self.music_section.volume_slider.configure(state=state)

        for section in self.layer_sections.values():
            for widget in (
                section.enabled_switch,
                section.sample_quote_box,
                section.font_combo,
                section.font_size_slider,
                section.box_width_slider,
                section.bg_opacity_slider,
                section.corner_radius_slider,
                section.shadow_slider,
            ):
                widget.configure(state=state)
            section.text_color_picker.set_enabled(enabled)
            section.bg_color_picker.set_enabled(enabled)

        self.preview.set_interaction_enabled(enabled)
        self.timeline.set_interaction_enabled(enabled)
        if enabled:
            self._refresh_original_actions()
        self._refresh_history_controls()

    def _refresh_inspector(self) -> None:
        a = self._current_profile.layer_a
        b = self._current_profile.layer_b
        count_a = len(self._current_profile.timeline.quote_clips_a)
        count_b = len(self._current_profile.timeline.quote_clips_b)
        music_count = len(self._current_profile.timeline.music_clips)
        self.layer_sections["A"].clip_status_label.configure(text=f"Клипы: {count_a}")
        self.layer_sections["B"].clip_status_label.configure(text=f"Клипы: {count_b}")
        self.music_section.clip_status_label.configure(text=f"Клипы: {music_count}")

        selected_music = self._selected_music_clip()
        if selected_music is not None:
            self.music_section.volume_slider.set(selected_music.volume)
            self.music_section.volume_label.configure(
                text=f"Громкость выбранного клипа: {int(round(selected_music.volume * 100))}%"
            )
            self.music_section.volume_slider.configure(state="normal")
        else:
            self.music_section.volume_slider.set(1.0)
            self.music_section.volume_label.configure(text="Громкость выбранного клипа: 100%")
            self.music_section.volume_slider.configure(state="disabled")
        inspector_target: str | None
        if self._selected_clip_lane == "Music":
            inspector_target = "Music"
            context_title = "Музыкальный клип"
            context_text = "Громкость и поведение выбранного музыкального окна на timeline."
        elif self._selected_clip_lane in {"A", "B"}:
            inspector_target = self._selected_clip_lane
            layer_style = a if inspector_target == "A" else b
            context_title = f"Цитата {inspector_target}"
            context_text = (
                f"Слой {'включён' if layer_style.enabled else 'выключен'} • "
                f"клипов: {count_a if inspector_target == 'A' else count_b} • "
                f"текст: {len(layer_style.preview_text.strip())} символов"
            )
        elif self._selected_video_path is None:
            inspector_target = "Help"
            context_title = "Ничего не выбрано"
            context_text = "Загрузите вертикальный ролик и выберите дорожку на stage или timeline."
        else:
            inspector_target = self._focused_layer
            layer_style = a if inspector_target == "A" else b
            context_title = f"Цитата {inspector_target}"
            context_text = (
                f"Текущая активная дорожка • клипов: {count_a if inspector_target == 'A' else count_b} • "
                f"playhead {self.preview._format_time(self.preview.get_playhead())}"
            )

        self.inspector_context_label.configure(text=context_title)
        self.layer_status.configure(
            text=(
                f"{context_text}\n\n"
                f"Цитата A: {'вкл' if a.enabled else 'выкл'} • {count_a} клипов\n"
                f"Цитата B: {'вкл' if b.enabled else 'выкл'} • {count_b} клипов\n"
                f"Music: {music_count} клипов • {len(self._music_tracks)} треков в пуле"
            )
        )
        self._show_inspector_section(inspector_target)
