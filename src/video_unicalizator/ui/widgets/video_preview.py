from __future__ import annotations

import logging
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from typing import Literal

import customtkinter as ctk
import cv2
from PIL import Image, ImageTk

from video_unicalizator.config import PREVIEW_MAX_ZOOM, PREVIEW_MIN_ZOOM, PREVIEW_ZOOM_STEP, TARGET_HEIGHT, TARGET_WIDTH
from video_unicalizator.state import TextStyle, VideoEditProfile
from video_unicalizator.ui.widgets.draggable_text import DraggableTextOverlay
from video_unicalizator.utils.image_tools import fit_cover_frame

LayerKey = Literal["A", "B"]


class VideoPreviewWidget(ctk.CTkFrame):
    """Превью выбранного ролика с двумя редактируемыми слоями цитат."""

    def __init__(self, master, on_overlay_change, **kwargs) -> None:
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
        self.logger = logging.getLogger(self.__class__.__name__)

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, padx=14, pady=(10, 8), sticky="ew")
        toolbar.grid_columnconfigure(1, weight=1)

        self.title_label = ctk.CTkLabel(
            toolbar,
            text="Редактор кадра",
            font=ctk.CTkFont(family="Bahnschrift", size=20, weight="bold"),
            text_color="#f8fafc",
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self.layer_badges = ctk.CTkSegmentedButton(
            toolbar,
            values=["Цитата A", "Цитата B"],
            command=self._handle_layer_badge,
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            unselected_color="#16253c",
            unselected_hover_color="#1d3557",
        )
        self.layer_badges.grid(row=0, column=1, padx=(18, 10), sticky="w")
        self.layer_badges.set("Цитата A")

        controls = ctk.CTkFrame(toolbar, fg_color="transparent")
        controls.grid(row=0, column=2, sticky="e")

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
        self.stop_button.grid(row=0, column=5)

        self.canvas = tk.Canvas(self, bg="#08111f", highlightthickness=0, bd=0)
        self.canvas.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="nsew")

        self.status_label = ctk.CTkLabel(
            self,
            text="Переключайте видео справа, колесом масштабируйте кадр, drag по цитате двигает слой.",
            text_color="#94a3b8",
            anchor="w",
            justify="left",
        )
        self.status_label.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="ew")

        self._photo_image: ImageTk.PhotoImage | None = None
        self._frame_item: int | None = None
        self._capture: cv2.VideoCapture | None = None
        self._after_id: str | None = None
        self._is_playing = False
        self._fps = 30.0
        self._video_path: Path | None = None
        self._current_frame_rgb = None
        self._base_status_text = self.status_label.cget("text")
        self._resume_playback_after_interaction = False

        self._zoom_factor = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._viewport = (0, 0, 1, 1)
        self._interaction_enabled = True

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
        self._draw_placeholder()

    def _handle_layer_badge(self, value: str) -> None:
        self.set_active_layer("A" if value.endswith("A") else "B")

    def set_active_layer(self, layer: LayerKey) -> None:
        self._active_layer = layer
        self.layer_badges.set(f"Цитата {layer}")
        self._refresh_overlays()

    def load_profile(self, profile: VideoEditProfile) -> None:
        self._profile = profile.copy()
        self._refresh_overlays()

    def update_layer(self, layer: LayerKey, style: TextStyle) -> None:
        if layer == "A":
            self._profile.layer_a = replace(style)
        else:
            self._profile.layer_b = replace(style)
        self._refresh_overlays()

    def _refresh_overlays(self) -> None:
        self._overlay_a.update_scene(self._profile.layer_a, self._profile.layer_a.preview_text, self._viewport)
        self._overlay_b.update_scene(self._profile.layer_b, self._profile.layer_b.preview_text, self._viewport)
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
        self._refresh_scene()

    def _try_start_overlay(self, layer: LayerKey, event) -> bool:
        overlay = self._overlay_a if layer == "A" else self._overlay_b
        if overlay.start_interaction(event.x, event.y):
            self._pause_for_overlay_interaction()
            self._drag_mode = "overlay"
            self._active_overlay_id = layer
            self.set_active_layer(layer)
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
                self._refresh_overlays()
            return

        if self._drag_mode == "pan":
            delta_x = event.x - self._drag_start[0]
            delta_y = event.y - self._drag_start[1]
            self._pan_x = self._pan_start[0] + delta_x
            self._pan_y = self._pan_start[1] + delta_y
            self._refresh_scene()

    def _on_canvas_release(self, _event) -> None:
        if not self._interaction_enabled:
            self._drag_mode = None
            self.canvas.configure(cursor="")
            return
        if self._drag_mode == "overlay" and self._active_overlay_id is not None:
            overlay = self._overlay_a if self._active_overlay_id == "A" else self._overlay_b
            overlay.finish_interaction()
            self._refresh_overlays()
            self._resume_after_overlay_interaction()
        self._drag_mode = None
        self._active_overlay_id = None
        self.canvas.configure(cursor="")

    def _on_mouse_wheel(self, event) -> None:
        if not self._interaction_enabled:
            return
        factor = PREVIEW_ZOOM_STEP if event.delta > 0 else 1 / PREVIEW_ZOOM_STEP
        self._change_zoom(factor)

    def _change_zoom(self, factor: float) -> None:
        target_zoom = max(PREVIEW_MIN_ZOOM, min(PREVIEW_MAX_ZOOM, self._zoom_factor * factor))
        if abs(target_zoom - self._zoom_factor) < 0.001:
            return
        self._zoom_factor = target_zoom
        if self._zoom_factor <= 1.0:
            self._pan_x = 0.0
            self._pan_y = 0.0
        self._refresh_scene()

    def reset_viewport(self) -> None:
        self._zoom_factor = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._refresh_scene()

    def load_video(self, video_path: Path | None) -> None:
        self.stop()
        self._release_capture()
        self._video_path = video_path
        self._current_frame_rgb = None
        self.reset_viewport()
        if video_path is None:
            self._base_status_text = "Загрузите оригинал, чтобы увидеть живое превью."
            self.status_label.configure(text=self._base_status_text)
            self._draw_placeholder()
            return

        self._capture = cv2.VideoCapture(str(video_path))
        self._fps = self._capture.get(cv2.CAP_PROP_FPS) or 30.0
        self._base_status_text = video_path.name
        self.status_label.configure(text=self._base_status_text)
        self._render_current_frame()

    def toggle_playback(self) -> None:
        if self._capture is None or not self._interaction_enabled:
            return
        self._is_playing = not self._is_playing
        self.play_button.configure(text="Pause" if self._is_playing else "Play")
        if self._is_playing:
            self._play_loop()

    def restart(self) -> None:
        if self._capture is None:
            return
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._render_current_frame()
        if self._is_playing:
            self._play_loop()

    def stop(self) -> None:
        self._is_playing = False
        self.play_button.configure(text="Play")
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _play_loop(self) -> None:
        if not self._is_playing or self._capture is None:
            return
        ok = self._render_current_frame()
        if not ok:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self._render_current_frame()
        delay = max(15, int(1000 / max(self._fps, 1.0)))
        self._after_id = self.after(delay, self._play_loop)

    def _render_current_frame(self) -> bool:
        if self._capture is None:
            return False
        ok, frame = self._capture.read()
        if not ok:
            return False

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self._current_frame_rgb = fit_cover_frame(frame_rgb, target_width=TARGET_WIDTH, target_height=TARGET_HEIGHT)
        self._refresh_scene()
        return True

    def _refresh_scene(self) -> None:
        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        self._viewport = self._compute_viewport(canvas_width, canvas_height)
        viewport_x, viewport_y, viewport_width, viewport_height = self._viewport

        if self._current_frame_rgb is None:
            self._draw_placeholder()
        else:
            image = Image.fromarray(self._current_frame_rgb).resize((viewport_width, viewport_height), Image.Resampling.LANCZOS)
            self._photo_image = ImageTk.PhotoImage(image=image)
            if self._frame_item is None:
                self._frame_item = self.canvas.create_image(viewport_x, viewport_y, anchor="nw", image=self._photo_image)
            else:
                self.canvas.itemconfigure(self._frame_item, image=self._photo_image)
                self.canvas.coords(self._frame_item, viewport_x, viewport_y)

        self._refresh_overlays()

    def _draw_placeholder(self) -> None:
        canvas_width = max(320, self.canvas.winfo_width() or 405)
        canvas_height = max(568, self.canvas.winfo_height() or 720)
        self._viewport = self._compute_viewport(canvas_width, canvas_height)
        viewport_x, viewport_y, viewport_width, viewport_height = self._viewport

        image = Image.new("RGB", (viewport_width, viewport_height), "#08111f")
        self._photo_image = ImageTk.PhotoImage(image=image)
        if self._frame_item is None:
            self._frame_item = self.canvas.create_image(viewport_x, viewport_y, anchor="nw", image=self._photo_image)
        else:
            self.canvas.itemconfigure(self._frame_item, image=self._photo_image)
            self.canvas.coords(self._frame_item, viewport_x, viewport_y)
        self._refresh_overlays()

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

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def destroy(self) -> None:
        self.stop()
        self._release_capture()
        super().destroy()

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
        ):
            button.configure(state=button_state)
        self.layer_badges.configure(state=button_state)
        if not enabled:
            self.stop()
            self._drag_mode = None
            self._active_overlay_id = None
            self.canvas.configure(cursor="")

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
