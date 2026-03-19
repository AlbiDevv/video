from __future__ import annotations

import logging
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from typing import Callable

import customtkinter as ctk
import cv2
from PIL import Image, ImageTk

from video_unicalizator.config import (
    PREVIEW_EXACT_MAX_HEIGHT,
    PREVIEW_EXACT_MAX_WIDTH,
    PREVIEW_MAX_ZOOM,
    PREVIEW_MIN_ZOOM,
    PREVIEW_PROXY_MAX_HEIGHT,
    PREVIEW_PROXY_MAX_WIDTH,
    PREVIEW_STAGE_MAX_WIDTH,
    PREVIEW_STAGE_MIN_WIDTH,
    PREVIEW_ZOOM_STEP,
    TARGET_HEIGHT,
    TARGET_WIDTH,
)
from video_unicalizator.state import LayerKey, QuoteClip, TextStyle, VideoEditProfile
from video_unicalizator.ui.preview_support import PreviewPlaybackController, PreviewVideoWorker
from video_unicalizator.ui.widgets.draggable_text import DraggableTextOverlay
from video_unicalizator.utils.image_tools import fit_cover_frame

TimeChangeCallback = Callable[[float, float], None]


class VideoPreviewWidget(ctk.CTkFrame):
    """Превью выбранного ролика с редактируемыми дорожками цитат."""

    def __init__(
        self,
        master,
        on_overlay_change,
        on_overlay_focus=None,
        on_time_change=None,
        on_music_settings_change=None,
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
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._on_overlay_change = on_overlay_change
        self._on_overlay_focus = on_overlay_focus or (lambda _layer: None)
        self._on_time_change = on_time_change or (lambda _time, _duration: None)
        self._on_music_settings_change = on_music_settings_change or (lambda _enabled, _volume: None)
        self.logger = logging.getLogger(self.__class__.__name__)

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, padx=14, pady=(10, 8), sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            toolbar,
            text="Редактор кадра",
            font=ctk.CTkFont(family="Bahnschrift", size=20, weight="bold"),
            text_color="#f8fafc",
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        controls = ctk.CTkFrame(toolbar, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e")

        self.zoom_out_button = ctk.CTkButton(
            controls,
            text="-",
            width=34,
            height=30,
            corner_radius=10,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=lambda: self._change_zoom(1 / PREVIEW_ZOOM_STEP),
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
            command=lambda: self._change_zoom(PREVIEW_ZOOM_STEP),
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
            command=self.reset_viewport,
        )
        self.fit_button.grid(row=0, column=2, padx=(0, 10))

        self.play_button = ctk.CTkButton(controls, text="Play", width=68, height=30, corner_radius=10, command=self.toggle_playback)
        self.play_button.grid(row=0, column=3, padx=(0, 6))

        self.restart_button = ctk.CTkButton(
            controls,
            text="Restart",
            width=74,
            height=30,
            corner_radius=10,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=self.restart,
        )
        self.restart_button.grid(row=0, column=4, padx=(0, 6))

        self.stop_button = ctk.CTkButton(
            controls,
            text="Stop",
            width=60,
            height=30,
            corner_radius=10,
            fg_color="#16253c",
            hover_color="#1d3557",
            command=self.stop,
        )
        self.stop_button.grid(row=0, column=5, padx=(0, 10))

        self.music_preview_switch = ctk.CTkSwitch(
            controls,
            text="Music",
            progress_color="#22c55e",
            command=self._handle_audio_setting_change,
        )
        self.music_preview_switch.grid(row=0, column=6, padx=(0, 8))
        self.music_preview_switch.select()

        self.music_preview_slider = ctk.CTkSlider(
            controls,
            from_=0.0,
            to=1.5,
            number_of_steps=150,
            width=94,
            command=lambda _value: self._handle_audio_setting_change(),
            progress_color="#0f766e",
        )
        self.music_preview_slider.grid(row=0, column=7, padx=(0, 10))
        self.music_preview_slider.set(1.0)

        self.time_label = ctk.CTkLabel(controls, text="00:00.0 / 00:00.0", text_color="#dbe4f0")
        self.time_label.grid(row=0, column=8, sticky="e")

        self.stage_host = ctk.CTkFrame(self, fg_color="transparent")
        self.stage_host.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="nsew")
        self.stage_host.grid_rowconfigure(0, weight=1)
        self.stage_host.grid_columnconfigure(0, weight=1)
        self.stage_host.grid_columnconfigure(2, weight=1)

        self.stage_card = ctk.CTkFrame(
            self.stage_host,
            fg_color="#08111f",
            corner_radius=20,
            border_width=1,
            border_color="#16253c",
        )
        self.stage_card.grid(row=0, column=1, sticky="n")
        self.stage_card.grid_rowconfigure(0, weight=1)
        self.stage_card.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self.stage_card, bg="#08111f", highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.status_label = ctk.CTkLabel(
            self,
            text="Клик по цитате выбирает дорожку, drag двигает её, колесо мыши масштабирует кадр.",
            text_color="#94a3b8",
            anchor="w",
            justify="left",
        )
        self.status_label.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="ew")

        self._photo_image: ImageTk.PhotoImage | None = None
        self._frame_item: int | None = None
        self._capture: cv2.VideoCapture | None = None
        self._after_id: str | None = None
        self._proxy_after_id: str | None = None
        self._stage_resize_after_id: str | None = None
        self._is_playing = False
        self._fps = 30.0
        self._duration_sec = 0.0
        self._video_path: Path | None = None
        self._current_frame_rgb = None
        self._base_status_text = self.status_label.cget("text")
        self._resume_playback_after_interaction = False
        self._playback_controller: PreviewPlaybackController | None = None
        self._proxy_worker: PreviewVideoWorker | None = None
        self._proxy_frame_version = 0
        self._render_mode = "paused_exact"
        self._last_overlay_signature: tuple | None = None

        self._zoom_factor = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._viewport = (0, 0, 1, 1)
        self._interaction_enabled = True
        self._suspend_audio_setting_callbacks = False

        self._playhead_sec = 0.0
        self._active_layer: LayerKey = "A"
        self._active_overlay_id: LayerKey | None = None
        self._drag_mode: str | None = None
        self._drag_start = (0, 0)
        self._pan_start = (0.0, 0.0)

        self._profile = VideoEditProfile()
        self._overlay_a = DraggableTextOverlay(self.canvas, lambda style: self._handle_overlay_change("A", style))
        self._overlay_b = DraggableTextOverlay(self.canvas, lambda style: self._handle_overlay_change("B", style))

        self.canvas.bind("<Configure>", self._on_canvas_resized)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.stage_host.bind("<Configure>", self._schedule_stage_resize)
        self._draw_placeholder()

    @property
    def video_path(self) -> Path | None:
        return self._video_path

    def get_playhead(self) -> float:
        return self._playhead_sec

    def is_playing(self) -> bool:
        return self._is_playing

    def set_playback_controller(self, controller: PreviewPlaybackController | None) -> None:
        self._playback_controller = controller

    def load_profile(self, profile: VideoEditProfile) -> None:
        fallback_duration = self._duration_sec or profile.timeline.duration_hint or 12.0
        self._profile = profile.normalized_for_duration(fallback_duration)
        self._last_overlay_signature = None
        self._refresh_overlays(force=True)

    def update_layer(self, layer: LayerKey, style: TextStyle) -> None:
        if layer == "A":
            self._profile.layer_a = replace(style)
        else:
            self._profile.layer_b = replace(style)
        self._last_overlay_signature = None
        self._refresh_overlays(force=True)

    def set_active_layer(self, layer: LayerKey) -> None:
        self._active_layer = layer
        self._last_overlay_signature = None
        self._refresh_overlays(force=True)

    def set_playhead(self, seconds: float, *, from_playback: bool = False) -> None:
        target = max(0.0, min(seconds, self._duration_sec))
        if not from_playback and self._playback_controller is not None:
            self._playback_controller.handle_external_seek()
        self._playhead_sec = target
        self._update_time_label()
        if self._capture is not None:
            self._seek_capture(target)
            self._render_current_frame()
        else:
            self._last_overlay_signature = None
            self._refresh_overlays(force=True)
            self._notify_time_change()

    def get_duration(self) -> float:
        return self._duration_sec

    def get_playback_proxy_size(self) -> tuple[int, int]:
        viewport_width = self._viewport[2] if self._viewport[2] > 1 else 0
        viewport_height = self._viewport[3] if self._viewport[3] > 1 else 0
        canvas_width = max(PREVIEW_STAGE_MIN_WIDTH, viewport_width or self.canvas.winfo_width() or PREVIEW_STAGE_MAX_WIDTH)
        canvas_height = max(420, viewport_height or self.canvas.winfo_height() or int(PREVIEW_STAGE_MAX_WIDTH * TARGET_HEIGHT / TARGET_WIDTH))
        width = min(PREVIEW_PROXY_MAX_WIDTH, canvas_width)
        height = min(PREVIEW_PROXY_MAX_HEIGHT, canvas_height)
        return max(200, width), max(356, height)

    def load_video(self, video_path: Path | None) -> None:
        self.stop()
        self._release_capture()
        self._video_path = video_path
        self._current_frame_rgb = None
        self._duration_sec = 0.0
        self._playhead_sec = 0.0
        self._last_overlay_signature = None
        self.reset_viewport()
        if video_path is None:
            self._base_status_text = "Загрузите оригинал, чтобы увидеть живое превью."
            self.status_label.configure(text=self._base_status_text)
            self._update_time_label()
            self._draw_placeholder()
            self._notify_time_change()
            return

        self._capture = cv2.VideoCapture(str(video_path))
        self._fps = self._capture.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(self._capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        self._duration_sec = frame_count / max(self._fps, 1.0)
        self._profile = self._profile.normalized_for_duration(self._duration_sec)
        self._base_status_text = video_path.name
        self.status_label.configure(text=self._base_status_text)
        self._update_time_label()
        self._render_current_frame()
        self._notify_time_change()

    def toggle_playback(self) -> None:
        if self._capture is None or not self._interaction_enabled:
            return
        if self._playback_controller is not None:
            self._playback_controller.toggle_playback()
            return
        if self._is_playing:
            self._pause_local_playback()
        else:
            self._start_local_playback()

    def restart(self) -> None:
        if self._capture is None:
            return
        if self._playback_controller is not None:
            self._playback_controller.restart()
            return
        self._restart_local_playback()

    def stop(self) -> None:
        if self._playback_controller is not None:
            self._playback_controller.stop()
            return
        self._stop_local_playback()

    def set_runtime_status(self, text: str | None) -> None:
        self.status_label.configure(text=text or self._base_status_text)

    def set_interaction_enabled(self, enabled: bool) -> None:
        self._interaction_enabled = enabled
        button_state = "normal" if enabled else "disabled"
        for button in (
            self.zoom_out_button,
            self.zoom_in_button,
            self.fit_button,
            self.play_button,
            self.restart_button,
            self.stop_button,
            self.music_preview_switch,
            self.music_preview_slider,
        ):
            button.configure(state=button_state)
        if not enabled:
            self.stop()
            self._drag_mode = None
            self._active_overlay_id = None
            self.canvas.configure(cursor="")

    def reset_viewport(self) -> None:
        self._zoom_factor = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._last_overlay_signature = None
        self._refresh_scene(force_overlay=True)

    def _seek_capture(self, seconds: float) -> None:
        if self._capture is None:
            return
        frame_number = max(0, int(round(seconds * max(self._fps, 1.0))))
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

    def _render_current_frame(self) -> bool:
        if self._capture is None:
            return False
        ok, frame = self._capture.read()
        if not ok:
            return False

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        target_width, target_height = self._exact_frame_target_size()
        self._current_frame_rgb = fit_cover_frame(frame_rgb, target_width=target_width, target_height=target_height)
        self._update_playhead_from_capture()
        self._refresh_scene(force_overlay=True)
        self._notify_time_change()
        return True

    def _update_playhead_from_capture(self) -> None:
        if self._capture is None:
            return
        time_sec = self._capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if time_sec <= 0.0:
            frame_index = self._capture.get(cv2.CAP_PROP_POS_FRAMES)
            time_sec = max(0.0, frame_index / max(self._fps, 1.0))
        self._playhead_sec = max(0.0, min(time_sec, self._duration_sec))
        self._update_time_label()

    def _notify_time_change(self) -> None:
        self._on_time_change(self._playhead_sec, self._duration_sec)

    def _update_time_label(self) -> None:
        self.time_label.configure(
            text=f"{self._format_time(self._playhead_sec)} / {self._format_time(self._duration_sec)}"
        )

    def _format_time(self, seconds: float) -> str:
        total = max(0.0, seconds)
        minutes = int(total // 60)
        remainder = total - minutes * 60
        return f"{minutes:02d}:{remainder:04.1f}"

    def _refresh_scene(self, *, force_overlay: bool = False) -> None:
        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        self._viewport = self._compute_viewport(canvas_width, canvas_height)
        viewport_x, viewport_y, viewport_width, viewport_height = self._viewport

        if self._current_frame_rgb is None:
            self._draw_placeholder()
        else:
            current_height, current_width = self._current_frame_rgb.shape[:2]
            image = Image.fromarray(self._current_frame_rgb)
            if current_width != viewport_width or current_height != viewport_height:
                resample = Image.Resampling.BILINEAR if self._render_mode == "playback_proxy" else Image.Resampling.LANCZOS
                image = image.resize((viewport_width, viewport_height), resample)
            self._photo_image = ImageTk.PhotoImage(image=image, master=self.canvas)
            if self._frame_item is None:
                self._frame_item = self.canvas.create_image(viewport_x, viewport_y, anchor="nw", image=self._photo_image)
            else:
                self.canvas.itemconfigure(self._frame_item, image=self._photo_image)
                self.canvas.coords(self._frame_item, viewport_x, viewport_y)

        self._refresh_overlays(force=force_overlay)

    def _draw_placeholder(self) -> None:
        canvas_width = max(320, self.canvas.winfo_width() or 405)
        canvas_height = max(568, self.canvas.winfo_height() or 720)
        self._viewport = self._compute_viewport(canvas_width, canvas_height)
        viewport_x, viewport_y, viewport_width, viewport_height = self._viewport

        image = Image.new("RGB", (viewport_width, viewport_height), "#08111f")
        self._photo_image = ImageTk.PhotoImage(image=image, master=self.canvas)
        if self._frame_item is None:
            self._frame_item = self.canvas.create_image(viewport_x, viewport_y, anchor="nw", image=self._photo_image)
        else:
            self.canvas.itemconfigure(self._frame_item, image=self._photo_image)
            self.canvas.coords(self._frame_item, viewport_x, viewport_y)
        self._refresh_overlays(force=True)

    def _compute_viewport(self, canvas_width: int, canvas_height: int) -> tuple[int, int, int, int]:
        fit_scale = min(canvas_width / TARGET_WIDTH, canvas_height / TARGET_HEIGHT)
        display_scale = fit_scale * self._zoom_factor
        viewport_width = max(1, int(round(TARGET_WIDTH * display_scale)))
        viewport_height = max(1, int(round(TARGET_HEIGHT * display_scale)))

        if self._zoom_factor <= 1.0:
            self._pan_x = 0.0
            self._pan_y = 0.0

        center_x = (canvas_width - viewport_width) / 2.0 + self._pan_x
        center_y = (canvas_height - viewport_height) / 2.0 + self._pan_y

        if viewport_width > canvas_width:
            center_x = min(0.0, max(canvas_width - viewport_width, center_x))
        else:
            center_x = (canvas_width - viewport_width) / 2.0

        if viewport_height > canvas_height:
            center_y = min(0.0, max(canvas_height - viewport_height, center_y))
        else:
            center_y = (canvas_height - viewport_height) / 2.0

        self._pan_x = center_x - (canvas_width - viewport_width) / 2.0
        self._pan_y = center_y - (canvas_height - viewport_height) / 2.0
        return int(round(center_x)), int(round(center_y)), viewport_width, viewport_height

    def _point_inside_viewport(self, canvas_x: int, canvas_y: int) -> bool:
        viewport_x, viewport_y, viewport_width, viewport_height = self._viewport
        return viewport_x <= canvas_x <= viewport_x + viewport_width and viewport_y <= canvas_y <= viewport_y + viewport_height

    def _effective_quote_state(self, layer: LayerKey) -> tuple[TextStyle, str]:
        lane_style = self._profile.layer_a if layer == "A" else self._profile.layer_b
        active_clip = self._profile.timeline.active_quote_clip(layer, self._playhead_sec)
        if not lane_style.enabled or active_clip is None or not active_clip.enabled:
            return replace(lane_style, enabled=False), ""

        effective_text = (active_clip.sample_text or lane_style.preview_text).strip()
        if not effective_text:
            return replace(lane_style, enabled=False), ""

        return replace(lane_style, preview_text=effective_text, enabled=True), effective_text

    def _refresh_overlays(self, *, force: bool = False) -> None:
        style_a, text_a = self._effective_quote_state("A")
        style_b, text_b = self._effective_quote_state("B")
        signature = (
            self._active_layer,
            self._viewport,
            self._layer_signature(style_a, text_a),
            self._layer_signature(style_b, text_b),
        )
        self._overlay_a.set_highlighted(self._active_layer == "A")
        self._overlay_b.set_highlighted(self._active_layer == "B")
        if not force and signature == self._last_overlay_signature:
            if self._active_layer == "A":
                self._overlay_b.lift()
                self._overlay_a.lift()
            else:
                self._overlay_a.lift()
                self._overlay_b.lift()
            return

        self._overlay_a.update_scene(style_a, text_a, self._viewport)
        self._overlay_b.update_scene(style_b, text_b, self._viewport)
        self._last_overlay_signature = signature
        if self._active_layer == "A":
            self._overlay_b.lift()
            self._overlay_a.lift()
        else:
            self._overlay_a.lift()
            self._overlay_b.lift()

    def _handle_overlay_change(self, layer: LayerKey, style: TextStyle) -> None:
        try:
            if layer == "A":
                self._profile.layer_a = replace(style)
            else:
                self._profile.layer_b = replace(style)
            self.set_active_layer(layer)
            self._on_overlay_change(layer, style)
        except Exception:  # noqa: BLE001
            self.logger.exception("Failed to apply overlay changes for layer %s", layer)
            self.set_runtime_status("Ошибка обновления цитаты. Последнее изменение не применено.")

    def _on_canvas_resized(self, _event) -> None:
        self._last_overlay_signature = None
        self._refresh_scene(force_overlay=True)

    def _try_start_overlay(self, layer: LayerKey, event) -> bool:
        overlay = self._overlay_a if layer == "A" else self._overlay_b
        if overlay.start_interaction(event.x, event.y):
            self._pause_for_overlay_interaction()
            self._drag_mode = "overlay"
            self._active_overlay_id = layer
            self.set_active_layer(layer)
            self._on_overlay_focus(layer)
            return True
        return False

    def _on_canvas_press(self, event) -> None:
        if not self._interaction_enabled:
            return

        overlay_order = [self._active_layer, "B" if self._active_layer == "A" else "A"]
        for layer in overlay_order:
            if self._try_start_overlay(layer, event):
                return

        if self._zoom_factor > 1.0 and self._point_inside_viewport(event.x, event.y):
            self._drag_mode = "pan"
            self._drag_start = (event.x, event.y)
            self._pan_start = (self._pan_x, self._pan_y)
            self.canvas.configure(cursor="fleur")
            return

        self._drag_mode = None

    def _on_canvas_drag(self, event) -> None:
        if not self._interaction_enabled:
            return
        if self._drag_mode == "overlay" and self._active_overlay_id is not None:
            overlay = self._overlay_a if self._active_overlay_id == "A" else self._overlay_b
            if overlay.drag_to(event.x, event.y):
                self._last_overlay_signature = None
                self._refresh_overlays(force=True)
            return

        if self._drag_mode == "pan":
            delta_x = event.x - self._drag_start[0]
            delta_y = event.y - self._drag_start[1]
            self._pan_x = self._pan_start[0] + delta_x
            self._pan_y = self._pan_start[1] + delta_y
            self._last_overlay_signature = None
            self._refresh_scene(force_overlay=True)

    def _on_canvas_release(self, _event) -> None:
        if not self._interaction_enabled:
            self._drag_mode = None
            self.canvas.configure(cursor="")
            return
        if self._drag_mode == "overlay" and self._active_overlay_id is not None:
            overlay = self._overlay_a if self._active_overlay_id == "A" else self._overlay_b
            overlay.finish_interaction()
            self._last_overlay_signature = None
            self._refresh_overlays(force=True)
            self._resume_after_overlay_interaction()
        self._drag_mode = None
        self._active_overlay_id = None
        self.canvas.configure(cursor="")

    def _on_mouse_wheel(self, event) -> None:
        if not self._interaction_enabled:
            return
        factor = PREVIEW_ZOOM_STEP if event.delta > 0 else 1 / PREVIEW_ZOOM_STEP
        self._change_zoom(factor)

    def _handle_audio_setting_change(self) -> None:
        if self._suspend_audio_setting_callbacks:
            return
        enabled, volume = self.read_music_preview_settings()
        self._on_music_settings_change(enabled, volume)
        if self._playback_controller is not None and self._is_playing:
            self._playback_controller.restart()
        elif self._playback_controller is not None:
            self._playback_controller.schedule_audio_prewarm()

    def _change_zoom(self, factor: float) -> None:
        target_zoom = max(PREVIEW_MIN_ZOOM, min(PREVIEW_MAX_ZOOM, self._zoom_factor * factor))
        if abs(target_zoom - self._zoom_factor) < 0.001:
            return
        self._zoom_factor = target_zoom
        if self._zoom_factor <= 1.0:
            self._pan_x = 0.0
            self._pan_y = 0.0
        self._last_overlay_signature = None
        self._refresh_scene(force_overlay=True)

    def _pause_for_overlay_interaction(self) -> None:
        self._resume_playback_after_interaction = False
        if self._is_playing:
            self._resume_playback_after_interaction = True
            self.stop()
        self.set_runtime_status("Редактирование цитаты: превью временно поставлено на паузу.")

    def _resume_after_overlay_interaction(self) -> None:
        self.set_runtime_status(None)
        if self._resume_playback_after_interaction:
            self._resume_playback_after_interaction = False
            self.toggle_playback()

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def read_music_preview_settings(self) -> tuple[bool, float]:
        return bool(self.music_preview_switch.get()), float(self.music_preview_slider.get())

    def set_music_preview_settings(
        self,
        *,
        enabled: bool | None = None,
        volume: float | None = None,
        notify: bool = False,
    ) -> None:
        self._suspend_audio_setting_callbacks = True
        try:
            if enabled is not None:
                if enabled:
                    self.music_preview_switch.select()
                else:
                    self.music_preview_switch.deselect()
            if volume is not None:
                clamped = max(0.0, min(1.5, float(volume)))
                self.music_preview_slider.set(clamped)
        finally:
            self._suspend_audio_setting_callbacks = False
        if notify:
            self._handle_audio_setting_change()

    def _start_local_playback(self) -> None:
        if self._capture is None:
            return
        self._is_playing = True
        self._render_mode = "playback_proxy"
        self.play_button.configure(text="Pause")
        self.set_runtime_status("Preview: запускаю playback...")
        if self._proxy_worker is None:
            self._schedule_legacy_playback()

    def _pause_local_playback(self) -> None:
        self._is_playing = False
        self._render_mode = "paused_exact"
        self.play_button.configure(text="Play")
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self._proxy_after_id:
            self.after_cancel(self._proxy_after_id)
            self._proxy_after_id = None
        self._proxy_worker = None
        if self._capture is not None:
            self._seek_capture(self._playhead_sec)
            self._render_current_frame()
        else:
            self._last_overlay_signature = None
            self._refresh_overlays(force=True)

    def _stop_local_playback(self) -> None:
        self._pause_local_playback()

    def _restart_local_playback(self) -> None:
        if self._capture is None:
            return
        self._pause_local_playback()
        self._seek_capture(0.0)
        self._render_current_frame()
        self._notify_time_change()

    def start_proxy_playback(self, worker: PreviewVideoWorker) -> None:
        self._proxy_worker = worker
        self._proxy_frame_version = 0
        self._start_local_playback()
        self._schedule_proxy_poll()

    def _schedule_proxy_poll(self) -> None:
        if self._proxy_after_id is not None:
            self.after_cancel(self._proxy_after_id)
        self._proxy_after_id = self.after(16, self._poll_proxy_worker)

    def _schedule_legacy_playback(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self._after_id = self.after(16, self._legacy_play_loop)

    def _legacy_play_loop(self) -> None:
        self._after_id = None
        if not self._is_playing or self._capture is None or self._proxy_worker is not None:
            return
        ok = self._render_current_frame()
        if not ok:
            self._pause_local_playback()
            self.set_runtime_status(None)
            return
        delay = max(15, int(1000 / max(min(self._fps, 24.0), 1.0)))
        self._after_id = self.after(delay, self._legacy_play_loop)

    def _poll_proxy_worker(self) -> None:
        self._proxy_after_id = None
        if not self._is_playing or self._proxy_worker is None:
            return

        version, packet = self._proxy_worker.buffer.read(self._proxy_frame_version)
        if packet is not None:
            self._proxy_frame_version = version
            if packet.frame_rgb is not None:
                self._current_frame_rgb = packet.frame_rgb
                self._playhead_sec = max(0.0, min(packet.playhead_sec, self._duration_sec))
                self._update_time_label()
                self._refresh_scene(force_overlay=False)
                self._notify_time_change()
            if packet.finished:
                self._pause_local_playback()
                self.set_runtime_status(None)
                return

        if self._proxy_worker.is_running():
            self._schedule_proxy_poll()
        else:
            self._pause_local_playback()
            self.set_runtime_status(None)

    def _exact_frame_target_size(self) -> tuple[int, int]:
        canvas_width = max(PREVIEW_STAGE_MIN_WIDTH, self.canvas.winfo_width() or PREVIEW_STAGE_MAX_WIDTH)
        canvas_height = max(420, self.canvas.winfo_height() or int(PREVIEW_STAGE_MAX_WIDTH * TARGET_HEIGHT / TARGET_WIDTH))
        width = min(PREVIEW_EXACT_MAX_WIDTH, canvas_width)
        height = min(PREVIEW_EXACT_MAX_HEIGHT, canvas_height)
        return max(320, width), max(568, height)

    def _layer_signature(self, style: TextStyle, text: str) -> tuple:
        return (
            style.enabled,
            text,
            style.position_x,
            style.position_y,
            style.box_width_ratio,
            style.font_size,
            style.font_name,
            style.text_color,
            style.background_color,
            style.background_opacity,
            style.shadow_strength,
            style.corner_radius,
            style.text_align,
            style.line_spacing,
        )

    def _schedule_stage_resize(self, _event=None) -> None:
        if self._stage_resize_after_id is not None:
            self.after_cancel(self._stage_resize_after_id)
        self._stage_resize_after_id = self.after_idle(self._resize_stage_canvas)

    def _resize_stage_canvas(self) -> None:
        self._stage_resize_after_id = None
        host_width = max(1, self.stage_host.winfo_width())
        host_height = max(1, self.stage_host.winfo_height())
        available_width = max(220, host_width - 28)
        available_height = max(360, host_height - 12)
        target_width = min(PREVIEW_STAGE_MAX_WIDTH, available_width)
        target_height = int(round(target_width * TARGET_HEIGHT / TARGET_WIDTH))
        if target_height > available_height:
            target_height = available_height
            target_width = int(round(target_height * TARGET_WIDTH / TARGET_HEIGHT))
        target_width = max(min(available_width, target_width), min(220, available_width))
        target_height = max(min(available_height, target_height), min(360, available_height))
        self.canvas.configure(width=target_width, height=target_height)
        self.stage_card.configure(width=target_width, height=target_height)
        self._last_overlay_signature = None
        self._refresh_scene(force_overlay=True)

    def destroy(self) -> None:
        if self._playback_controller is not None:
            self._playback_controller.shutdown()
        self.stop()
        if self._stage_resize_after_id is not None:
            self.after_cancel(self._stage_resize_after_id)
        self._release_capture()
        super().destroy()
