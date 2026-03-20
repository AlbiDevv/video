from __future__ import annotations

import math
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from typing import Callable

import customtkinter as ctk
from PIL import Image, ImageTk

from video_unicalizator.config import (
    TIMELINE_DEFAULT_CLIP_SECONDS,
    TIMELINE_DEFAULT_PIXELS_PER_SECOND,
    TIMELINE_MAX_PIXELS_PER_SECOND,
    TIMELINE_MIN_CLIP_SECONDS,
    TIMELINE_MIN_PIXELS_PER_SECOND,
    TIMELINE_SNAP_SECONDS,
    TIMELINE_ZOOM_STEP,
)
from video_unicalizator.state import (
    MusicClip,
    QuoteClip,
    TimelineClip,
    TimelineLane,
    VideoTimelineProfile,
    bind_unassigned_music_clips,
)
from video_unicalizator.ui.preview_support import (
    PreviewMusicAssignment,
    ThumbnailStripCache,
    WaveformCache,
    assign_preview_music_clips,
)

TimelineChangeCallback = Callable[[VideoTimelineProfile], None]
LaneFocusCallback = Callable[[TimelineLane], None]
PlayheadCallback = Callable[[float], None]
SelectionCallback = Callable[[TimelineLane | None, str | None], None]


class TimelineEditorWidget(ctk.CTkFrame):
    """Timeline widget with range cut, continuous filmstrip, and clip editing."""

    HEADER_WIDTH = 124
    TOP_PADDING = 16
    LEFT_PADDING = 18
    RIGHT_PADDING = 34
    RULER_HEIGHT = 28
    THUMBNAIL_HEIGHT = 68
    THUMBNAIL_GAP = 10
    TRACK_HEIGHT = 82
    TRACK_GAP = 14
    CLIP_MARGIN_X = 4
    CLIP_MARGIN_Y = 8
    HANDLE_HIT_PX = 10
    FILMSTRIP_TILE_WIDTH = 96
    RANGE_MIN_SECONDS = 0.05

    LANE_META: tuple[tuple[TimelineLane, str, str], ...] = (
        ("A", "Quote A", "#2563eb"),
        ("B", "Quote B", "#ec4899"),
        ("Music", "Music", "#0f766e"),
    )

    def __init__(
        self,
        master,
        *,
        on_timeline_change: TimelineChangeCallback,
        on_playhead_change: PlayheadCallback,
        on_lane_focus: LaneFocusCallback,
        on_selection_change: SelectionCallback | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            fg_color="#0d1729",
            corner_radius=20,
            border_width=1,
            border_color="#1e293b",
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._on_timeline_change = on_timeline_change
        self._on_playhead_change = on_playhead_change
        self._on_lane_focus = on_lane_focus
        self._on_selection_change = on_selection_change or (lambda _lane, _clip_id: None)

        self._interaction_enabled = True
        self._timeline = VideoTimelineProfile()
        self._duration = 0.0
        self._playhead = 0.0
        self._pixels_per_second = float(TIMELINE_DEFAULT_PIXELS_PER_SECOND)
        self._left_time_sec = 0.0
        self._lane_defaults = {"A": "", "B": ""}
        self._selected_lane: TimelineLane | None = None
        self._selected_clip_id: str | None = None
        self._selected_range_start_sec: float | None = None
        self._selected_range_end_sec: float | None = None
        self._range_mode_enabled = False
        self._drag_mode: str | None = None
        self._drag_origin_time = 0.0
        self._drag_origin_clip: TimelineClip | None = None
        self._range_drag_anchor_sec: float | None = None
        self._video_path: Path | None = None
        self._music_tracks: list[Path] = []
        self._thumbnail_cache = ThumbnailStripCache()
        self._waveform_cache = WaveformCache()
        self._thumbnail_refs: list[ImageTk.PhotoImage] = []
        self._pending_waveform_keys: set[str] = set()
        self._playhead_line_item: int | None = None
        self._playhead_handle_item: int | None = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=12, pady=(10, 6), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        self.title_label = ctk.CTkLabel(
            header,
            text="Timeline",
            font=ctk.CTkFont(family="Bahnschrift", size=18, weight="bold"),
            text_color="#f8fafc",
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self._default_info_text = "Double click creates clip. Drag moves, drag edges resizes, X/Ч splits selected clip at playhead, Delete removes clip."
        self.info_label = ctk.CTkLabel(
            header,
            text=self._default_info_text,
            text_color="#94a3b8",
            justify="left",
        )
        self.info_label.grid(row=1, column=0, columnspan=2, sticky="w")

        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.grid(row=0, column=2, rowspan=2, sticky="e")

        self.zoom_out_button = ctk.CTkButton(
            controls,
            text="-",
            width=34,
            height=30,
            corner_radius=10,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=lambda: self._change_zoom(1 / TIMELINE_ZOOM_STEP),
        )
        self.zoom_out_button.grid(row=0, column=0, padx=(0, 6))

        self.zoom_in_button = ctk.CTkButton(
            controls,
            text="+",
            width=34,
            height=30,
            corner_radius=10,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=lambda: self._change_zoom(TIMELINE_ZOOM_STEP),
        )
        self.zoom_in_button.grid(row=0, column=1, padx=(0, 6))

        self.fit_button = ctk.CTkButton(
            controls,
            text="Fit",
            width=56,
            height=30,
            corner_radius=10,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=self.reset_zoom,
        )
        self.fit_button.grid(row=0, column=2, padx=(0, 8))

        self.playhead_button = ctk.CTkButton(
            controls,
            text="Playhead",
            width=84,
            height=30,
            corner_radius=10,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=self.scroll_to_playhead,
        )
        self.playhead_button.grid(row=0, column=3, padx=(0, 6))

        self.end_button = ctk.CTkButton(
            controls,
            text="End",
            width=56,
            height=30,
            corner_radius=10,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=self.scroll_to_end,
        )
        self.end_button.grid(row=0, column=4, padx=(0, 6))

        self.range_button = ctk.CTkButton(
            controls,
            text="Range",
            width=70,
            height=30,
            corner_radius=10,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=self.toggle_range_mode,
        )
        self.range_button.grid(row=0, column=5, padx=(0, 6))
        self.range_button.grid_remove()

        self.cut_button = ctk.CTkButton(
            controls,
            text="Split (X)",
            width=78,
            height=30,
            corner_radius=10,
            fg_color="#7c2d12",
            hover_color="#9a3412",
            command=self.request_split_selected_clip,
            state="disabled",
        )
        self.cut_button.grid(row=0, column=6, padx=(0, 6))

        self.clear_range_button = ctk.CTkButton(
            controls,
            text="Clear",
            width=62,
            height=30,
            corner_radius=10,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=self.clear_time_range,
            state="disabled",
        )
        self.clear_range_button.grid(row=0, column=7, padx=(0, 6))
        self.clear_range_button.grid_remove()

        self.add_music_button = ctk.CTkButton(
            controls,
            text="+ Music",
            width=84,
            height=30,
            corner_radius=10,
            fg_color="#0f766e",
            hover_color="#115e59",
            command=lambda: self.create_clip("Music", seconds=self._playhead, notify=False),
        )
        self.add_music_button.grid(row=0, column=8, padx=(0, 8))

        self.playhead_label = ctk.CTkLabel(controls, text="00:00.0 / 00:00.0", text_color="#dbe4f0")
        self.playhead_label.grid(row=0, column=9, sticky="e")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(body, bg="#08111f", highlightthickness=0, bd=0, height=350, xscrollincrement=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.scrollbar = tk.Scrollbar(body, orient="horizontal", command=self._on_scrollbar)
        self.scrollbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=self.scrollbar.set)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Delete>", self._on_delete_pressed)
        self.canvas.bind("<Configure>", lambda _event: self._redraw())
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_mouse_wheel)
        self.canvas.focus_set()
        self._refresh_control_states()

    def set_lane_defaults(self, *, lane_a_text: str, lane_b_text: str) -> None:
        self._lane_defaults["A"] = lane_a_text
        self._lane_defaults["B"] = lane_b_text

    def set_media_sources(self, *, video_path: Path | None, music_tracks: list[Path]) -> None:
        self._video_path = video_path
        self._music_tracks = list(music_tracks)
        self._redraw()

    def bind_unassigned_music_tracks(self, *, notify: bool = False) -> bool:
        if not self._timeline.music_clips or not self._music_tracks:
            return False
        updated = bind_unassigned_music_clips(self._timeline.music_clips, self._music_tracks)
        changed = any(old.bound_track != new.bound_track for old, new in zip(self._timeline.music_clips, updated))
        if not changed:
            return False
        self._timeline.music_clips = self._normalize_lane_clips("Music", updated)  # type: ignore[assignment]
        if notify:
            self._emit_timeline_change()
        else:
            self._redraw_tracks_only()
        return True

    def _preview_music_assignment_map(self) -> dict[str, PreviewMusicAssignment]:
        return {
            assignment.clip_id: assignment
            for assignment in assign_preview_music_clips(self._timeline.music_clips, self._music_tracks)
        }

    def load_timeline(self, timeline: VideoTimelineProfile, duration: float) -> None:
        self._timeline = timeline.copy()
        self._duration = max(0.0, duration)
        self._playhead = max(0.0, min(self._playhead, self._duration))
        if self.has_time_range():
            self._set_time_range_internal(self._selected_range_start_sec or 0.0, self._selected_range_end_sec or 0.0)
        self._refresh_control_states()
        self._update_playhead_label()
        self._redraw()

    def read_timeline(self) -> VideoTimelineProfile:
        return self._timeline.copy()

    def read_view_state(self) -> tuple[float, float]:
        return self._pixels_per_second, self._left_time_sec

    def read_time_range(self) -> tuple[float | None, float | None]:
        return self._selected_range_start_sec, self._selected_range_end_sec

    def set_view_state(self, *, pixels_per_second: float, scroll_fraction: float) -> None:
        self._pixels_per_second = max(TIMELINE_MIN_PIXELS_PER_SECOND, min(TIMELINE_MAX_PIXELS_PER_SECOND, pixels_per_second))
        self._left_time_sec = max(0.0, scroll_fraction)
        self._redraw()

    def set_playhead(self, seconds: float, *, notify: bool = False) -> None:
        self._playhead = max(0.0, min(seconds, self._duration))
        self._update_playhead_label()
        self._update_playhead_overlay()
        self._refresh_control_states()
        if notify:
            self._on_playhead_change(self._playhead)

    def set_interaction_enabled(self, enabled: bool) -> None:
        self._interaction_enabled = enabled
        if not enabled:
            self._drag_mode = None
            self._drag_origin_clip = None
            self._range_drag_anchor_sec = None
        self._refresh_control_states()

    def delete_selected_clip(self) -> None:
        if self._selected_lane is None or self._selected_clip_id is None:
            return
        clips = [clip for clip in self._clips_for_lane(self._selected_lane) if clip.clip_id != self._selected_clip_id]
        self._set_clips_for_lane(self._selected_lane, clips)
        self._selected_clip_id = None
        self._on_selection_change(None, None)
        self._refresh_control_states()
        self._emit_timeline_change()

    def ensure_music_lane_visible(self) -> None:
        self._redraw_tracks_only()

    def select_clip(self, lane: TimelineLane | None, clip_id: str | None) -> None:
        self._selected_lane = lane
        self._selected_clip_id = clip_id
        if lane is not None:
            self._on_lane_focus(lane)
        self._on_selection_change(lane, clip_id)
        self._refresh_control_states()
        self._redraw_tracks_only()

    def create_clip(self, lane: TimelineLane, *, seconds: float | None = None, notify: bool = True) -> TimelineClip | None:
        if not self._interaction_enabled and notify:
            return None
        return self._create_clip(lane, self._playhead if seconds is None else seconds, notify=notify)

    def has_time_range(self) -> bool:
        return (
            self._selected_range_start_sec is not None
            and self._selected_range_end_sec is not None
            and (self._selected_range_end_sec - self._selected_range_start_sec) >= self.RANGE_MIN_SECONDS
        )

    def set_time_range(self, start_sec: float | None, end_sec: float | None) -> None:
        if start_sec is None or end_sec is None:
            self.clear_time_range()
            return
        self._set_time_range_internal(start_sec, end_sec)
        self._redraw_tracks_only()

    def clear_time_range(self) -> None:
        self._selected_range_start_sec = None
        self._selected_range_end_sec = None
        self._refresh_control_states()
        self._redraw_tracks_only()

    def toggle_range_mode(self) -> None:
        self._range_mode_enabled = False
        self._refresh_control_states()

    def apply_cut_to_range(self) -> None:
        if not self._interaction_enabled or not self.has_time_range():
            return
        range_start = self._selected_range_start_sec or 0.0
        range_end = self._selected_range_end_sec or range_start
        self._timeline = self._timeline.cut_range(range_start, range_end)
        if range_start <= self._playhead <= range_end:
            self.set_playhead(range_start, notify=True)
        self._selected_clip_id = None
        self._on_selection_change(self._selected_lane, None)
        self._emit_timeline_change()

    def split_availability_reason(self) -> str | None:
        if not self._interaction_enabled:
            return "Timeline is locked during generation."
        clip = self._selected_clip()
        if clip is None:
            return "Select a clip first."
        split_sec = round(self._playhead, 3)
        if not ((clip.start_sec + TIMELINE_MIN_CLIP_SECONDS) < split_sec < (clip.end_sec - TIMELINE_MIN_CLIP_SECONDS)):
            return "Place playhead inside selected clip."
        return None

    def can_split_selected_clip(self) -> bool:
        return self.split_availability_reason() is None

    def request_split_selected_clip(self) -> bool:
        return self.split_selected_clip()

    def split_selected_clip(self) -> bool:
        if not self._interaction_enabled or not self.can_split_selected_clip():
            return False
        lane = self._selected_lane
        clip = self._selected_clip()
        if lane is None or clip is None:
            return False

        split_sec = round(self._playhead, 3)
        clips = list(self._clips_for_lane(lane))
        music_assignments = self._preview_music_assignment_map() if lane == "Music" else {}
        updated: list[TimelineClip] = []
        new_clip_id: str | None = None
        for current in clips:
            if current.clip_id != clip.clip_id:
                updated.append(current)
                continue
            if isinstance(current, MusicClip) and not current.track_locked:
                assignment = music_assignments.get(current.clip_id)
                continuity_track = assignment.track if assignment is not None and assignment.track is not None else current.bound_track
                split_source = replace(current, bound_track=continuity_track, track_locked=False)
                left_clip = replace(split_source, end_sec=split_sec)
                right_clip = self._make_split_clip(split_source, start_sec=split_sec, end_sec=current.end_sec)
            else:
                left_clip = replace(current, end_sec=split_sec)
                right_clip = self._make_split_clip(current, start_sec=split_sec, end_sec=current.end_sec)
            updated.append(left_clip)
            updated.append(right_clip)
            new_clip_id = right_clip.clip_id

        self._set_clips_for_lane(lane, self._normalize_lane_clips(lane, updated))
        self._selected_clip_id = new_clip_id
        self._selected_range_start_sec = None
        self._selected_range_end_sec = None
        self._on_selection_change(lane, new_clip_id)
        self._refresh_control_states()
        self._emit_timeline_change()
        return True

    def scroll_to_end(self) -> None:
        self._left_time_sec = self._max_left_time()
        self._scroll_to_time(self._left_time_sec)

    def scroll_to_playhead(self) -> None:
        self._left_time_sec = self._playhead
        self._scroll_to_time(self._left_time_sec)

    def _timeline_left(self) -> float:
        return self.LEFT_PADDING + self.HEADER_WIDTH

    def _ruler_top(self) -> float:
        return self.TOP_PADDING

    def _thumb_top(self) -> float:
        return self._ruler_top() + self.RULER_HEIGHT + 8

    def _lane_origin_top(self) -> float:
        return self._thumb_top() + self.THUMBNAIL_HEIGHT + self.THUMBNAIL_GAP

    def _seconds_to_x(self, seconds: float) -> float:
        return self._timeline_left() + seconds * self._pixels_per_second

    def _x_to_seconds(self, canvas_x: float) -> float:
        return max(0.0, min(self._duration, (canvas_x - self._timeline_left()) / max(self._pixels_per_second, 1.0)))

    def _lane_top(self, lane: TimelineLane) -> float:
        index = [meta[0] for meta in self.LANE_META].index(lane)
        return self._lane_origin_top() + index * (self.TRACK_HEIGHT + self.TRACK_GAP)

    def _clip_rect(self, lane: TimelineLane, clip: TimelineClip) -> tuple[float, float, float, float]:
        top = self._lane_top(lane) + self.CLIP_MARGIN_Y
        left = self._seconds_to_x(clip.start_sec) + self.CLIP_MARGIN_X
        right = self._seconds_to_x(clip.end_sec) - self.CLIP_MARGIN_X
        bottom = self._lane_top(lane) + self.TRACK_HEIGHT - self.CLIP_MARGIN_Y
        return left, top, max(left + 6, right), bottom

    def _content_width(self) -> int:
        visible_width = max(1, self.canvas.winfo_width())
        trailing_room = max(self.RIGHT_PADDING, int(max(0, visible_width - self._timeline_left()) + self.RIGHT_PADDING))
        return max(visible_width, int(self._timeline_left() + self._duration * self._pixels_per_second + trailing_room))

    def _visible_canvas_x_bounds(self, *, padding: float = 56.0) -> tuple[float, float]:
        left = max(0.0, self.canvas.canvasx(0) - padding)
        right = self.canvas.canvasx(self.canvas.winfo_width()) + padding
        return left, right

    def _total_height(self) -> int:
        return int(self._lane_origin_top() + len(self.LANE_META) * (self.TRACK_HEIGHT + self.TRACK_GAP) + 18)

    def _redraw_tracks_only(self) -> None:
        if not self.winfo_exists():
            return
        if not self.canvas.cget("scrollregion"):
            self._redraw()
            return

        self._left_time_sec = self._canvas_left_time()
        full_width = self._content_width()
        total_height = self._total_height()
        self.canvas.configure(scrollregion=(0, 0, full_width, total_height))
        self.canvas.delete("tracks")
        self.canvas.delete("range")
        self.canvas.delete("playhead")
        self._draw_tracks(full_width)
        self._draw_range_overlay(total_height)
        self._draw_playhead(total_height)
        self._scroll_to_time(self._left_time_sec)
        self._update_playhead_label()

    def _redraw(self) -> None:
        if self.winfo_exists():
            self._left_time_sec = self._canvas_left_time()

        self.canvas.delete("all")
        self._thumbnail_refs.clear()
        self._playhead_line_item = None
        self._playhead_handle_item = None

        full_width = self._content_width()
        total_height = self._total_height()
        self.canvas.configure(scrollregion=(0, 0, full_width, total_height))

        self._draw_ruler(full_width)
        self._draw_thumbnail_strip(full_width)
        self._draw_tracks(full_width)
        self._draw_range_overlay(total_height)
        self._draw_playhead(total_height)

        self._scroll_to_time(self._left_time_sec)
        self._update_playhead_label()

    def _draw_ruler(self, full_width: int) -> None:
        top = self._ruler_top()
        bottom = top + self.RULER_HEIGHT
        self.canvas.create_rectangle(0, top, full_width, bottom, fill="#091423", outline="")
        self.canvas.create_text(
            self.LEFT_PADDING + 6,
            top + self.RULER_HEIGHT / 2,
            text="Video",
            fill="#f8fafc",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )

        if self._duration <= 0:
            return

        pixels_per_tick = 88
        seconds_per_tick = max(0.5, round(pixels_per_tick / max(self._pixels_per_second, 1.0), 1))
        tick = 0.0
        while tick <= self._duration + 0.001:
            x = self._seconds_to_x(tick)
            self.canvas.create_line(x, bottom - 10, x, bottom, fill="#475569", width=1)
            self.canvas.create_text(x + 2, top + 8, text=self._format_time(tick), fill="#94a3b8", anchor="nw", font=("Segoe UI", 9))
            tick += seconds_per_tick

    def _draw_thumbnail_strip(self, full_width: int) -> None:
        top = self._thumb_top()
        bottom = top + self.THUMBNAIL_HEIGHT
        left = self._timeline_left()
        right = full_width - self.RIGHT_PADDING
        self.canvas.create_rectangle(left, top, right, bottom, fill="#0c1629", outline="#16253c")
        thumb_size = (self.FILMSTRIP_TILE_WIDTH, self.THUMBNAIL_HEIGHT - 8)
        if self._duration <= 0 or self._video_path is None:
            self.canvas.create_text(
                left + 12,
                top + self.THUMBNAIL_HEIGHT / 2,
                text="Thumbnail strip appears after video is loaded.",
                fill="#64748b",
                anchor="w",
                font=("Segoe UI", 10),
            )
            return

        seconds_per_tile = max(0.2, self.FILMSTRIP_TILE_WIDTH / max(self._pixels_per_second, 1.0))
        visible_left, visible_right = self._visible_canvas_x_bounds(padding=self.FILMSTRIP_TILE_WIDTH * 2.0)
        visible_start_sec = max(0.0, self._x_to_seconds(max(left, visible_left)))
        visible_end_sec = min(self._duration, self._x_to_seconds(visible_right))
        start_bucket = max(0, int(math.floor(visible_start_sec / seconds_per_tile)) - 2)
        end_bucket = max(start_bucket + 1, int(math.ceil(visible_end_sec / seconds_per_tile)) + 2)
        missing_buckets: list[int] = []

        for bucket_index in range(start_bucket, end_bucket):
            bucket_start_sec = bucket_index * seconds_per_tile
            bucket_end_sec = min(self._duration, bucket_start_sec + seconds_per_tile)
            if bucket_end_sec <= bucket_start_sec:
                continue
            x1 = self._seconds_to_x(bucket_start_sec)
            x2 = self._seconds_to_x(bucket_end_sec)
            if x2 < visible_left or x1 > visible_right:
                continue

            tile = self._thumbnail_cache.peek_tile(
                self._video_path,
                bucket_index=bucket_index,
                seconds_per_tile=seconds_per_tile,
                size=thumb_size,
            )
            if tile is None:
                missing_buckets.append(bucket_index)
                self.canvas.create_rectangle(x1, top + 4, x2, bottom - 4, fill="#142238", outline="#1f3658")
                self.canvas.create_line(x1 + 8, bottom - 14, x2 - 8, top + 14, fill="#334155", width=1)
                continue

            draw_width = max(4, int(round(x2 - x1)))
            draw_image = tile.resize((draw_width, thumb_size[1]), Image.Resampling.BILINEAR) if draw_width != thumb_size[0] else tile
            photo = ImageTk.PhotoImage(draw_image, master=self.canvas)
            self._thumbnail_refs.append(photo)
            self.canvas.create_image(x1, top + 4, image=photo, anchor="nw")

        if missing_buckets:
            self._request_filmstrip_tiles(
                bucket_indices=missing_buckets,
                seconds_per_tile=seconds_per_tile,
                size=thumb_size,
            )

    def _draw_tracks(self, full_width: int) -> None:
        visible_left, visible_right = self._visible_canvas_x_bounds()
        music_assignments = self._preview_music_assignment_map()
        for lane, title, color in self.LANE_META:
            top = self._lane_top(lane)
            bottom = top + self.TRACK_HEIGHT
            self.canvas.create_rectangle(
                self.LEFT_PADDING,
                top,
                full_width - self.RIGHT_PADDING,
                bottom,
                fill="#0d182b",
                outline="#16253c",
                tags=("tracks",),
            )
            self.canvas.create_text(
                self.LEFT_PADDING + 8,
                top + 18,
                text=title,
                fill="#dbe4f0",
                font=("Segoe UI", 11, "bold"),
                anchor="w",
                tags=("tracks",),
            )
            self.canvas.create_text(
                self.LEFT_PADDING + 8,
                top + 41,
                text=self._lane_hint(lane),
                fill="#64748b",
                font=("Segoe UI", 9),
                anchor="w",
                tags=("tracks",),
            )

            lane_clips = self._clips_for_lane(lane)
            for clip in lane_clips:
                left, clip_top, right, clip_bottom = self._clip_rect(lane, clip)
                if right < visible_left or left > visible_right:
                    continue
                fill = color if clip.enabled else "#334155"
                outline = "#f8fafc" if clip.clip_id == self._selected_clip_id else "#0b1220"
                self.canvas.create_rectangle(
                    left,
                    clip_top,
                    right,
                    clip_bottom,
                    fill=fill,
                    outline=outline,
                    width=2 if clip.clip_id == self._selected_clip_id else 1,
                    tags=("tracks",),
                )
                self._draw_clip_contents(lane, clip, left, clip_top, right, clip_bottom, music_assignments.get(clip.clip_id))

            if lane == "Music" and not lane_clips:
                self.canvas.create_text(
                    self._timeline_left() + 16,
                    top + self.TRACK_HEIGHT / 2,
                    text="Double click or + Music creates clip at current playhead.",
                    fill="#8ea2c0",
                    anchor="w",
                    font=("Segoe UI", 10),
                    tags=("tracks",),
                )

    def _draw_clip_contents(
        self,
        lane: TimelineLane,
        clip: TimelineClip,
        left: float,
        top: float,
        right: float,
        bottom: float,
        music_assignment,
    ) -> None:
        header_y = top + 13
        title = self._clip_title(lane, clip, music_assignment)
        meta = self._clip_meta(clip)
        self.canvas.create_text(
            left + 10,
            header_y,
            text=title,
            fill="#f8fafc",
            anchor="w",
            font=("Segoe UI", 10, "bold"),
            tags=("tracks",),
        )
        self.canvas.create_text(
            left + 10,
            header_y + 18,
            text=meta,
            fill="#dbe4f0",
            anchor="w",
            font=("Segoe UI", 8),
            tags=("tracks",),
        )

        if lane == "Music" and music_assignment is not None and music_assignment.track is not None:
            self._draw_waveform(left + 8, top + 36, right - 8, bottom - 6, music_assignment.track)

    def _draw_waveform(self, left: float, top: float, right: float, bottom: float, track: Path) -> None:
        if right - left < 16 or bottom - top < 10:
            return
        points = max(24, int((right - left) / 4))
        peaks = self._waveform_cache.peek(track, points=points)
        if peaks is None:
            self._request_waveform(track, points=points)
            center_y = (top + bottom) / 2.0
            self.canvas.create_line(left, center_y, right, center_y, fill="#8fd7c9", width=1, tags=("tracks",))
            return
        center_y = (top + bottom) / 2.0
        width = right - left
        step = width / max(1, len(peaks))
        for index, peak in enumerate(peaks):
            x = left + index * step
            half = peak * (bottom - top) / 2.0
            self.canvas.create_line(x, center_y - half, x, center_y + half, fill="#d1fae5", width=1, tags=("tracks",))

    def _request_filmstrip_tiles(
        self,
        *,
        bucket_indices: list[int],
        seconds_per_tile: float,
        size: tuple[int, int],
    ) -> None:
        if self._video_path is None or not bucket_indices:
            return

        def on_ready() -> None:
            try:
                self.after(0, self._on_thumbnail_ready)
            except (tk.TclError, RuntimeError):
                return

        self._thumbnail_cache.request_filmstrip_async(
            self._video_path,
            bucket_indices=bucket_indices,
            seconds_per_tile=seconds_per_tile,
            duration=self._duration,
            size=size,
            callback=on_ready,
        )

    def _on_thumbnail_ready(self) -> None:
        if self.winfo_exists():
            self._redraw()

    def _request_waveform(self, track: Path, *, points: int) -> None:
        key = self._waveform_cache.key_for(track, points=points)
        if key is None or key in self._pending_waveform_keys:
            return
        self._pending_waveform_keys.add(key)

        def on_ready() -> None:
            try:
                self.after(0, lambda: self._on_waveform_ready(key))
            except (tk.TclError, RuntimeError):
                return

        self._waveform_cache.request_async(track, points=points, callback=on_ready)

    def _on_waveform_ready(self, key: str) -> None:
        self._pending_waveform_keys.discard(key)
        if self.winfo_exists():
            self._redraw_tracks_only()

    def _draw_playhead(self, total_height: int) -> None:
        playhead_x = self._seconds_to_x(self._playhead)
        self._playhead_line_item = self.canvas.create_line(
            playhead_x,
            self.TOP_PADDING,
            playhead_x,
            total_height - 6,
            fill="#f97316",
            width=2,
            tags=("playhead",),
        )
        self._playhead_handle_item = self.canvas.create_rectangle(
            playhead_x - 5,
            self.TOP_PADDING,
            playhead_x + 5,
            self.TOP_PADDING + 8,
            fill="#f97316",
            outline="",
            tags=("playhead",),
        )

    def _draw_range_overlay(self, total_height: int) -> None:
        if not self.has_time_range():
            return
        start_sec = self._selected_range_start_sec or 0.0
        end_sec = self._selected_range_end_sec or start_sec
        x1 = self._seconds_to_x(start_sec)
        x2 = self._seconds_to_x(end_sec)
        self.canvas.create_rectangle(
            x1,
            self.TOP_PADDING,
            x2,
            total_height - 6,
            fill="#1d4ed8",
            stipple="gray25",
            outline="#93c5fd",
            width=1,
            tags=("range",),
        )
        if x2 - x1 >= 90:
            self.canvas.create_text(
                x1 + 8,
                self.TOP_PADDING + 12,
                text=f"Cut {self._format_time(start_sec)} -> {self._format_time(end_sec)}",
                fill="#dbeafe",
                anchor="w",
                font=("Segoe UI", 9, "bold"),
                tags=("range",),
            )

    def _update_playhead_overlay(self) -> None:
        if self._playhead_line_item is None or self._playhead_handle_item is None:
            self._redraw()
            return
        total_height = self._total_height()
        playhead_x = self._seconds_to_x(self._playhead)
        self.canvas.coords(self._playhead_line_item, playhead_x, self.TOP_PADDING, playhead_x, total_height - 6)
        self.canvas.coords(self._playhead_handle_item, playhead_x - 5, self.TOP_PADDING, playhead_x + 5, self.TOP_PADDING + 8)

    def _lane_hint(self, lane: TimelineLane) -> str:
        if lane == "Music":
            return "bound track continuity"
        return "pool/sample"

    def _clip_title(self, lane: TimelineLane, clip: TimelineClip, music_assignment) -> str:
        if lane == "Music" and music_assignment is not None and music_assignment.track is not None:
            return music_assignment.track.name
        if lane == "Music":
            return "No track"
        if isinstance(clip, QuoteClip):
            source = "pool" if clip.source_mode == "pool" else "sample"
            return f"Quote {clip.lane} · {source}"
        return f"Clip {lane}"

    def _clip_meta(self, clip: TimelineClip) -> str:
        if isinstance(clip, MusicClip):
            return (
                f"{clip.start_sec:.1f}s -> {clip.end_sec:.1f}s · {clip.duration_sec:.1f}s · "
                f"offset {clip.track_offset_sec:.1f}s"
            )
        return f"{clip.start_sec:.1f}s -> {clip.end_sec:.1f}s · {clip.duration_sec:.1f}s"

    def _update_playhead_label(self) -> None:
        self.playhead_label.configure(text=f"{self._format_time(self._playhead)} / {self._format_time(self._duration)}")

    def _format_time(self, seconds: float) -> str:
        total = max(0.0, seconds)
        minutes = int(total // 60)
        remainder = total - minutes * 60
        return f"{minutes:02d}:{remainder:04.1f}"

    def _canvas_left_time(self) -> float:
        left_px = max(0.0, self.canvas.canvasx(0) - self._timeline_left())
        if self._pixels_per_second <= 0:
            return 0.0
        return max(0.0, left_px / self._pixels_per_second)

    def _max_left_time(self) -> float:
        visible_width = max(1, self.canvas.winfo_width())
        content_width = float(self._content_width())
        max_offset_px = max(0.0, content_width - visible_width)
        if self._pixels_per_second <= 0:
            return 0.0
        return max(0.0, (max_offset_px - self._timeline_left()) / self._pixels_per_second)

    def _scroll_to_time(self, seconds: float) -> None:
        self.update_idletasks()
        target_seconds = max(0.0, min(seconds, self._max_left_time()))
        scrollregion = self.canvas.cget("scrollregion")
        if not scrollregion:
            self._left_time_sec = target_seconds
            return
        x1, _y1, x2, _y2 = [float(value) for value in str(scrollregion).split()]
        total_width = max(1.0, x2 - x1)
        visible_width = max(1.0, self.canvas.winfo_width())
        max_offset = max(0.0, total_width - visible_width)
        target_offset = min(max_offset, max(0.0, self._timeline_left() + target_seconds * self._pixels_per_second))
        fraction = 0.0 if total_width <= 0 else target_offset / total_width
        self.canvas.xview_moveto(fraction)
        self._left_time_sec = target_seconds

    def _on_shift_mouse_wheel(self, event) -> str:
        if event.delta == 0:
            return "break"
        step_seconds = 0.8 if event.delta < 0 else -0.8
        self._left_time_sec = max(0.0, min(self._left_time_sec + step_seconds, self._max_left_time()))
        self._scroll_to_time(self._left_time_sec)
        return "break"

    def _on_scrollbar(self, *args) -> None:
        self.canvas.xview(*args)
        self._left_time_sec = self._canvas_left_time()

    def _change_zoom(self, factor: float) -> None:
        self._pixels_per_second = max(
            TIMELINE_MIN_PIXELS_PER_SECOND,
            min(TIMELINE_MAX_PIXELS_PER_SECOND, self._pixels_per_second * factor),
        )
        self._redraw()

    def reset_zoom(self) -> None:
        self._pixels_per_second = float(TIMELINE_DEFAULT_PIXELS_PER_SECOND)
        self._left_time_sec = 0.0
        self._redraw()

    def _clips_for_lane(self, lane: TimelineLane) -> list[TimelineClip]:
        return self._timeline.clips_for_lane(lane)

    def _set_clips_for_lane(self, lane: TimelineLane, clips: list[TimelineClip]) -> None:
        self._timeline.set_clips_for_lane(lane, clips)

    def _selected_clip(self) -> TimelineClip | None:
        if self._selected_lane is None or self._selected_clip_id is None:
            return None
        return next((clip for clip in self._clips_for_lane(self._selected_lane) if clip.clip_id == self._selected_clip_id), None)

    def _make_split_clip(self, clip: TimelineClip, *, start_sec: float, end_sec: float) -> TimelineClip:
        if isinstance(clip, QuoteClip):
            return QuoteClip(
                start_sec=start_sec,
                end_sec=end_sec,
                enabled=clip.enabled,
                lane=clip.lane,
                sample_text=clip.sample_text,
                source_mode=clip.source_mode,
            )
        if isinstance(clip, MusicClip):
            start_delta = start_sec - clip.start_sec
            return MusicClip(
                start_sec=start_sec,
                end_sec=end_sec,
                enabled=clip.enabled,
                volume=clip.volume,
                source_mode=clip.source_mode,
                bound_track=clip.bound_track,
                track_locked=clip.track_locked,
                track_offset_sec=max(0.0, round(clip.track_offset_sec + start_delta, 3)),
            )
        return TimelineClip(start_sec=start_sec, end_sec=end_sec, enabled=clip.enabled)

    def _lane_for_y(self, canvas_y: float) -> TimelineLane | None:
        for lane, _title, _color in self.LANE_META:
            top = self._lane_top(lane)
            bottom = top + self.TRACK_HEIGHT
            if top <= canvas_y <= bottom:
                return lane
        return None

    def _clip_at(self, lane: TimelineLane, seconds: float) -> TimelineClip | None:
        for clip in self._clips_for_lane(lane):
            if clip.start_sec <= seconds <= clip.end_sec:
                return clip
        return None

    def _near_clip_edge(self, clip: TimelineClip, seconds: float) -> str | None:
        threshold = self.HANDLE_HIT_PX / max(self._pixels_per_second, 1.0)
        if abs(seconds - clip.start_sec) <= threshold:
            return "resize_start"
        if abs(seconds - clip.end_sec) <= threshold:
            return "resize_end"
        return None

    def _on_press(self, event) -> None:
        self.canvas.focus_set()
        if not self._interaction_enabled:
            return

        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        seconds = self._x_to_seconds(canvas_x)

        if self._should_start_range_selection(event, canvas_y):
            self._drag_mode = "range"
            self._range_drag_anchor_sec = seconds
            self._selected_range_start_sec = seconds
            self._selected_range_end_sec = seconds
            self._refresh_control_states()
            self._redraw_tracks_only()
            return

        lane = self._lane_for_y(canvas_y)
        if lane is None:
            self._drag_mode = "playhead"
            self.set_playhead(seconds, notify=True)
            return

        clip = self._clip_at(lane, seconds)
        self._selected_lane = lane
        self._on_lane_focus(lane)
        if clip is None:
            self._selected_clip_id = None
            self._on_selection_change(lane, None)
            self._refresh_control_states()
            self._redraw_tracks_only()
            return

        self._selected_clip_id = clip.clip_id
        self._drag_origin_time = seconds
        self._drag_origin_clip = replace(clip)
        self._drag_mode = self._near_clip_edge(clip, seconds) or "move"
        self._on_selection_change(lane, clip.clip_id)
        self._refresh_control_states()
        self._redraw_tracks_only()

    def _on_double_click(self, event) -> None:
        if not self._interaction_enabled:
            return
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        lane = self._lane_for_y(canvas_y)
        if lane is None:
            return
        self._selected_lane = lane
        self._on_lane_focus(lane)
        self._create_clip(lane, self._x_to_seconds(canvas_x), notify=True)

    def _create_clip(self, lane: TimelineLane, seconds: float, *, notify: bool = True) -> TimelineClip:
        start_sec = max(0.0, min(seconds, self._duration))
        end_sec = min(self._duration, start_sec + TIMELINE_DEFAULT_CLIP_SECONDS)
        if end_sec - start_sec < TIMELINE_MIN_CLIP_SECONDS:
            start_sec = max(0.0, self._duration - TIMELINE_DEFAULT_CLIP_SECONDS)
            end_sec = self._duration
        if lane == "Music":
            new_clip = MusicClip(start_sec=start_sec, end_sec=end_sec, volume=1.0)
        else:
            new_clip = QuoteClip(
                start_sec=start_sec,
                end_sec=end_sec,
                lane=lane,
                sample_text=self._lane_defaults.get(lane, ""),
                source_mode="pool",
            )

        clips = list(self._clips_for_lane(lane))
        clips.append(new_clip)
        self._selected_lane = lane
        self._selected_clip_id = new_clip.clip_id
        self._on_selection_change(lane, new_clip.clip_id)
        self._set_clips_for_lane(lane, self._normalize_lane_clips(lane, clips))
        self.set_playhead(start_sec, notify=notify)
        self._emit_timeline_change()
        return new_clip

    def _on_drag(self, event) -> None:
        if not self._interaction_enabled or self._drag_mode is None:
            return

        canvas_x = self.canvas.canvasx(event.x)
        seconds = self._x_to_seconds(canvas_x)
        if self._drag_mode == "range":
            if self._range_drag_anchor_sec is None:
                return
            self._set_time_range_internal(self._range_drag_anchor_sec, seconds, allow_short=True)
            self._redraw_tracks_only()
            return
        if self._drag_mode == "playhead":
            self.set_playhead(seconds, notify=True)
            return

        if self._selected_lane is None or self._selected_clip_id is None or self._drag_origin_clip is None:
            return

        clips = list(self._clips_for_lane(self._selected_lane))
        current = next((clip for clip in clips if clip.clip_id == self._selected_clip_id), None)
        if current is None:
            return

        delta = seconds - self._drag_origin_time
        if self._drag_mode == "move":
            duration = self._drag_origin_clip.duration_sec
            start_sec = self._drag_origin_clip.start_sec + delta
            end_sec = start_sec + duration
            start_sec, end_sec = self._bounded_move(self._selected_lane, self._selected_clip_id, start_sec, end_sec)
            current.start_sec, current.end_sec = start_sec, end_sec
        elif self._drag_mode == "resize_start":
            start_sec = self._snap_time(self._selected_lane, self._selected_clip_id, seconds)
            if self._selected_lane == "Music":
                left_bound = 0.0
                for neighbour in clips:
                    if neighbour.clip_id == self._selected_clip_id:
                        continue
                    if neighbour.end_sec <= self._drag_origin_clip.start_sec:
                        left_bound = max(left_bound, neighbour.end_sec)
                start_sec = max(left_bound, min(start_sec, current.end_sec - TIMELINE_MIN_CLIP_SECONDS))
            current.start_sec = max(0.0, min(start_sec, current.end_sec - TIMELINE_MIN_CLIP_SECONDS))
            if isinstance(current, MusicClip) and isinstance(self._drag_origin_clip, MusicClip):
                delta_start = current.start_sec - self._drag_origin_clip.start_sec
                current.track_offset_sec = max(0.0, round(self._drag_origin_clip.track_offset_sec + delta_start, 3))
        elif self._drag_mode == "resize_end":
            end_sec = self._snap_time(self._selected_lane, self._selected_clip_id, seconds)
            current.end_sec = min(self._duration, max(end_sec, current.start_sec + TIMELINE_MIN_CLIP_SECONDS))

        self._set_clips_for_lane(self._selected_lane, self._normalize_lane_clips(self._selected_lane, clips))
        self._emit_timeline_change(redraw_only=True)

    def _on_release(self, _event) -> None:
        if self._drag_mode is None:
            return
        mode = self._drag_mode
        self._drag_mode = None
        self._drag_origin_clip = None
        if mode == "range":
            self._range_drag_anchor_sec = None
            if not self.has_time_range():
                self._selected_range_start_sec = None
                self._selected_range_end_sec = None
            self._refresh_control_states()
            self._redraw_tracks_only()
            return
        if mode != "playhead":
            self._emit_timeline_change()

    def _on_delete_pressed(self, _event=None) -> str:
        self.delete_selected_clip()
        return "break"

    def _on_cut_pressed(self, _event=None) -> str:
        self.request_split_selected_clip()
        return "break"

    def _bounded_move(self, lane: TimelineLane, clip_id: str, start_sec: float, end_sec: float) -> tuple[float, float]:
        duration = max(TIMELINE_MIN_CLIP_SECONDS, end_sec - start_sec)
        neighbours = [clip for clip in self._clips_for_lane(lane) if clip.clip_id != clip_id]
        left_bound = 0.0
        right_bound = self._duration

        for clip in neighbours:
            if self._drag_origin_clip is None:
                continue
            if clip.end_sec <= self._drag_origin_clip.start_sec:
                left_bound = max(left_bound, clip.end_sec)
            elif clip.start_sec >= self._drag_origin_clip.end_sec:
                right_bound = min(right_bound, clip.start_sec)
                break

        start_sec = max(left_bound, min(start_sec, right_bound - duration))
        end_sec = min(right_bound, start_sec + duration)
        start_sec = self._snap_time(lane, clip_id, start_sec)
        end_sec = start_sec + duration
        return round(start_sec, 3), round(end_sec, 3)

    def _snap_time(self, lane: TimelineLane, clip_id: str, candidate: float) -> float:
        snap_targets = [0.0, self._duration, self._playhead]
        for clip in self._clips_for_lane(lane):
            if clip.clip_id == clip_id:
                continue
            snap_targets.extend([clip.start_sec, clip.end_sec])
        for target in snap_targets:
            if abs(candidate - target) <= TIMELINE_SNAP_SECONDS:
                return target
        return max(0.0, min(candidate, self._duration))

    def _normalize_lane_clips(self, lane: TimelineLane, clips: list[TimelineClip]) -> list[TimelineClip]:
        normalized: list[TimelineClip] = []
        for clip in sorted(clips, key=lambda item: (item.start_sec, item.end_sec, item.clip_id)):
            copy_clip = replace(clip)
            self._fit_clip_between_neighbours(copy_clip, normalized)
            if isinstance(copy_clip, QuoteClip) and lane in {"A", "B"} and not copy_clip.sample_text:
                copy_clip.sample_text = self._lane_defaults.get(lane, "")
            if copy_clip.duration_sec >= TIMELINE_MIN_CLIP_SECONDS:
                normalized.append(copy_clip)
        return normalized

    def _fit_clip_between_neighbours(self, clip: TimelineClip, previous: list[TimelineClip]) -> None:
        clip.start_sec = max(0.0, min(clip.start_sec, self._duration))
        clip.end_sec = max(clip.start_sec + TIMELINE_MIN_CLIP_SECONDS, min(clip.end_sec, self._duration))
        if previous:
            clip.start_sec = max(clip.start_sec, previous[-1].end_sec)
            clip.end_sec = max(clip.end_sec, clip.start_sec + TIMELINE_MIN_CLIP_SECONDS)
        if clip.end_sec > self._duration:
            clip.end_sec = self._duration
        if clip.end_sec - clip.start_sec < TIMELINE_MIN_CLIP_SECONDS:
            clip.start_sec = max(0.0, self._duration - TIMELINE_MIN_CLIP_SECONDS)
            clip.end_sec = self._duration
        clip.start_sec = round(clip.start_sec, 3)
        clip.end_sec = round(clip.end_sec, 3)

    def _emit_timeline_change(self, *, redraw_only: bool = False) -> None:
        self._timeline.duration_hint = self._duration
        self._redraw_tracks_only()
        if not redraw_only:
            self._on_timeline_change(self._timeline.copy())

    def _refresh_control_states(self) -> None:
        state = "normal" if self._interaction_enabled else "disabled"
        for widget in (
            self.zoom_out_button,
            self.zoom_in_button,
            self.fit_button,
            self.playhead_button,
            self.end_button,
            self.add_music_button,
        ):
            widget.configure(state=state)
        split_reason = self.split_availability_reason()
        split_state = "normal" if split_reason is None else "disabled"
        self.cut_button.configure(state=split_state)
        self.range_button.configure(state="disabled")
        self.clear_range_button.configure(state="disabled")
        if split_reason is None:
            self.info_label.configure(text=self._default_info_text)
        else:
            self.info_label.configure(text=f"{self._default_info_text} Hint: {split_reason}")

    def _should_start_range_selection(self, event, canvas_y: float) -> bool:
        return False

    def _set_time_range_internal(self, start_sec: float, end_sec: float, *, allow_short: bool = False) -> None:
        clamped_start = max(0.0, min(start_sec, self._duration))
        clamped_end = max(0.0, min(end_sec, self._duration))
        start, end = sorted((round(clamped_start, 3), round(clamped_end, 3)))
        if not allow_short and (end - start) < self.RANGE_MIN_SECONDS:
            self._selected_range_start_sec = None
            self._selected_range_end_sec = None
        else:
            self._selected_range_start_sec = start
            self._selected_range_end_sec = end
        self._refresh_control_states()
